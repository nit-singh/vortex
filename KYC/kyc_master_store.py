"""Master JSON storage module.

This module provides functions to store and retrieve master JSON verification results.
"""

import uuid
from typing import Dict, Any, Optional
from datetime import datetime


# In-memory storage (for development/testing)
# In production, this should use a proper database
_master_json_store: Dict[str, Dict[str, Any]] = {}


def register_master_json(master_json: Dict[str, Any], temp_id: Optional[str] = None) -> str:
    """
    Register/store a master JSON and return its ID.
    
    Args:
        master_json: The master verification JSON to store
        temp_id: Optional temporary ID (ignored, generates new UUID)
        
    Returns:
        Unique ID for the stored master JSON
    """
    master_json_id = str(uuid.uuid4())
    
    # Store with metadata
    _master_json_store[master_json_id] = {
        "master_json": master_json,
        "stored_at": datetime.now().isoformat(),
        "id": master_json_id
    }
    
    return master_json_id


def get_master_json(master_json_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a master JSON by ID.
    
    Args:
        master_json_id: The ID of the master JSON to retrieve
        
    Returns:
        The master JSON if found, None otherwise
    """
    stored = _master_json_store.get(master_json_id)
    if stored:
        return stored.get("master_json")
    return None


def list_master_jsons(limit: int = 100) -> list:
    """
    List all stored master JSON IDs.
    
    Args:
        limit: Maximum number of IDs to return
        
    Returns:
        List of master JSON IDs
    """
    return list(_master_json_store.keys())[:limit]

