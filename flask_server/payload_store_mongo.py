"""MongoDB-backed payload store for KYC orchestration.

This module provides persistent storage for overall KYC payloads (master_json + ml_input_json)
using MongoDB. It uses the same database as the users collection.

SECURITY: Sensitive fields (Aadhaar, PAN, DOB, etc.) are automatically encrypted before
storage and decrypted on retrieval. This prevents exposure of PII in the database.

Usage:
    from flask_server.payload_store_mongo import MongoPayloadStore
    from pymongo import MongoClient
    
    client = MongoClient("mongodb://localhost:27017/")
    db = client["kyc_app"]
    store = MongoPayloadStore(db)  # Uses payloads collection with encryption
    
    payload = OverallPayload(
        user_id="user123",
        master_json={"verification_status": {...}},
        ml_input_json={"age": 30, "gross_income": 500000, ...}
    )
    store.save(payload)  # Sensitive fields encrypted automatically
    retrieved = store.get("user123")  # Decrypted on retrieval
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

# Import OverallPayload from KYC
import sys
from pathlib import Path
kyc_dir = Path(__file__).resolve().parent.parent / "KYC"
if str(kyc_dir) not in sys.path:
    sys.path.insert(0, str(kyc_dir))

from payload_store import OverallPayload

# Import encryption utilities
try:
    from encryption_utils import (
        SensitiveDataEncryptor,
        get_encryptor,
        encrypt_payload,
        decrypt_payload,
        mask_payload,
        CRYPTO_AVAILABLE,
    )
    ENCRYPTION_ENABLED = CRYPTO_AVAILABLE
except ImportError:
    ENCRYPTION_ENABLED = False
    get_encryptor = None

logger = logging.getLogger(__name__)


class MongoPayloadStore:
    """MongoDB-backed store for KYC payloads with automatic encryption.
    
    This implementation uses MongoDB for persistent storage. It stores payloads
    in a separate collection from users for better performance and separation of concerns.
    
    SECURITY: Sensitive fields in master_json are automatically encrypted before
    storage and decrypted on retrieval. Set encrypt_sensitive=False to disable.
    
    Collection: payloads
    Document structure:
    {
        "_id": ObjectId(user_id),
        "user_id": "6932eafade8ac2f8b00c1174",
        "master_json": {...},  // Encrypted sensitive fields
        "ml_input_json": {...},  // Plain text
        "status": "completed",
        "created_at": ISODate(...),
        "updated_at": ISODate(...),
        "metadata": {...}
    }
    """

    def __init__(
        self,
        db: Database,
        encrypt_sensitive: bool = True,
    ):
        self.db = db
        self.collection = db.payloads
        self.encrypt_sensitive = encrypt_sensitive and ENCRYPTION_ENABLED
        self._encryptor = get_encryptor() if self.encrypt_sensitive and get_encryptor else None
        self._init_indexes()
        
        if self.encrypt_sensitive:
            logger.info("MongoPayloadStore: Encryption ENABLED for sensitive fields")
        else:
            logger.warning("MongoPayloadStore: Encryption DISABLED - sensitive data stored in plaintext")

    def _init_indexes(self) -> None:
        """Initialize database indexes."""
        try:
            # Index on status for filtering
            self.collection.create_index("status", name="idx_payloads_status")
            
            # Index on created_at for sorting
            self.collection.create_index("created_at", name="idx_payloads_created_at")
            
            # Compound index for common queries (status + created_at)
            self.collection.create_index(
                [("status", 1), ("created_at", -1)],
                name="idx_payloads_status_created_at"
            )
            
            logger.info("MongoPayloadStore: Indexes initialized")
        except Exception as e:
            logger.warning(f"MongoPayloadStore: Failed to create indexes: {e}")

    def save(self, payload: OverallPayload) -> str:
        """Save or update a payload. Returns user_id.
        
        Sensitive fields in master_json are automatically encrypted before storage.
        Uses user_id as _id for efficient lookups.
        """
        now = datetime.utcnow()
        payload.updated_at = now.isoformat()
        
        if payload.created_at is None:
            payload.created_at = now.isoformat()
        
        # Encrypt sensitive fields in master_json before storage
        master_json_to_store = payload.master_json
        if self._encryptor and self.encrypt_sensitive:
            try:
                master_json_to_store = self._encryptor.encrypt_sensitive_fields(payload.master_json)
                logger.debug("Encrypted sensitive fields for user_id=%s", payload.user_id)
            except Exception as e:
                logger.warning(f"Failed to encrypt sensitive fields: {e}")
                master_json_to_store = payload.master_json
        
        # Convert user_id to ObjectId for _id
        try:
            user_object_id = ObjectId(payload.user_id)
        except Exception:
            # If user_id is not a valid ObjectId, use it as string
            user_object_id = payload.user_id
        
        # Prepare document
        document = {
            "_id": user_object_id,  # Use user_id as _id
            "user_id": payload.user_id,  # Keep as string for reference
            "master_json": master_json_to_store,
            "ml_input_json": payload.ml_input_json,
            "status": payload.status,
            "created_at": now,  # MongoDB Date
            "updated_at": now,  # MongoDB Date
            "metadata": payload.metadata,
        }
        
        # Insert or update (upsert)
        try:
            self.collection.replace_one(
                {"_id": user_object_id},
                document,
                upsert=True
            )
            logger.debug("Saved payload for user_id=%s", payload.user_id)
        except Exception as e:
            logger.error(f"Failed to save payload for user_id={payload.user_id}: {e}")
            raise
        
        return payload.user_id

    def get(self, user_id: str, decrypt: bool = True) -> Optional[OverallPayload]:
        """Retrieve a payload by user_id.
        
        Args:
            user_id: The user ID to retrieve
            decrypt: Whether to decrypt sensitive fields (default: True)
        
        Returns:
            OverallPayload with decrypted data, or None if not found
        """
        try:
            # Try to convert to ObjectId
            try:
                user_object_id = ObjectId(user_id)
            except Exception:
                # If not valid ObjectId, use as string
                user_object_id = user_id
            
            # Find by _id (preferred) or user_id
            document = self.collection.find_one({
                "$or": [
                    {"_id": user_object_id},
                    {"user_id": user_id}
                ]
            })
            
            if document is None:
                return None
            
            return self._document_to_payload(document, decrypt=decrypt)
        except Exception as e:
            logger.error(f"Failed to get payload for user_id={user_id}: {e}")
            return None
    
    def get_encrypted(self, user_id: str) -> Optional[OverallPayload]:
        """Retrieve a payload without decrypting sensitive fields.
        
        Use this when you need the raw encrypted data (e.g., for backup).
        """
        return self.get(user_id, decrypt=False)
    
    def get_masked(self, user_id: str) -> Optional[OverallPayload]:
        """Retrieve a payload with sensitive fields masked for display.
        
        Returns payload where sensitive data is replaced with masked values
        like "XXXX XXXX 1234" for Aadhaar.
        """
        payload = self.get(user_id, decrypt=True)
        if payload is None:
            return None
        
        if self._encryptor:
            try:
                payload.master_json = self._encryptor.get_masked_payload(
                    payload.master_json,
                    decrypt_first=False  # Already decrypted
                )
            except Exception as e:
                logger.warning(f"Failed to mask payload: {e}")
        
        return payload

    def get_master_json(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve only master_json by user_id."""
        payload = self.get(user_id)
        return payload.master_json if payload else None

    def get_ml_input_json(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve only ml_input_json by user_id."""
        payload = self.get(user_id)
        return payload.ml_input_json if payload else None

    def _deep_merge_dict(self, base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries, with update taking precedence."""
        result = base.copy()
        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge_dict(result[key], value)
            else:
                result[key] = value
        return result

    def update_status(self, user_id: str, status: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Update the status of a payload. Returns True if updated."""
        try:
            try:
                user_object_id = ObjectId(user_id)
            except Exception:
                user_object_id = user_id
            
            now = datetime.utcnow()
            update_doc = {
                "$set": {
                    "status": status,
                    "updated_at": now
                }
            }
            
            if metadata:
                # Merge with existing metadata (deep merge for nested dicts)
                # First, get existing metadata without decrypting (faster)
                try:
                    existing_doc = self.collection.find_one(
                        {"_id": user_object_id},
                        {"metadata": 1}
                    )
                    if existing_doc and existing_doc.get("metadata"):
                        existing_metadata = existing_doc["metadata"]
                        # Deep merge: combine existing and new metadata
                        merged_metadata = self._deep_merge_dict(existing_metadata, metadata)
                    else:
                        merged_metadata = metadata
                except Exception as e:
                    logger.warning(f"Failed to get existing metadata for merge: {e}, using new metadata only")
                    merged_metadata = metadata
                
                update_doc["$set"]["metadata"] = merged_metadata
            
            result = self.collection.update_one(
                {"_id": user_object_id},
                update_doc
            )
            
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to update status for user_id={user_id}: {e}")
            return False

    def delete(self, user_id: str) -> bool:
        """Delete a payload. Returns True if deleted."""
        try:
            try:
                user_object_id = ObjectId(user_id)
            except Exception:
                user_object_id = user_id
            
            result = self.collection.delete_one({"_id": user_object_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Failed to delete payload for user_id={user_id}: {e}")
            return False

    def list_all(self, status: Optional[str] = None, limit: int = 100) -> List[OverallPayload]:
        """List payloads, optionally filtered by status."""
        try:
            query = {}
            if status:
                query["status"] = status
            
            cursor = self.collection.find(query).sort("created_at", -1).limit(limit)
            return [self._document_to_payload(doc) for doc in cursor]
        except Exception as e:
            logger.error(f"Failed to list payloads: {e}")
            return []

    def list_user_ids(self) -> List[str]:
        """Return all stored user_ids."""
        try:
            cursor = self.collection.find({}, {"user_id": 1})
            return [doc.get("user_id") or str(doc.get("_id", "")) for doc in cursor]
        except Exception as e:
            logger.error(f"Failed to list user_ids: {e}")
            return []

    def count(self, status: Optional[str] = None) -> int:
        """Count payloads, optionally filtered by status."""
        try:
            query = {}
            if status:
                query["status"] = status
            return self.collection.count_documents(query)
        except Exception as e:
            logger.error(f"Failed to count payloads: {e}")
            return 0

    def _document_to_payload(self, document: Dict[str, Any], decrypt: bool = True) -> OverallPayload:
        """Convert a MongoDB document to an OverallPayload object.
        
        Args:
            document: MongoDB document to convert
            decrypt: Whether to decrypt sensitive fields (default: True)
        
        Returns:
            OverallPayload object
        """
        # Extract user_id (prefer user_id field, fallback to _id)
        user_id = document.get("user_id") or str(document.get("_id", ""))
        
        # Get master_json
        master_json = document.get("master_json", {})
        
        # Decrypt if needed
        if decrypt and self._encryptor and self.encrypt_sensitive:
            try:
                master_json = self._encryptor.decrypt_sensitive_fields(master_json)
            except Exception as e:
                logger.warning(f"Failed to decrypt sensitive fields: {e}")
        
        # Convert dates to ISO strings
        created_at = document.get("created_at")
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()
        elif created_at is None:
            created_at = None
        
        updated_at = document.get("updated_at")
        if isinstance(updated_at, datetime):
            updated_at = updated_at.isoformat()
        elif updated_at is None:
            updated_at = None
        
        return OverallPayload(
            user_id=user_id,
            master_json=master_json,
            ml_input_json=document.get("ml_input_json", {}),
            status=document.get("status", "pending"),
            created_at=created_at,
            updated_at=updated_at,
            metadata=document.get("metadata", {})
        )

    def close(self):
        """Close database connection (MongoDB handles this automatically)."""
        # MongoDB connections are managed by the client, no explicit close needed
        pass


def get_mongo_payload_store(db: Database, encrypt_sensitive: bool = True) -> MongoPayloadStore:
    """Get a singleton MongoPayloadStore instance.
    
    Args:
        db: MongoDB database instance
        encrypt_sensitive: Whether to encrypt sensitive fields (default: True)
    
    Returns:
        MongoPayloadStore instance
    """
    return MongoPayloadStore(db, encrypt_sensitive=encrypt_sensitive)

