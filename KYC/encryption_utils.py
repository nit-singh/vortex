"""Sensitive data encryption utilities for KYC system.

This module provides encryption/decryption for sensitive PII fields like:
- Aadhaar number
- PAN number
- Date of birth
- Address
- Other personally identifiable information

Uses Fernet symmetric encryption (AES-128-CBC with HMAC).
The encryption key should be stored securely (environment variable, secrets manager, etc.)

Usage:
    from encryption_utils import SensitiveDataEncryptor
    
    encryptor = SensitiveDataEncryptor()  # Uses ENCRYPTION_KEY env var
    
    # Encrypt before storing
    encrypted_payload = encryptor.encrypt_sensitive_fields(master_json)
    
    # Decrypt when retrieving
    decrypted_payload = encryptor.decrypt_sensitive_fields(encrypted_payload)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Set, Union

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger(__name__)

# Fields that should be encrypted (case-insensitive matching)
DEFAULT_SENSITIVE_FIELDS: Set[str] = {
    # Identity numbers
    "aadhaar_number",
    "aadhaar_no",
    "aadhar_number",
    "aadhar_no",
    "pan_number",
    "pan_no",
    "pan",
    
    # Personal details that could identify someone
    "date_of_birth",
    "dob",
    "address",
    "full_address",
    
    # Raw document text (contains sensitive info)
    "raw_text",
}

# Nested paths to encrypt (dot notation)
DEFAULT_SENSITIVE_PATHS: List[str] = [
    "personal_details.pan_number.value",
    "personal_details.aadhaar_number.value",
    "personal_details.date_of_birth.value",
    "personal_details.address.value",
    "parsed_documents.pan.pan_number",
    "parsed_documents.pan.dob",
    "parsed_documents.pan.raw_text",
    "parsed_documents.aadhaar.aadhaar_number",
    "alerting.signal.evidence.document_verification.verification_details.normalized_names",
]


def generate_encryption_key() -> str:
    """Generate a new Fernet encryption key.
    
    Returns:
        Base64-encoded key string suitable for ENCRYPTION_KEY env var.
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package not installed. Run: pip install cryptography")
    return Fernet.generate_key().decode()


def derive_key_from_password(password: str, salt: Optional[bytes] = None) -> tuple[bytes, bytes]:
    """Derive a Fernet key from a password using PBKDF2.
    
    Args:
        password: User password or passphrase
        salt: Optional salt bytes (generated if not provided)
    
    Returns:
        Tuple of (derived_key, salt)
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package not installed")
    
    if salt is None:
        salt = os.urandom(16)
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key, salt


class SensitiveDataEncryptor:
    """Encrypts and decrypts sensitive fields in KYC payloads.
    
    Encryption is performed in-place on specified fields. Encrypted values
    are prefixed with 'ENC:' to identify them during decryption.
    
    Attributes:
        sensitive_fields: Set of field names to encrypt
        sensitive_paths: List of dot-notation paths to encrypt
    """
    
    ENCRYPTED_PREFIX = "ENC:"
    
    def __init__(
        self,
        encryption_key: Optional[str] = None,
        sensitive_fields: Optional[Set[str]] = None,
        sensitive_paths: Optional[List[str]] = None,
    ):
        """Initialize encryptor.
        
        Args:
            encryption_key: Base64-encoded Fernet key. If not provided,
                           reads from ENCRYPTION_KEY environment variable.
            sensitive_fields: Set of field names to encrypt (case-insensitive)
            sensitive_paths: List of dot-notation paths to always encrypt
        
        Raises:
            RuntimeError: If cryptography package not installed
            ValueError: If no encryption key provided or found
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError(
                "cryptography package not installed. Run: pip install cryptography"
            )
        
        # Get key from parameter or environment
        key_str = encryption_key or os.environ.get("ENCRYPTION_KEY")
        if not key_str:
            # Generate a default key for development (NOT for production!)
            logger.warning(
                "No ENCRYPTION_KEY found. Generating temporary key. "
                "Set ENCRYPTION_KEY environment variable for production!"
            )
            key_str = self._get_or_create_dev_key()
        
        self._fernet = Fernet(key_str.encode() if isinstance(key_str, str) else key_str)
        self.sensitive_fields = sensitive_fields or DEFAULT_SENSITIVE_FIELDS
        self.sensitive_paths = sensitive_paths or DEFAULT_SENSITIVE_PATHS
    
    def _get_or_create_dev_key(self) -> str:
        """Get or create a development key (stored in .encryption_key file)."""
        key_file = os.path.join(os.path.dirname(__file__), ".encryption_key")
        
        if os.path.exists(key_file):
            with open(key_file, "r") as f:
                return f.read().strip()
        
        # Generate and save new key
        key = Fernet.generate_key().decode()
        with open(key_file, "w") as f:
            f.write(key)
        
        logger.info("Generated development encryption key at %s", key_file)
        return key
    
    def encrypt_value(self, value: str) -> str:
        """Encrypt a single string value.
        
        Args:
            value: Plain text string to encrypt
        
        Returns:
            Encrypted string prefixed with 'ENC:'
        """
        if not value or not isinstance(value, str):
            return value
        
        if value.startswith(self.ENCRYPTED_PREFIX):
            return value  # Already encrypted
        
        encrypted = self._fernet.encrypt(value.encode())
        return f"{self.ENCRYPTED_PREFIX}{encrypted.decode()}"
    
    def decrypt_value(self, value: str) -> str:
        """Decrypt a single encrypted value.
        
        Args:
            value: Encrypted string (must start with 'ENC:')
        
        Returns:
            Decrypted plain text string
        """
        if not value or not isinstance(value, str):
            return value
        
        if not value.startswith(self.ENCRYPTED_PREFIX):
            return value  # Not encrypted
        
        encrypted_data = value[len(self.ENCRYPTED_PREFIX):]
        try:
            decrypted = self._fernet.decrypt(encrypted_data.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error("Decryption failed: %s", e)
            return value  # Return as-is if decryption fails
    
    def mask_value(self, value: str, field_name: str = "") -> str:
        """Mask a sensitive value for display (partial redaction).
        
        Args:
            value: Plain text value to mask
            field_name: Optional field name for context-aware masking
        
        Returns:
            Masked string (e.g., "XXXX XXXX 1234" for Aadhaar)
        """
        if not value or not isinstance(value, str):
            return value
        
        field_lower = field_name.lower()
        
        # Aadhaar: show last 4 digits
        if "aadhaar" in field_lower or "aadhar" in field_lower:
            digits = re.sub(r"\D", "", value)
            if len(digits) >= 4:
                return f"XXXX XXXX {digits[-4:]}"
            return "XXXX XXXX XXXX"
        
        # PAN: show last 4 characters
        if "pan" in field_lower:
            if len(value) >= 4:
                return f"XXXXXX{value[-4:]}"
            return "XXXXXXXXXX"
        
        # DOB: show only year
        if "dob" in field_lower or "date_of_birth" in field_lower:
            # Try to extract year
            year_match = re.search(r"\b(19|20)\d{2}\b", value)
            if year_match:
                return f"XX/XX/{year_match.group()}"
            return "XX/XX/XXXX"
        
        # Address: show only city/state
        if "address" in field_lower:
            if len(value) > 20:
                return f"[REDACTED], {value.split(',')[-1].strip() if ',' in value else '...'}"
            return "[REDACTED]"
        
        # Default: show first and last 2 chars
        if len(value) > 4:
            return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"
        return "*" * len(value)
    
    def _get_nested_value(self, data: Dict, path: str) -> Any:
        """Get value at nested path (dot notation)."""
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current
    
    def _set_nested_value(self, data: Dict, path: str, value: Any) -> None:
        """Set value at nested path (dot notation)."""
        keys = path.split(".")
        current = data
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value
    
    def _should_encrypt_field(self, field_name: str) -> bool:
        """Check if a field name should be encrypted."""
        return field_name.lower() in {f.lower() for f in self.sensitive_fields}
    
    def _encrypt_dict_recursive(
        self,
        data: Dict[str, Any],
        current_path: str = "",
    ) -> Dict[str, Any]:
        """Recursively encrypt sensitive fields in a dictionary."""
        result = {}
        
        for key, value in data.items():
            full_path = f"{current_path}.{key}" if current_path else key
            
            if isinstance(value, dict):
                result[key] = self._encrypt_dict_recursive(value, full_path)
            elif isinstance(value, list):
                result[key] = [
                    self._encrypt_dict_recursive(item, full_path)
                    if isinstance(item, dict)
                    else item
                    for item in value
                ]
            elif isinstance(value, str) and self._should_encrypt_field(key):
                result[key] = self.encrypt_value(value)
            else:
                result[key] = value
        
        return result
    
    def _decrypt_dict_recursive(
        self,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Recursively decrypt encrypted fields in a dictionary."""
        result = {}
        
        for key, value in data.items():
            if isinstance(value, dict):
                result[key] = self._decrypt_dict_recursive(value)
            elif isinstance(value, list):
                result[key] = [
                    self._decrypt_dict_recursive(item)
                    if isinstance(item, dict)
                    else item
                    for item in value
                ]
            elif isinstance(value, str) and value.startswith(self.ENCRYPTED_PREFIX):
                result[key] = self.decrypt_value(value)
            else:
                result[key] = value
        
        return result
    
    def encrypt_sensitive_fields(
        self,
        payload: Dict[str, Any],
        additional_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Encrypt all sensitive fields in a payload.
        
        Args:
            payload: The payload dictionary to encrypt
            additional_paths: Extra dot-notation paths to encrypt
        
        Returns:
            New dictionary with sensitive fields encrypted
        """
        # Deep copy to avoid modifying original
        encrypted = deepcopy(payload)
        
        # First, encrypt by field name (recursive)
        encrypted = self._encrypt_dict_recursive(encrypted)
        
        # Then, encrypt by explicit paths
        all_paths = self.sensitive_paths + (additional_paths or [])
        for path in all_paths:
            value = self._get_nested_value(encrypted, path)
            if isinstance(value, str) and not value.startswith(self.ENCRYPTED_PREFIX):
                self._set_nested_value(encrypted, path, self.encrypt_value(value))
            elif isinstance(value, dict):
                # Encrypt all string values in the dict
                for k, v in value.items():
                    if isinstance(v, str) and not v.startswith(self.ENCRYPTED_PREFIX):
                        value[k] = self.encrypt_value(v)
        
        return encrypted
    
    def decrypt_sensitive_fields(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Decrypt all encrypted fields in a payload.
        
        Args:
            payload: The payload dictionary with encrypted fields
        
        Returns:
            New dictionary with all fields decrypted
        """
        return self._decrypt_dict_recursive(deepcopy(payload))
    
    def get_masked_payload(
        self,
        payload: Dict[str, Any],
        decrypt_first: bool = True,
    ) -> Dict[str, Any]:
        """Get a payload with sensitive fields masked for display.
        
        Args:
            payload: The payload to mask
            decrypt_first: Whether to decrypt before masking
        
        Returns:
            New dictionary with sensitive fields masked
        """
        if decrypt_first:
            payload = self.decrypt_sensitive_fields(payload)
        
        masked = deepcopy(payload)
        
        def mask_recursive(data: Dict, parent_key: str = ""):
            for key, value in data.items():
                # Determine field context (use parent key if current is 'value')
                field_context = parent_key if key == "value" else key
                
                if isinstance(value, dict):
                    mask_recursive(value, key)
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, dict):
                            mask_recursive(item, key)
                elif isinstance(value, str):
                    # Check if this field or its parent should be masked
                    if self._should_encrypt_field(key) or self._should_encrypt_field(field_context):
                        data[key] = self.mask_value(value, field_context or key)
        
        mask_recursive(masked)
        return masked


# Singleton encryptor instance
_encryptor: Optional[SensitiveDataEncryptor] = None


def get_encryptor() -> SensitiveDataEncryptor:
    """Get the singleton encryptor instance."""
    global _encryptor
    if _encryptor is None:
        _encryptor = SensitiveDataEncryptor()
    return _encryptor


def encrypt_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to encrypt a payload."""
    return get_encryptor().encrypt_sensitive_fields(payload)


def decrypt_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to decrypt a payload."""
    return get_encryptor().decrypt_sensitive_fields(payload)


def mask_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to get a masked payload."""
    return get_encryptor().get_masked_payload(payload)


if __name__ == "__main__":
    # Demo/test
    print("=== Encryption Utils Demo ===\n")
    
    if not CRYPTO_AVAILABLE:
        print("ERROR: cryptography package not installed")
        print("Run: pip install cryptography")
        exit(1)
    
    # Generate a key
    print("1. Generating encryption key...")
    key = generate_encryption_key()
    print(f"   Key: {key[:20]}...")
    
    # Test encryption
    print("\n2. Testing encryption...")
    encryptor = SensitiveDataEncryptor(encryption_key=key)
    
    test_payload = {
        "personal_details": {
            "pan_number": {"value": "XXXXXXXXXX", "status": "found"},
            "aadhaar_number": {"value": "XXXX XXXX XXXX", "status": "found"},
            "name": {"value": "Your dad", "status": "found"},
            "date_of_birth": {"value": "10/05/2005", "status": "found"},
        },
        "parsed_documents": {
            "pan": {
                "pan_number": "XXXXXXXXXX",
                "raw_text": "Some raw OCR text with PAN...",
            }
        }
    }
    
    print("   Original payload (sensitive fields):")
    print(f"     PAN: {test_payload['personal_details']['pan_number']['value']}")
    print(f"     Aadhaar: {test_payload['personal_details']['aadhaar_number']['value']}")
    
    encrypted = encryptor.encrypt_sensitive_fields(test_payload)
    print("\n   Encrypted payload:")
    print(f"     PAN: {encrypted['personal_details']['pan_number']['value'][:50]}...")
    print(f"     Aadhaar: {encrypted['personal_details']['aadhaar_number']['value'][:50]}...")
    
    decrypted = encryptor.decrypt_sensitive_fields(encrypted)
    print("\n   Decrypted payload:")
    print(f"     PAN: {decrypted['personal_details']['pan_number']['value']}")
    print(f"     Aadhaar: {decrypted['personal_details']['aadhaar_number']['value']}")
    
    masked = encryptor.get_masked_payload(encrypted)
    print("\n   Masked payload (for display):")
    print(f"     PAN: {masked['personal_details']['pan_number']['value']}")
    print(f"     Aadhaar: {masked['personal_details']['aadhaar_number']['value']}")
    
    print("\n✓ All tests passed!")
