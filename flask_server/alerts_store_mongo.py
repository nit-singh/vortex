"""MongoDB-backed alerts store for KYC system.

This module provides persistent storage for alerts that are dispatched during
the KYC orchestration process. Alerts are stored with user_id association
for polling by the web portal.

Usage:
    from flask_server.alerts_store_mongo import MongoAlertsStore
    from pymongo import MongoClient
    
    client = MongoClient("mongodb://localhost:27017/")
    db = client["kyc_app"]
    store = MongoAlertsStore(db)
    
    # Store an alert
    alert_id = store.create_alert(
        user_id="user123",
        alert_type="user",
        severity="critical",
        title="Document Verification Failed",
        message="Please upload supporting documents",
        metadata={...}
    )
    
    # Get unread alerts for a user
    alerts = store.get_unread_alerts("user123")
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)


class MongoAlertsStore:
    """MongoDB-backed store for KYC alerts.
    
    This implementation uses MongoDB for persistent storage of alerts.
    Alerts are associated with user_id for easy polling by the web portal.
    
    Collection: alerts
    Document structure:
    {
        "_id": ObjectId(...),
        "user_id": "6932eafade8ac2f8b00c1174",
        "alert_type": "user" | "ops",
        "severity": "info" | "minor" | "major" | "critical",
        "title": "Alert Title",
        "message": "Alert message/instructions",
        "channel": "in_app" | "email" | "pagerduty" | "slack" | ...,
        "audience": "user" | "compliance_ops" | ...,
        "read": false,
        "read_at": null,
        "metadata": {...},  // Additional context (alert_plan, context, etc.)
        "created_at": ISODate(...),
        "updated_at": ISODate(...)
    }
    """

    def __init__(self, db: Database):
        self.db = db
        self.collection = db.alerts
        self._init_indexes()
        logger.info("MongoAlertsStore initialized")

    def _init_indexes(self) -> None:
        """Initialize database indexes for efficient queries."""
        try:
            # Index on user_id for user-specific queries
            self.collection.create_index("user_id", name="idx_alerts_user_id")
            
            # Index on read status for unread queries
            self.collection.create_index("read", name="idx_alerts_read")
            
            # Compound index for common query: user_id + read + created_at
            self.collection.create_index(
                [("user_id", 1), ("read", 1), ("created_at", -1)],
                name="idx_alerts_user_read_created"
            )
            
            # Index on created_at for sorting
            self.collection.create_index("created_at", name="idx_alerts_created_at")
            
            logger.info("MongoAlertsStore: Indexes initialized")
        except Exception as e:
            logger.warning(f"MongoAlertsStore: Failed to create indexes: {e}")

    def create_alert(
        self,
        user_id: str,
        alert_type: str,  # "user" or "ops"
        severity: str,  # "info", "minor", "major", "critical"
        title: str,
        message: str,
        channel: str = "in_app",
        audience: str = "user",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new alert in the database.
        
        Args:
            user_id: User ID associated with the alert
            alert_type: Type of alert ("user" or "ops")
            severity: Severity level ("info", "minor", "major", "critical")
            title: Alert title
            message: Alert message/instructions
            channel: Channel used for dispatch
            audience: Target audience
            metadata: Additional metadata (alert_plan, context, etc.)
        
        Returns:
            Alert ID (ObjectId as string)
        """
        now = datetime.utcnow()
        
        document = {
            "user_id": user_id,
            "alert_type": alert_type,
            "severity": severity,
            "title": title,
            "message": message,
            "channel": channel,
            "audience": audience,
            "read": False,
            "read_at": None,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        
        try:
            result = self.collection.insert_one(document)
            alert_id = str(result.inserted_id)
            logger.info(f"Created alert {alert_id} for user_id={user_id}, type={alert_type}, severity={severity}")
            return alert_id
        except Exception as e:
            logger.error(f"Failed to create alert for user_id={user_id}: {e}")
            raise

    def get_alerts(
        self,
        user_id: str,
        read: Optional[bool] = None,
        limit: int = 100,
        sort_by_created: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get alerts for a user, optionally filtered by read status.
        
        Args:
            user_id: User ID to get alerts for
            read: Filter by read status (None = all, True = read only, False = unread only)
            limit: Maximum number of alerts to return
            sort_by_created: Sort by created_at descending (newest first)
        
        Returns:
            List of alert documents (with _id converted to string)
        """
        query = {"user_id": user_id}
        if read is not None:
            query["read"] = read
        
        try:
            cursor = self.collection.find(query)
            if sort_by_created:
                cursor = cursor.sort("created_at", -1)
            cursor = cursor.limit(limit)
            
            alerts = []
            for doc in cursor:
                alert = self._document_to_dict(doc)
                alerts.append(alert)
            
            return alerts
        except Exception as e:
            logger.error(f"Failed to get alerts for user_id={user_id}: {e}")
            return []

    def get_unread_alerts(
        self,
        user_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get unread alerts for a user.
        
        Args:
            user_id: User ID to get unread alerts for
            limit: Maximum number of alerts to return
        
        Returns:
            List of unread alert documents
        """
        return self.get_alerts(user_id, read=False, limit=limit)

    def get_read_alerts(
        self,
        user_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get read alerts for a user.
        
        Args:
            user_id: User ID to get read alerts for
            limit: Maximum number of alerts to return
        
        Returns:
            List of read alert documents
        """
        return self.get_alerts(user_id, read=True, limit=limit)

    def mark_as_read(self, alert_id: str) -> bool:
        """Mark an alert as read.
        
        Args:
            alert_id: Alert ID to mark as read
        
        Returns:
            True if updated, False if not found
        """
        try:
            alert_object_id = ObjectId(alert_id)
        except Exception:
            logger.warning(f"Invalid alert_id format: {alert_id}")
            return False
        
        try:
            result = self.collection.update_one(
                {"_id": alert_object_id, "read": False},
                {
                    "$set": {
                        "read": True,
                        "read_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    }
                }
            )
            if result.modified_count > 0:
                logger.info(f"Marked alert {alert_id} as read")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to mark alert {alert_id} as read: {e}")
            return False

    def mark_all_as_read(self, user_id: str) -> int:
        """Mark all unread alerts for a user as read.
        
        Args:
            user_id: User ID to mark all alerts as read for
        
        Returns:
            Number of alerts marked as read
        """
        try:
            result = self.collection.update_many(
                {"user_id": user_id, "read": False},
                {
                    "$set": {
                        "read": True,
                        "read_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    }
                }
            )
            count = result.modified_count
            if count > 0:
                logger.info(f"Marked {count} alerts as read for user_id={user_id}")
            return count
        except Exception as e:
            logger.error(f"Failed to mark all alerts as read for user_id={user_id}: {e}")
            return 0

    def get_unread_count(self, user_id: str) -> int:
        """Get count of unread alerts for a user.
        
        Args:
            user_id: User ID to count unread alerts for
        
        Returns:
            Number of unread alerts
        """
        try:
            return self.collection.count_documents({"user_id": user_id, "read": False})
        except Exception as e:
            logger.error(f"Failed to count unread alerts for user_id={user_id}: {e}")
            return 0

    def delete_alert(self, alert_id: str) -> bool:
        """Delete an alert.
        
        Args:
            alert_id: Alert ID to delete
        
        Returns:
            True if deleted, False if not found
        """
        try:
            alert_object_id = ObjectId(alert_id)
        except Exception:
            logger.warning(f"Invalid alert_id format: {alert_id}")
            return False
        
        try:
            result = self.collection.delete_one({"_id": alert_object_id})
            if result.deleted_count > 0:
                logger.info(f"Deleted alert {alert_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete alert {alert_id}: {e}")
            return False

    def _document_to_dict(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Convert MongoDB document to dictionary with _id as string.
        
        Args:
            document: MongoDB document
        
        Returns:
            Dictionary with _id converted to string and dates to ISO strings
        """
        alert = dict(document)
        
        # Convert _id to string
        if "_id" in alert:
            alert["_id"] = str(alert["_id"])
        
        # Convert dates to ISO strings
        for date_field in ["created_at", "updated_at", "read_at"]:
            if date_field in alert and isinstance(alert[date_field], datetime):
                alert[date_field] = alert[date_field].isoformat()
        
        return alert


def get_alerts_store(db: Database) -> MongoAlertsStore:
    """Get a MongoAlertsStore instance.
    
    Args:
        db: MongoDB database instance
    
    Returns:
        MongoAlertsStore instance
    """
    return MongoAlertsStore(db)

