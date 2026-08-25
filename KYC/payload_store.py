"""SQLite-backed payload store for KYC orchestration.

This module provides persistent storage for overall KYC payloads (master_json + ml_input_json)
keyed by user_id. The SQLite backend can be swapped for MongoDB during deployment by
implementing the same interface.

SECURITY: Sensitive fields (Aadhaar, PAN, DOB, etc.) are automatically encrypted before
storage and decrypted on retrieval. This prevents exposure of PII in the database.

Usage:
    from payload_store import PayloadStore, OverallPayload

    store = PayloadStore()  # Uses default SQLite DB with encryption
    payload = OverallPayload(
        user_id="user123",
        master_json={"verification_status": {...}},
        ml_input_json={"age": 30, "gross_income": 500000, ...}
    )
    store.save(payload)  # Sensitive fields encrypted automatically
    retrieved = store.get("user123")  # Decrypted on retrieval
    
    # Get masked version for display (without decrypting sensitive data)
    masked = store.get_masked("user123")
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

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
    encrypt_payload = lambda x: x
    decrypt_payload = lambda x: x
    mask_payload = lambda x: x

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "kyc_payloads.db")


@dataclass
class OverallPayload:
    """Data model for storing KYC payloads.
    
    Attributes:
        user_id: Unique identifier for the user/application
        master_json: Full KYC verification data (goes to KYCV MCP server)
        ml_input_json: Simplified features for ML scoring (goes to RiskScore MCP server)
        status: Processing status (pending, processing, completed, failed)
        created_at: Timestamp when payload was created
        updated_at: Timestamp when payload was last updated
        metadata: Optional additional metadata
    """
    user_id: str
    master_json: Dict[str, Any]
    ml_input_json: Dict[str, Any]
    status: str = "pending"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        now = datetime.utcnow().isoformat()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "master_json": self.master_json,
            "ml_input_json": self.ml_input_json,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OverallPayload":
        return cls(
            user_id=data["user_id"],
            master_json=data["master_json"],
            ml_input_json=data["ml_input_json"],
            status=data.get("status", "pending"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            metadata=data.get("metadata", {}),
        )


class PayloadStore:
    """Thread-safe SQLite store for KYC payloads with automatic encryption.
    
    This implementation uses SQLite for development/testing. For production
    deployment with MongoDB, implement a MongoPayloadStore with the same interface.
    
    SECURITY: Sensitive fields in master_json are automatically encrypted before
    storage and decrypted on retrieval. Set encrypt_sensitive=False to disable.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        encrypt_sensitive: bool = True,
    ):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.encrypt_sensitive = encrypt_sensitive and ENCRYPTION_ENABLED
        self._local = threading.local()
        self._encryptor = get_encryptor() if self.encrypt_sensitive and get_encryptor else None
        self._init_db()
        
        if self.encrypt_sensitive:
            logger.info("PayloadStore: Encryption ENABLED for sensitive fields")
        else:
            logger.warning("PayloadStore: Encryption DISABLED - sensitive data stored in plaintext")

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payloads (
                user_id TEXT PRIMARY KEY,
                master_json TEXT NOT NULL,
                ml_input_json TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_payloads_status ON payloads(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_payloads_created_at ON payloads(created_at)
        """)
        conn.commit()
        logger.info("PayloadStore initialized with database at %s", self.db_path)

    def save(self, payload: OverallPayload) -> str:
        """Save or update a payload. Returns user_id.
        
        Sensitive fields in master_json are automatically encrypted before storage.
        """
        conn = self._get_conn()
        now = datetime.utcnow().isoformat()
        payload.updated_at = now
        
        # Encrypt sensitive fields in master_json before storage
        master_json_to_store = payload.master_json
        if self._encryptor and self.encrypt_sensitive:
            master_json_to_store = self._encryptor.encrypt_sensitive_fields(payload.master_json)
            logger.debug("Encrypted sensitive fields for user_id=%s", payload.user_id)
        
        conn.execute("""
            INSERT INTO payloads (user_id, master_json, ml_input_json, status, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                master_json = excluded.master_json,
                ml_input_json = excluded.ml_input_json,
                status = excluded.status,
                updated_at = excluded.updated_at,
                metadata = excluded.metadata
        """, (
            payload.user_id,
            json.dumps(master_json_to_store),
            json.dumps(payload.ml_input_json),
            payload.status,
            payload.created_at,
            payload.updated_at,
            json.dumps(payload.metadata),
        ))
        conn.commit()
        logger.debug("Saved payload for user_id=%s", payload.user_id)
        return payload.user_id

    def get(self, user_id: str, decrypt: bool = True) -> Optional[OverallPayload]:
        """Retrieve a payload by user_id.
        
        Args:
            user_id: The user ID to retrieve
            decrypt: Whether to decrypt sensitive fields (default: True)
        
        Returns:
            OverallPayload with decrypted data, or None if not found
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM payloads WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_payload(row, decrypt=decrypt)
    
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
            payload.master_json = self._encryptor.get_masked_payload(
                payload.master_json,
                decrypt_first=False  # Already decrypted
            )
        return payload

    def get_master_json(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve only master_json by user_id."""
        payload = self.get(user_id)
        return payload.master_json if payload else None

    def get_ml_input_json(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve only ml_input_json by user_id."""
        payload = self.get(user_id)
        return payload.ml_input_json if payload else None

    def update_status(self, user_id: str, status: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Update the status of a payload. Returns True if updated."""
        conn = self._get_conn()
        now = datetime.utcnow().isoformat()
        
        if metadata:
            # Merge with existing metadata
            existing = self.get(user_id)
            if existing:
                merged_metadata = {**existing.metadata, **metadata}
            else:
                merged_metadata = metadata
            
            cursor = conn.execute("""
                UPDATE payloads SET status = ?, updated_at = ?, metadata = ?
                WHERE user_id = ?
            """, (status, now, json.dumps(merged_metadata), user_id))
        else:
            cursor = conn.execute("""
                UPDATE payloads SET status = ?, updated_at = ?
                WHERE user_id = ?
            """, (status, now, user_id))
        
        conn.commit()
        return cursor.rowcount > 0

    def delete(self, user_id: str) -> bool:
        """Delete a payload. Returns True if deleted."""
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM payloads WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0

    def list_all(self, status: Optional[str] = None, limit: int = 100) -> List[OverallPayload]:
        """List payloads, optionally filtered by status."""
        conn = self._get_conn()
        if status:
            cursor = conn.execute(
                "SELECT * FROM payloads WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM payloads ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
        return [self._row_to_payload(row) for row in cursor.fetchall()]

    def list_user_ids(self) -> List[str]:
        """Return all stored user_ids."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT user_id FROM payloads ORDER BY created_at DESC")
        return [row["user_id"] for row in cursor.fetchall()]

    def count(self, status: Optional[str] = None) -> int:
        """Count payloads, optionally filtered by status."""
        conn = self._get_conn()
        if status:
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM payloads WHERE status = ?",
                (status,)
            )
        else:
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM payloads")
        return cursor.fetchone()["cnt"]

    def _row_to_payload(self, row: sqlite3.Row, decrypt: bool = True) -> OverallPayload:
        """Convert a database row to an OverallPayload object.
        
        Args:
            row: SQLite row to convert
            decrypt: Whether to decrypt sensitive fields
        """
        master_json = json.loads(row["master_json"])
        
        # Decrypt sensitive fields if enabled
        if decrypt and self._encryptor and self.encrypt_sensitive:
            master_json = self._encryptor.decrypt_sensitive_fields(master_json)
        
        return OverallPayload(
            user_id=row["user_id"],
            master_json=master_json,
            ml_input_json=json.loads(row["ml_input_json"]),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def close(self) -> None:
        """Close database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# Global singleton instance for convenience
_default_store: Optional[PayloadStore] = None


def get_payload_store(db_path: Optional[str] = None) -> PayloadStore:
    """Get or create the default PayloadStore instance."""
    global _default_store
    if _default_store is None:
        _default_store = PayloadStore(db_path)
    return _default_store


def save_overall_payload(
    user_id: str,
    master_json: Dict[str, Any],
    ml_input_json: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Convenience function to save a payload."""
    store = get_payload_store()
    payload = OverallPayload(
        user_id=user_id,
        master_json=master_json,
        ml_input_json=ml_input_json,
        metadata=metadata or {},
    )
    return store.save(payload)


def get_overall_payload(user_id: str) -> Optional[OverallPayload]:
    """Convenience function to retrieve a payload."""
    store = get_payload_store()
    return store.get(user_id)


def get_master_json_for_user(user_id: str) -> Optional[Dict[str, Any]]:
    """Convenience function to get master_json by user_id."""
    store = get_payload_store()
    return store.get_master_json(user_id)


def get_ml_input_json_for_user(user_id: str) -> Optional[Dict[str, Any]]:
    """Convenience function to get ml_input_json by user_id."""
    store = get_payload_store()
    return store.get_ml_input_json(user_id)
