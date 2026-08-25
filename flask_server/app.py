"""Flask application for KYC system."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from datetime import datetime, timedelta
import base64
import json
import requests
import logging
import pandas as pd
import glob
import bcrypt

# Cloudinary import
try:
    import cloudinary
    import cloudinary.uploader
    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False
    print("Warning: cloudinary not available. Document uploads to Cloudinary will be skipped.")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Add parent directory to path FIRST so flask_server can be imported
parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

# Add KYC directory to path for encryption utils
kyc_dir = Path(__file__).resolve().parent.parent / "KYC"
if str(kyc_dir) not in sys.path:
    sys.path.insert(0, str(kyc_dir))

try:
    from encryption_utils import SensitiveDataEncryptor
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    print("Warning: encryption_utils not available. Documents will not be encrypted.")

# Import payload storage (MongoDB version)
PAYLOAD_STORAGE_AVAILABLE = False
MongoPayloadStore = None
OverallPayload = None

try:
    from flask_server.payload_store_mongo import MongoPayloadStore as _MongoPayloadStore
    from payload_store import OverallPayload as _OverallPayload
    MongoPayloadStore = _MongoPayloadStore
    OverallPayload = _OverallPayload
    PAYLOAD_STORAGE_AVAILABLE = True
except ImportError as e:
    PAYLOAD_STORAGE_AVAILABLE = False
    print(f"Warning: MongoDB payload_store not available: {e}")
except Exception as e:
    PAYLOAD_STORAGE_AVAILABLE = False
    print(f"Warning: MongoDB payload_store import failed: {e}")

# Import verification module
VERIFICATION_AVAILABLE = False
verify_questionnaire_submission = None
convert_base64_to_image = None

try:
    # Try relative import first (when running as module)
    try:
        from .verification import (
            verify_questionnaire_submission as _verify_questionnaire_submission,
            convert_base64_to_image as _convert_base64_to_image,
            VERIFICATION_AVAILABLE as _VERIFICATION_AVAILABLE_MODULE
        )
    except (ImportError, ValueError):
        # Fallback to absolute import (when running as script)
        from flask_server.verification import (
            verify_questionnaire_submission as _verify_questionnaire_submission,
            convert_base64_to_image as _convert_base64_to_image,
            VERIFICATION_AVAILABLE as _VERIFICATION_AVAILABLE_MODULE
        )
    
    verify_questionnaire_submission = _verify_questionnaire_submission
    convert_base64_to_image = _convert_base64_to_image
    VERIFICATION_AVAILABLE = _VERIFICATION_AVAILABLE_MODULE
    if VERIFICATION_AVAILABLE:
        print("✅ Verification module loaded successfully and ready to use")
    else:
        print("⚠️  Verification module imported but VERIFICATION_AVAILABLE is False")
except ImportError as e:
    VERIFICATION_AVAILABLE = False
    print(f"⚠️  Warning: Verification module not available: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    VERIFICATION_AVAILABLE = False
    print(f"⚠️  Warning: Verification module import failed: {e}")
    import traceback
    traceback.print_exc()

# Load environment variables from keys.env file
env_path = Path(__file__).resolve().parent.parent / "keys.env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# Import config after loading .env
# Add parent directory to path so we can import config
parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from flask_server.config import config

# Create Flask app
app = Flask(__name__)
config_name = os.getenv("FLASK_ENV", "default")
app.config.from_object(config[config_name])

# Enable CORS for dashboard
CORS(app, origins="*")

# MongoDB connection
try:
    mongodb_client = MongoClient(app.config["MONGODB_URI"])
    db = mongodb_client[app.config["MONGODB_DB_NAME"]]
    users_collection = db.users
    
    # Create unique index on email
    users_collection.create_index("email", unique=True)
    print(f"✓ Connected to MongoDB: {app.config['MONGODB_DB_NAME']}")
except Exception as e:
    print(f"✗ MongoDB connection failed: {e}")
    mongodb_client = None
    db = None
    users_collection = None

# Initialize encryptor if available
encryptor = None
if ENCRYPTION_AVAILABLE:
    try:
        encryptor = SensitiveDataEncryptor()
        print("✓ Encryption initialized")
    except Exception as e:
        print(f"⚠ Encryption initialization failed: {e}")
        encryptor = None

# Initialize Cloudinary if available
if CLOUDINARY_AVAILABLE:
    try:
        cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "")
        api_key = os.getenv("CLOUDINARY_API_KEY", "")
        api_secret = os.getenv("CLOUDINARY_API_SECRET", "")
        
        # Check if credentials are placeholders
        if (cloud_name == "your_cloud_name" or 
            api_key == "your_api_key" or 
            api_secret == "your_api_secret" or
            not cloud_name or not api_key or not api_secret):
            logger.warning("⚠️  Cloudinary credentials not configured properly in keys.env")
            logger.warning("   Please set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET")
            logger.warning("   Get your credentials from: https://console.cloudinary.com/settings/api")
            CLOUDINARY_AVAILABLE = False
        else:
            cloudinary.config(
                cloud_name=cloud_name,
                api_key=api_key,
                api_secret=api_secret,
                secure=True
            )
            logger.info("✓ Cloudinary configured: %s", cloud_name)
    except Exception as e:
        logger.error("⚠️  Cloudinary configuration failed: %s", e)
        CLOUDINARY_AVAILABLE = False
else:
    logger.warning("⚠️  Cloudinary not available. Document uploads will be skipped.")


def upload_document_to_cloudinary(base64_content: str, user_id: str, doc_type: str, filename: str, mime_type: str = "application/pdf") -> str:
    """
    Upload a document to Cloudinary.
    
    Args:
        base64_content: Base64 encoded document content
        user_id: User ID for folder organization
        doc_type: Type of document (aadhaar, pan, itr)
        filename: Original filename
        mime_type: MIME type of the document
    
    Returns:
        Cloudinary secure URL or None if upload fails
    """
    if not CLOUDINARY_AVAILABLE:
        return None
    
    try:
        # Determine file format from mime_type
        file_format = "pdf"
        if "image" in mime_type.lower():
            if "jpeg" in mime_type.lower() or "jpg" in mime_type.lower():
                file_format = "jpg"
            elif "png" in mime_type.lower():
                file_format = "png"
            elif "webp" in mime_type.lower():
                file_format = "webp"
        elif "pdf" in mime_type.lower():
            file_format = "pdf"
        
        # Create public_id with folder structure
        public_id = f"kyc-documents/{user_id}/{doc_type}"
        
        # Upload to Cloudinary
        # Use data URI format for base64 upload
        data_uri = f"data:{mime_type};base64,{base64_content}"
        
        result = cloudinary.uploader.upload(
            data_uri,
            public_id=public_id,
            resource_type="auto",  # Auto-detect image or raw
            folder=f"kyc-documents/{user_id}",
            overwrite=True,
            invalidate=True
        )
        
        secure_url = result.get("secure_url")
        return secure_url
        
    except Exception as e:
        logger.error(f"❌ Failed to upload {doc_type} to Cloudinary: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

# Initialize MongoDB payload store if available
payload_store = None
if PAYLOAD_STORAGE_AVAILABLE and db is not None:
    try:
        payload_store = MongoPayloadStore(db, encrypt_sensitive=True)
        print("✓ MongoDB payload storage initialized")
    except Exception as e:
        print(f"⚠ MongoDB payload storage initialization failed: {e}")
        payload_store = None
elif PAYLOAD_STORAGE_AVAILABLE and db is None:
    print("⚠ MongoDB payload storage not initialized: Database connection not available")

# Initialize MongoDB alerts store if available
alerts_store = None
if db is not None:
    try:
        from alerts_store_mongo import MongoAlertsStore
        alerts_store = MongoAlertsStore(db)
        print("✓ MongoDB alerts storage initialized")
    except ImportError as e:
        print(f"⚠ Alerts store not available: {e}")
        alerts_store = None
    except Exception as e:
        print(f"⚠ MongoDB alerts storage initialization failed: {e}")
        alerts_store = None
else:
    print("⚠ MongoDB alerts storage not initialized: Database connection not available")


def normalize_user_id(user_id: str) -> str:
    """
    Normalize user_id to a consistent format for payload storage.
    
    Now only accepts MongoDB ObjectId format. Returns as-is if valid.
    Legacy formats (email-{email}, temp-{base64}) are no longer supported
    but kept for backward compatibility with existing data.
    
    Args:
        user_id: MongoDB ObjectId string (24 hex characters)
    
    Returns:
        user_id as-is if valid MongoDB ObjectId, otherwise raises ValueError
    """
    import re
    
    # Validate MongoDB ObjectId format (24 hex characters)
    if re.match(r'^[0-9a-fA-F]{24}$', user_id):
        return user_id
    
    # Legacy format handling (for backward compatibility only)
    # Log warning but still process for existing data
    if user_id.startswith("email-"):
        email = user_id.replace("email-", "")
        print(f"⚠️  Warning: Legacy email- format detected: {user_id}. Please use MongoDB ObjectId.")
        # Try to find user by email and return their ObjectId
        try:
            if mongodb_client is not None and users_collection is not None:
                user = users_collection.find_one({"email": email.lower()})
                if user:
                    return str(user["_id"])
        except Exception:
            pass
        # If can't find user, return email (for backward compatibility)
        return email
    elif user_id.startswith("temp-"):
        try:
            import base64 as b64
            encoded_email = user_id.replace("temp-", "")
            try:
                email = b64.b64decode(encoded_email + "==").decode('utf-8')
            except:
                email = b64.b64decode(encoded_email).decode('utf-8')
            print(f"⚠️  Warning: Legacy temp- format detected: {user_id}. Please use MongoDB ObjectId.")
            # Try to find user by email and return their ObjectId
            try:
                if mongodb_client is not None and users_collection is not None:
                    user = users_collection.find_one({"email": email.lower()})
                    if user:
                        return str(user["_id"])
            except Exception:
                pass
            return email
        except Exception:
            pass
    
    # Invalid format - raise error
    raise ValueError(f"Invalid userId format: {user_id}. Must be a valid MongoDB ObjectId (24 hex characters).")


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "KYC Flask API",
        "mongodb_connected": mongodb_client is not None
    }), 200


@app.route("/api/v1/auth/signup", methods=["POST"])
def signup():
    """
    Create a new user account.
    
    Expects JSON body:
    {
        "email": "user@example.com",
        "password": "password123",
        "name": "John Doe",
        "userType": "consumer" or "company"
    }
    """
    try:
        if mongodb_client is None or users_collection is None:
            return jsonify({
                "error": "Database unavailable",
                "message": "MongoDB connection not established"
            }), 503
        
        data = request.get_json()
        
        # Validate required fields
        required_fields = ["email", "password", "name", "userType"]
        missing_fields = [field for field in required_fields if not data.get(field)]
        
        if missing_fields:
            return jsonify({
                "error": "Missing required fields",
                "message": f"Required fields: {', '.join(missing_fields)}"
            }), 400
        
        email = data["email"].strip().lower()
        password = data["password"]
        name = data["name"].strip()
        user_type = data["userType"].strip().lower()
        
        # Validate user type
        if user_type not in ["consumer", "company"]:
            return jsonify({
                "error": "Invalid user type",
                "message": "userType must be 'consumer' or 'company'"
            }), 400
        
        # Hash password using bcrypt
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password_bytes, salt)
        hashed_password_str = hashed_password.decode('utf-8')
        
        # Create user document
        user_doc = {
            "email": email,
            "password": hashed_password_str,  # Store hashed password
            "name": name,
            "userType": user_type,
            "isQuestionnaireSubmitted": False,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
            "isActive": True
        }
        
        # Check if email already exists before inserting
        existing_user = users_collection.find_one({"email": email})
        if existing_user:
            return jsonify({
                "error": "Email already exists",
                "message": f"An account with email {email} already exists. Please use a different email or sign in."
            }), 409
        
        # Insert into MongoDB
        result = users_collection.insert_one(user_doc)
        
        return jsonify({
            "success": True,
            "message": "User created successfully",
            "userId": str(result.inserted_id),
            "email": email,
            "userType": user_type
        }), 201
        
    except DuplicateKeyError:
        # Fallback: MongoDB unique index violation
        return jsonify({
            "error": "Email already exists",
            "message": f"An account with email {email} already exists. Please use a different email or sign in."
        }), 409
        
    except Exception as e:
        return jsonify({
            "error": "Signup failed",
            "message": str(e)
        }), 500


@app.route("/api/v1/auth/login", methods=["POST"])
def login():
    """
    Authenticate user and return user info.
    
    Expects JSON body:
    {
        "email": "user@example.com",
        "password": "password123"
    }
    """
    try:
        if mongodb_client is None or users_collection is None:
            return jsonify({
                "error": "Database unavailable",
                "message": "MongoDB connection not established"
            }), 503
        
        data = request.get_json()
        
        if not data or not data.get("email") or not data.get("password"):
            return jsonify({
                "error": "Missing credentials",
                "message": "Email and password are required"
            }), 400
        
        email = data["email"].strip().lower()
        password = data["password"]
        
        # Check for admin login first (hardcoded credentials)
        ADMIN_EMAIL = "admin@pathway.com"
        ADMIN_PASSWORD = "pathway2025"
        
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            return jsonify({
                "success": True,
                "message": "Admin login successful",
                "userId": "admin",
                "email": ADMIN_EMAIL,
                "name": "Admin",
                "userType": "admin",
                "isQuestionnaireSubmitted": True
            }), 200
        
        # Find user in MongoDB
        user = users_collection.find_one({"email": email})
        
        if not user:
            return jsonify({
                "error": "Invalid credentials",
                "message": "Email or password is incorrect"
            }), 401
        
        # Check password using bcrypt
        stored_password = user.get("password", "")
        password_bytes = password.encode('utf-8')
        
        # Check if password is hashed (starts with bcrypt hash format) or plaintext (backward compatibility)
        if stored_password.startswith("$2b$") or stored_password.startswith("$2a$") or stored_password.startswith("$2y$"):
            # Password is hashed, verify using bcrypt
            stored_password_bytes = stored_password.encode('utf-8')
            if not bcrypt.checkpw(password_bytes, stored_password_bytes):
                return jsonify({
                    "error": "Invalid credentials",
                    "message": "Email or password is incorrect"
                }), 401
        else:
            # Legacy plaintext password (backward compatibility)
            # Verify plaintext and optionally upgrade to hashed
            if stored_password != password:
                return jsonify({
                    "error": "Invalid credentials",
                    "message": "Email or password is incorrect"
                }), 401
            
            # Upgrade plaintext password to hashed (optional - can be removed after migration)
            try:
                hashed_password = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
                users_collection.update_one(
                    {"_id": user["_id"]},
                    {"$set": {"password": hashed_password.decode('utf-8')}}
                )
            except Exception as e:
                logger.warning(f"Failed to upgrade password for user {email}: {e}")
        
        # Check if user is active
        if not user.get("isActive", True):
            return jsonify({
                "error": "Account disabled",
                "message": "Your account has been disabled"
            }), 403
        
        # Return user info (without password)
        return jsonify({
            "success": True,
            "message": "Login successful",
            "userId": str(user["_id"]),
            "email": user["email"],
            "name": user["name"],
            "userType": user["userType"],
            "isQuestionnaireSubmitted": user.get("isQuestionnaireSubmitted", False)
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": "Login failed",
            "message": str(e)
        }), 500


@app.route("/api/v1/auth/user-id", methods=["GET"])
def get_user_id_by_email():
    """
    Get userId by email. Used to recover userId when it's lost from localStorage.
    
    Query params:
    - email: User's email address
    
    Returns:
    {
        "success": true,
        "userId": "6932eafade8ac2f8b00c1174",
        "email": "user@example.com"
    }
    """
    try:
        if mongodb_client is None or users_collection is None:
            return jsonify({
                "error": "Database unavailable",
                "message": "MongoDB connection not established"
            }), 503
        
        email = request.args.get("email")
        if not email:
            return jsonify({
                "error": "Missing email",
                "message": "Email query parameter is required"
            }), 400
        
        email = email.strip().lower()
        
        # Find user in MongoDB
        user = users_collection.find_one({"email": email})
        
        if not user:
            return jsonify({
                "error": "User not found",
                "message": f"No user found with email: {email}"
            }), 404
        
        # Return userId
        return jsonify({
            "success": True,
            "userId": str(user["_id"]),
            "email": user["email"]
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": "Failed to get userId",
            "message": str(e)
        }), 500


@app.route("/api/v1/user/questionnaire-status", methods=["POST"])
def update_questionnaire_status():
    """
    Update questionnaire submission status for a user.
    
    Expects JSON body:
    {
        "userId": "user_id_here",
        "isQuestionnaireSubmitted": true
    }
    """
    try:
        if mongodb_client is None or users_collection is None:
            return jsonify({
                "error": "Database unavailable",
                "message": "MongoDB connection not established"
            }), 503
        
        data = request.get_json()
        
        if not data or not data.get("userId"):
            return jsonify({
                "error": "Missing userId",
                "message": "userId is required"
            }), 400
        
        user_id = data["userId"]
        is_submitted = data.get("isQuestionnaireSubmitted", True)
        
        # Handle email-based IDs (starting with "email-") by finding user by email
        if user_id.startswith("email-"):
            # Extract email from the ID
            email = user_id.replace("email-", "")
            
            # Update user document by email
            result = users_collection.update_one(
                {"email": email.lower()},  # Use lowercase for consistency
                {
                    "$set": {
                        "isQuestionnaireSubmitted": is_submitted,
                        "updatedAt": datetime.utcnow()
                    }
                }
            )
            
            if result.matched_count == 0:
                return jsonify({
                    "error": "User not found",
                    "message": f"User with email {email} not found"
                }), 404
        # Handle temporary IDs (starting with "temp-") for backward compatibility
        elif user_id.startswith("temp-"):
            # Extract email from temporary ID
            try:
                import base64
                encoded_email = user_id.replace("temp-", "")
                # Try to decode, but it might be truncated
                try:
                    email = base64.b64decode(encoded_email + "==").decode('utf-8')
                except:
                    # If decoding fails, try without padding
                    email = base64.b64decode(encoded_email).decode('utf-8')
                
                # Update user document by email (try exact match first, then partial)
                result = users_collection.update_one(
                    {"email": {"$regex": f"^{email}", "$options": "i"}},
                    {
                        "$set": {
                            "isQuestionnaireSubmitted": is_submitted,
                            "updatedAt": datetime.utcnow()
                        }
                    }
                )
                
                if result.matched_count == 0:
                    return jsonify({
                        "error": "User not found",
                        "message": f"User with email matching {email} not found"
                    }), 404
            except Exception as e:
                return jsonify({
                    "error": "Invalid temporary userId format",
                    "message": f"Could not decode temporary userId: {str(e)}"
                }), 400
        else:
            # Convert string ID to ObjectId for regular MongoDB IDs
            try:
                user_object_id = ObjectId(user_id)
            except Exception:
                return jsonify({
                    "error": "Invalid userId format",
                    "message": "userId must be a valid MongoDB ObjectId"
                }), 400
            
            # Update user document
            result = users_collection.update_one(
                {"_id": user_object_id},
                {
                    "$set": {
                        "isQuestionnaireSubmitted": is_submitted,
                        "updatedAt": datetime.utcnow()
                    }
                }
            )
            
            if result.matched_count == 0:
                return jsonify({
                    "error": "User not found",
                    "message": f"User with id {user_id} not found"
                }), 404
        
        return jsonify({
            "success": True,
            "message": "Questionnaire status updated successfully",
            "isQuestionnaireSubmitted": is_submitted
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": "Update failed",
            "message": str(e)
        }), 500


@app.route("/api/v1/user/questionnaire", methods=["POST"])
def submit_questionnaire():
    """
    Collect and process questionnaire data.
    
    Expects JSON with:
    - userId: string (MongoDB ObjectId, 24 hex characters)
    - formData: object with all form fields
    - documents: object with encrypted base64 strings (aadhaar, pan, itr)
    - videoCloudinaryUrl: string
    """
    try:
        if mongodb_client is None or users_collection is None:
            return jsonify({
                "error": "Database unavailable",
                "message": "MongoDB connection not established"
            }), 503
        
        # Get JSON data
        data = request.get_json()
        if not data:
            print("❌ Error: Request body is not JSON")
            return jsonify({
                "error": "Invalid request",
                "message": "Request must be JSON"
            }), 400
        
        print(f"📥 Received questionnaire data. Keys: {list(data.keys())}")
        
        user_id = data.get("userId")
        if not user_id:
            print("❌ Error: Missing userId in request")
            return jsonify({
                "error": "Missing userId",
                "message": "userId is required"
            }), 400
        
        # Validate userId format (must be MongoDB ObjectId)
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            print(f"❌ Error: Invalid userId format: {user_id}")
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId (24 hex characters). Please login again."
            }), 400
        
        # Verify user exists in MongoDB
        try:
            user_object_id = ObjectId(user_id)
            user = users_collection.find_one({"_id": user_object_id})
            if not user:
                print(f"❌ Error: User not found with userId: {user_id}")
                return jsonify({
                    "error": "User not found",
                    "message": "User with provided userId does not exist. Please login again."
                }), 404
        except Exception as e:
            print(f"❌ Error: Invalid ObjectId format: {user_id}, error: {str(e)}")
            return jsonify({
                "error": "Invalid userId",
                "message": f"Invalid userId format: {str(e)}. Please login again."
            }), 400
        
        form_data = data.get("formData", {})
        documents_data = data.get("documents", {})
        video_url = data.get("videoCloudinaryUrl", "")
        document_urls_from_frontend = data.get("documentUrls", {})  # URLs already uploaded from frontend
        
        print(f"📋 Form data keys: {list(form_data.keys()) if form_data else 'None'}")
        print(f"📄 Documents keys: {list(documents_data.keys()) if documents_data else 'None'}")
        print(f"🎥 Video URL: {video_url[:50] if video_url else 'None'}...")
        
        # Decrypt documents (they come encrypted from frontend)
        documents = {}
        doc_types = {
            "aadhaar": "aadhaar",
            "pan": "pan",
            "itr": "itr"
        }
        
        for doc_key, doc_type in doc_types.items():
            doc_info = documents_data.get(doc_key)
            print(f"🔍 Processing {doc_type} document: {doc_key}")
            if doc_info:
                print(f"   - Has encryptedContent: {bool(doc_info.get('encryptedContent'))}")
                print(f"   - Filename: {doc_info.get('filename', 'N/A')}")
                print(f"   - MIME type: {doc_info.get('mime_type', 'N/A')}")
            
            if doc_info and doc_info.get("encryptedContent"):
                encrypted_content = doc_info["encryptedContent"]
                filename = doc_info.get("filename", f"{doc_type}_document")
                
                # Decrypt the content
                if encryptor:
                    try:
                        print(f"🔓 Decrypting {doc_type} document...")
                        decrypted_base64 = encryptor.decrypt_value(encrypted_content)
                        documents[doc_type] = {
                            "filename": filename,
                            "content": decrypted_base64,  # Decrypted base64
                            "encrypted": False,  # Now decrypted
                            "size": len(decrypted_base64) if decrypted_base64 else 0,
                            "mime_type": doc_info.get("mime_type", "application/octet-stream")
                        }
                        print(f"✅ Successfully decrypted {doc_type} document ({len(decrypted_base64)} chars)")
                    except Exception as e:
                        print(f"❌ Failed to decrypt {doc_type} document: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        return jsonify({
                            "error": "Decryption failed",
                            "message": f"Failed to decrypt {doc_type} document: {str(e)}"
                        }), 400
                else:
                    print(f"⚠️  No encryptor available, using content as-is for {doc_type}")
                    # If no encryptor, assume content is already decrypted (shouldn't happen)
                    documents[doc_type] = {
                        "filename": filename,
                        "content": encrypted_content,
                        "encrypted": False,
                        "size": len(encrypted_content) if encrypted_content else 0,
                        "mime_type": doc_info.get("mime_type", "application/octet-stream")
                    }
            else:
                print(f"⚠️  {doc_type} document not found or missing encryptedContent")
        
        print(f"📦 Total documents processed: {len(documents)}")
        
        # Use document URLs from frontend if available, otherwise upload to Cloudinary
        document_urls = document_urls_from_frontend.copy() if document_urls_from_frontend else {}
        
        # Upload any documents that weren't uploaded from frontend or have invalid URLs
        for doc_type, doc_data in documents.items():
            # Check if we have a valid URL from frontend
            existing_url = document_urls.get(doc_type)
            has_valid_url = existing_url and existing_url.strip() and existing_url.startswith("http")
            
            if not has_valid_url and doc_data and doc_data.get("content"):
                # No valid URL from frontend, upload to Cloudinary
                logger.info("☁️  Uploading %s to Cloudinary (not uploaded from frontend or invalid URL)...", doc_type)
                cloudinary_url = upload_document_to_cloudinary(
                    base64_content=doc_data["content"],
                    user_id=user_id,
                    doc_type=doc_type,
                    filename=doc_data.get("filename", f"{doc_type}_document"),
                    mime_type=doc_data.get("mime_type", "application/pdf")
                )
                if cloudinary_url:
                    document_urls[doc_type] = cloudinary_url
                    # Add Cloudinary URL to document data
                    doc_data["cloudinaryUrl"] = cloudinary_url
                    logger.info("✅ %s uploaded to Cloudinary: %s", doc_type, cloudinary_url)
                else:
                    logger.warning("⚠️  Failed to upload %s to Cloudinary, but continuing...", doc_type)
            elif has_valid_url:
                # Document already uploaded from frontend with valid URL
                if doc_data:
                    doc_data["cloudinaryUrl"] = existing_url
                logger.info("✅ %s URL from frontend: %s", doc_type, existing_url)
            else:
                logger.warning("⚠️  %s document has no content or invalid URL, skipping upload", doc_type)
        
        # Build complete questionnaire payload
        questionnaire_payload = {
            "userId": user_id,
            "submittedAt": datetime.utcnow().isoformat(),
            "personalInformation": {
                "fullName": form_data.get("fullName", ""),
                "dateOfBirth": form_data.get("dateOfBirth", ""),
                "email": form_data.get("email", ""),
                "contactNumber": form_data.get("contactNumber", ""),
                "countryCode": form_data.get("countryCode", "")
            },
            "addressInformation": {
                "addressLine1": form_data.get("addressLine1", ""),
                "addressLine2": form_data.get("addressLine2", ""),
                "city": form_data.get("city", ""),
                "state": form_data.get("state", ""),
                "pinCode": form_data.get("pinCode", "")
            },
            "additionalDetails": {
                "occupation": form_data.get("occupation", ""),
                "maritalStatus": form_data.get("maritalStatus", ""),
                "citizenship": form_data.get("citizenship", ""),
                "incomeRange": form_data.get("incomeRange", ""),
                "amountToInvest": form_data.get("amountToInvest", ""),
                "dependents": form_data.get("dependents", ""),
                "dependentDetails": form_data.get("dependentDetails", "")
            },
            "investmentQuestions": {
                "q1": form_data.get("investmentQ1", ""),
                "q2": form_data.get("investmentQ2", ""),
                "q3": form_data.get("investmentQ3", ""),
                "q4": form_data.get("investmentQ4", ""),
                "q5": form_data.get("investmentQ5", ""),
                "q6": form_data.get("investmentQ6", "")
            },
            "documents": documents,
            "documentUrls": document_urls,  # Store Cloudinary URLs separately for easy access
            "video": {
                "cloudinaryUrl": video_url,
                "uploadedAt": datetime.utcnow().isoformat() if video_url else None
            }
        }
        
        # Log questionnaire submission (without sensitive image data)
        logger.info("Questionnaire submitted for user_id: %s", user_id)
        
        # Convert decrypted base64 documents to PIL Images
        print("🔄 Starting document conversion to PIL Images...")
        pan_image = None
        aadhaar_image = None
        itr_image = None
        
        print(f"📊 convert_base64_to_image available: {convert_base64_to_image is not None}")
        print(f"📊 VERIFICATION_AVAILABLE: {VERIFICATION_AVAILABLE}")
        
        if not convert_base64_to_image:
            return jsonify({
                "error": "Internal server error",
                "message": "Document conversion utility not available"
            }), 500
        
        try:
            print(f"🔍 Checking PAN document: {bool(documents.get('pan', {}).get('content'))}")
            if documents.get("pan", {}).get("content"):
                pan_content = documents["pan"]["content"]
                pan_mime = documents.get("pan", {}).get("mime_type")
                print(f"🔄 Converting PAN document (MIME: {pan_mime}, content length: {len(pan_content) if pan_content else 0})...")
                try:
                    pan_image = convert_base64_to_image(pan_content, pan_mime)
                    print(f"✅ Converted PAN document to PIL Image (size: {pan_image.size if pan_image else 'None'})")
                except Exception as pan_err:
                    print(f"❌ PAN conversion error: {str(pan_err)}")
                    import traceback
                    traceback.print_exc()
                    raise
            
            print(f"🔍 Checking Aadhaar document: {bool(documents.get('aadhaar', {}).get('content'))}")
            if documents.get("aadhaar", {}).get("content"):
                aadhaar_content = documents["aadhaar"]["content"]
                aadhaar_mime = documents.get("aadhaar", {}).get("mime_type")
                print(f"🔄 Converting Aadhaar document (MIME: {aadhaar_mime}, content length: {len(aadhaar_content) if aadhaar_content else 0})...")
                try:
                    aadhaar_image = convert_base64_to_image(aadhaar_content, aadhaar_mime)
                    print(f"✅ Converted Aadhaar document to PIL Image (size: {aadhaar_image.size if aadhaar_image else 'None'})")
                except Exception as aadhaar_err:
                    print(f"❌ Aadhaar conversion error: {str(aadhaar_err)}")
                    import traceback
                    traceback.print_exc()
                    raise
            
            print(f"🔍 Checking ITR document: {bool(documents.get('itr', {}).get('content'))}")
            if documents.get("itr", {}).get("content"):
                itr_content = documents["itr"]["content"]
                itr_mime = documents.get("itr", {}).get("mime_type")
                print(f"🔄 Converting ITR document (MIME: {itr_mime}, content length: {len(itr_content) if itr_content else 0})...")
                try:
                    itr_image = convert_base64_to_image(itr_content, itr_mime)
                    print(f"✅ Converted ITR document to PIL Image (size: {itr_image.size if itr_image else 'None'})")
                except Exception as itr_err:
                    print(f"❌ ITR conversion error: {str(itr_err)}")
                    import traceback
                    traceback.print_exc()
                    raise
        except Exception as e:
            print(f"❌ Failed to convert documents to images: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({
                "error": "Document conversion failed",
                "message": f"Failed to convert documents to images: {str(e)}"
            }), 400
        
        print(f"📊 Document conversion complete. PAN: {pan_image is not None}, Aadhaar: {aadhaar_image is not None}, ITR: {itr_image is not None}")
        
        # Check if all required documents are present
        missing_docs = []
        if not pan_image:
            missing_docs.append("PAN")
        if not aadhaar_image:
            missing_docs.append("Aadhaar")
        if not itr_image:
            missing_docs.append("ITR")
        
        if missing_docs:
            print(f"❌ Missing documents: {', '.join(missing_docs)}")
            return jsonify({
                "error": "Missing documents",
                "message": f"The following documents are required but were not provided: {', '.join(missing_docs)}"
            }), 400
        
        # Run verification
        verification_results = None
        if VERIFICATION_AVAILABLE:
            if not verify_questionnaire_submission:
                print("❌ verify_questionnaire_submission function is not available despite VERIFICATION_AVAILABLE being True.")
                return jsonify({
                    "error": "Internal server error",
                    "message": "Verification function not available"
                }), 500
            try:
                print("\n" + "="*80)
                print("STARTING KYC VERIFICATION PROCESS...")
                print("="*80)
                
                verification_results = verify_questionnaire_submission(
                    pan_image=pan_image,
                    aadhaar_image=aadhaar_image,
                    itr_image=itr_image,
                    video_url=video_url,
                    questionnaire_data=questionnaire_payload["investmentQuestions"],
                    form_data=form_data
                )
                
                if verification_results.get("error"):
                    print(f"⚠️  Verification error: {verification_results['error']}")
                else:
                    # Log the master verification JSON
                    master_json = verification_results.get("master_verification")
                    if master_json:
                        print("\n" + "="*80)
                        print("FINAL VERIFICATION OUTPUT (MASTER JSON)")
                        print("="*80)
                        print(json.dumps(master_json, indent=2, ensure_ascii=False))
                        print("="*80 + "\n")
                    
                    ml_input = verification_results.get("ml_model_input")
                    if ml_input:
                        print("\n" + "="*80)
                        print("ML MODEL INPUT JSON")
                        print("="*80)
                        print(json.dumps(ml_input, indent=2, ensure_ascii=False))
                        print("="*80 + "\n")
            except Exception as e:
                print(f"❌ Verification failed: {str(e)}")
                import traceback
                traceback.print_exc()
                verification_results = {
                    "error": f"Verification process failed: {str(e)}",
                    "master_verification": None,
                    "ml_model_input": None
                }
        else:
            print("⚠️  Verification module not available, skipping verification")
            verification_results = {
                "error": "Verification module not available",
                "master_verification": None,
                "ml_model_input": None
            }
        
        # Update questionnaire status and store document/video URLs
        update_data = {
            "isQuestionnaireSubmitted": True,
            "updatedAt": datetime.utcnow(),
            "questionnaire": questionnaire_payload,
            "documentUrls": document_urls,  # Store Cloudinary URLs for documents
            "videoCloudinaryUrl": video_url  # Store Cloudinary URL for video
        }
        
        # Handle email-based IDs
        if user_id.startswith("email-"):
            email = user_id.replace("email-", "")
            result = users_collection.update_one(
                {"email": email.lower()},
                {"$set": update_data}
            )
        # Handle temporary IDs
        elif user_id.startswith("temp-"):
            try:
                import base64 as b64
                encoded_email = user_id.replace("temp-", "")
                try:
                    email = b64.b64decode(encoded_email + "==").decode('utf-8')
                except:
                    email = b64.b64decode(encoded_email).decode('utf-8')
                
                result = users_collection.update_one(
                    {"email": {"$regex": f"^{email}", "$options": "i"}},
                    {"$set": update_data}
                )
            except Exception as e:
                return jsonify({
                    "error": "Invalid userId format",
                    "message": f"Could not process userId: {str(e)}"
                }), 400
        else:
            # Regular ObjectId
            try:
                user_object_id = ObjectId(user_id)
                result = users_collection.update_one(
                    {"_id": user_object_id},
                    {"$set": update_data}
                )
            except Exception:
                return jsonify({
                    "error": "Invalid userId format",
                    "message": "userId must be a valid MongoDB ObjectId"
                }), 400
        
        if result.matched_count == 0:
            return jsonify({
                "error": "User not found",
                "message": f"User with id {user_id} not found"
            }), 404
        
        # Store payload in SQLite if available
        payload_stored = False
        payload_storage_error = None
        stored_payload_id = None
        orchestration_started = False
        orchestration_task_id = None
        orchestration_error = None
        
        if PAYLOAD_STORAGE_AVAILABLE and payload_store is not None and verification_results:
            try:
                master_json = verification_results.get("master_verification")
                ml_input_json = verification_results.get("ml_model_input")
                
                if master_json and ml_input_json:
                    # Normalize user_id for storage (user_id is already validated as ObjectId)
                    normalized_user_id = normalize_user_id(user_id)
                    
                    # Calculate validation status based on image/video verification
                    verification_status = master_json.get("verification_status", {})
                    document_verified = verification_status.get("document_verification", False)
                    video_verified = verification_status.get("video_verification", False)
                    overall_verified = verification_status.get("overall_status", False)
                    
                    # Set validationStatus: "passed" if both image and video verified, "failed" otherwise
                    validation_status = "passed" if overall_verified else "failed"
                    
                    # Update user document with validation status
                    try:
                        user_object_id = ObjectId(normalized_user_id)
                        users_collection.update_one(
                            {"_id": user_object_id},
                            {"$set": {"validationStatus": validation_status}}
                        )
                        logger.info(f"Updated validationStatus to '{validation_status}' for user_id={normalized_user_id} (doc: {document_verified}, video: {video_verified})")
                    except Exception as e:
                        logger.warning(f"Failed to update validationStatus: {e}")
                    
                    # Determine payload status based on verification results
                    status = "completed"
                    if verification_results.get("error"):
                        status = "failed"
                    
                    # Create metadata
                    metadata = {
                        "submitted_at": datetime.utcnow().isoformat(),
                        "original_user_id": user_id,
                        "verification_error": verification_results.get("error")
                    }
                    
                    # Store payload using MongoDB PayloadStore
                    if payload_store:
                        payload = OverallPayload(
                            user_id=normalized_user_id,
                            master_json=master_json,
                            ml_input_json=ml_input_json,
                            status=status,
                            metadata=metadata
                        )
                        stored_payload_id = payload_store.save(payload)
                        payload_stored = True
                        print(f"✅ Payload stored successfully in MongoDB")
                        print(f"   User ID: {normalized_user_id}")
                        print(f"   Status: {status}")
                        print(f"   Collection: payloads")
                        print(f"   Master JSON keys: {list(master_json.keys()) if master_json else 'None'}")
                        print(f"   ML Input JSON keys: {list(ml_input_json.keys()) if ml_input_json else 'None'}")
                        
                        # Automatically trigger orchestration after payload storage
                        try:
                            from flask_server.orchestration_helper import run_orchestration_in_thread
                            
                            # Generate task ID for orchestration
                            orchestration_task_id = f"orch-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                            
                            # Update payload status to processing
                            payload_store.update_status(normalized_user_id, "processing", {"task_id": orchestration_task_id})
                            
                            logger.info("🚀 Automatically starting orchestration...")
                            logger.info("   Task ID: %s", orchestration_task_id)
                            logger.info("   User ID: %s", normalized_user_id)
                            
                            # Start orchestration in background thread
                            # Use default options: run all steps (KYCV, RiskScore, report, alerts)
                            run_orchestration_in_thread(
                                user_id=normalized_user_id,
                                task_id=orchestration_task_id,
                                run_kycv=True,
                                run_risk_score=True,
                                generate_report=True,
                                plan_alerts=True,
                                payload_store_instance=payload_store,
                                users_collection_instance=users_collection,
                            )
                            
                            orchestration_started = True
                            logger.info("✅ Orchestration started in background thread")
                            
                        except ImportError as e:
                            orchestration_error = f"Orchestration module not available: {str(e)}"
                            logger.warning("⚠️  Could not start automatic orchestration: %s", orchestration_error)
                        except Exception as e:
                            orchestration_error = f"Failed to start orchestration: {str(e)}"
                            logger.warning("⚠️  Could not start automatic orchestration: %s", orchestration_error)
                            logger.error(f"Automatic orchestration failed: {orchestration_error}", exc_info=True)
                            # Update status back to pending if orchestration failed to start
                            try:
                                payload_store.update_status(normalized_user_id, "pending", {"orchestration_start_error": orchestration_error})
                            except Exception:
                                pass
                        
            except Exception as e:
                payload_storage_error = str(e)
                print(f"❌ Payload storage failed: {str(e)}")
                import traceback
                traceback.print_exc()
                # Don't fail the request if storage fails
        
        # Prepare response
        response_data = {
            "success": True,
            "message": "Questionnaire submitted and verified successfully",
            "isQuestionnaireSubmitted": True,
            "payload_stored": payload_stored,
            "payload_id": stored_payload_id if payload_stored else None
        }
        
        if payload_storage_error:
            response_data["payload_storage_warning"] = payload_storage_error
            print(f"⚠️  Payload storage warning: {payload_storage_error}")
        
        # Add orchestration status if it was attempted
        if payload_stored:
            if orchestration_started:
                response_data["orchestration"] = {
                    "started": True,
                    "task_id": orchestration_task_id,
                    "status": "processing",
                    "message": "Orchestration started automatically. Check status endpoint for results."
                }
            elif orchestration_error:
                response_data["orchestration"] = {
                    "started": False,
                    "error": orchestration_error,
                    "message": "Orchestration could not be started automatically. You can trigger it manually via /api/v1/orchestrate"
                }
        
        # Include verification results if available
        if verification_results:
            if verification_results.get("master_verification"):
                response_data["verification"] = verification_results["master_verification"]
            if verification_results.get("ml_model_input"):
                response_data["ml_model_input"] = verification_results["ml_model_input"]
            if verification_results.get("error"):
                response_data["verification_error"] = verification_results["error"]
        
        return jsonify(response_data), 200
        
    except Exception as e:
        print(f"Error processing questionnaire: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Questionnaire submission failed",
            "message": str(e)
        }), 500


@app.route("/api/v1/user/<user_id>/payload", methods=["GET"])
def get_user_payload(user_id: str):
    """Retrieve stored payload for a user (decrypted)."""
    if not PAYLOAD_STORAGE_AVAILABLE or not payload_store:
        return jsonify({
            "error": "Payload storage not available",
            "message": "Payload storage module is not initialized"
        }), 503
    
    try:
        # Validate userId format first
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId (24 hex characters)."
            }), 400
        
        normalized_user_id = normalize_user_id(user_id)
        payload = payload_store.get(normalized_user_id)
        
        if payload is None:
            return jsonify({
                "error": "Payload not found",
                "message": f"No payload found for user_id: {normalized_user_id}"
            }), 404
        
        return jsonify({
            "user_id": payload.user_id,
            "master_json": payload.master_json,
            "ml_input_json": payload.ml_input_json,
            "status": payload.status,
            "created_at": payload.created_at,
            "updated_at": payload.updated_at,
            "metadata": payload.metadata
        }), 200
    except Exception as e:
        return jsonify({
            "error": "Failed to retrieve payload",
            "message": str(e)
        }), 500


@app.route("/api/v1/user/<user_id>/payload/masked", methods=["GET"])
def get_user_payload_masked(user_id: str):
    """Retrieve stored payload with sensitive fields masked (for display)."""
    if not PAYLOAD_STORAGE_AVAILABLE or not payload_store:
        return jsonify({
            "error": "Payload storage not available",
            "message": "Payload storage module is not initialized"
        }), 503
    
    try:
        # Validate userId format first
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId (24 hex characters)."
            }), 400
        
        normalized_user_id = normalize_user_id(user_id)
        payload = payload_store.get_masked(normalized_user_id)
        
        if payload is None:
            return jsonify({
                "error": "Payload not found",
                "message": f"No payload found for user_id: {normalized_user_id}"
            }), 404
        
        return jsonify({
            "user_id": payload.user_id,
            "master_json": payload.master_json,
            "ml_input_json": payload.ml_input_json,
            "status": payload.status,
            "created_at": payload.created_at,
            "updated_at": payload.updated_at,
            "metadata": payload.metadata
        }), 200
    except Exception as e:
        return jsonify({
            "error": "Failed to retrieve payload",
            "message": str(e)
        }), 500


@app.route("/api/v1/user/<user_id>/payload/master", methods=["GET"])
def get_user_payload_master(user_id: str):
    """Retrieve only master_json for a user (for KYCV MCP server)."""
    if not PAYLOAD_STORAGE_AVAILABLE or not payload_store:
        return jsonify({
            "error": "Payload storage not available",
            "message": "Payload storage module is not initialized"
        }), 503
    
    try:
        # Validate userId format first
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId (24 hex characters)."
            }), 400
        
        normalized_user_id = normalize_user_id(user_id)
        master_json = payload_store.get_master_json(normalized_user_id)
        
        if master_json is None:
            return jsonify({
                "error": "Payload not found",
                "message": f"No payload found for user_id: {normalized_user_id}"
            }), 404
        
        return jsonify({
            "user_id": normalized_user_id,
            "master_json": master_json
        }), 200
    except Exception as e:
        return jsonify({
            "error": "Failed to retrieve master_json",
            "message": str(e)
        }), 500


@app.route("/api/v1/user/<user_id>/payload/ml", methods=["GET"])
def get_user_payload_ml(user_id: str):
    """Retrieve only ml_input_json for a user (for RiskScore MCP server)."""
    if not PAYLOAD_STORAGE_AVAILABLE or not payload_store:
        return jsonify({
            "error": "Payload storage not available",
            "message": "Payload storage module is not initialized"
        }), 503
    
    try:
        # Validate userId format first
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId (24 hex characters)."
            }), 400
        
        normalized_user_id = normalize_user_id(user_id)
        ml_input_json = payload_store.get_ml_input_json(normalized_user_id)
        
        if ml_input_json is None:
            return jsonify({
                "error": "Payload not found",
                "message": f"No payload found for user_id: {normalized_user_id}"
            }), 404
        
        return jsonify({
            "user_id": normalized_user_id,
            "ml_input_json": ml_input_json
        }), 200
    except Exception as e:
        return jsonify({
            "error": "Failed to retrieve ml_input_json",
            "message": str(e)
        }), 500


@app.route("/api/v1/payloads/check", methods=["GET"])
def check_payload_storage():
    """Check if payload storage is working and show stats."""
    if not PAYLOAD_STORAGE_AVAILABLE or not payload_store:
        return jsonify({
            "payload_storage_available": False,
            "message": "Payload storage module is not initialized"
        }), 503
    
    try:
        # Get database path
        db_path = payload_store.db_path if hasattr(payload_store, 'db_path') else "unknown"
        
        # Try to get a count (if possible)
        import os
        db_exists = os.path.exists(db_path) if db_path != "unknown" else False
        
        return jsonify({
            "payload_storage_available": True,
            "database_path": db_path,
            "database_exists": db_exists,
            "message": "Payload storage is ready. Use GET /api/v1/user/<user_id>/payload to retrieve stored payloads."
        }), 200
    except Exception as e:
        return jsonify({
            "payload_storage_available": True,
            "error": str(e),
            "message": "Payload storage initialized but check failed"
        }), 500


@app.route("/api/v1/orchestrate", methods=["POST"])
def trigger_orchestration():
    """
    Trigger KYC orchestration for a user.
    
    Expects JSON body:
    {
        "userId": "6932eafade8ac2f8b00c1174",
        "runKycv": true,        // Optional, default: true
        "runRiskScore": true,    // Optional, default: true
        "generateReport": true,  // Optional, default: true
        "planAlerts": true       // Optional, default: true
    }
    
    Returns immediately with task_id. Orchestration runs in background.
    """
    try:
        if not PAYLOAD_STORAGE_AVAILABLE or not payload_store:
            return jsonify({
                "error": "Payload storage not available",
                "message": "Payload storage must be initialized before orchestration"
            }), 503
        
        data = request.get_json()
        if not data:
            return jsonify({
                "error": "Invalid request",
                "message": "Request must be JSON"
            }), 400
        
        user_id = data.get("userId")
        if not user_id:
            return jsonify({
                "error": "Missing userId",
                "message": "userId is required"
            }), 400
        
        # Validate userId format
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId"
            }), 400
        
        # Check if payload exists
        payload = payload_store.get(user_id)
        if payload is None:
            return jsonify({
                "error": "Payload not found",
                "message": f"No payload found for user_id: {user_id}. Submit questionnaire first."
            }), 404
        
        # Get options (defaults to True)
        run_kycv = data.get("runKycv", True)
        run_risk_score = data.get("runRiskScore", True)
        generate_report = data.get("generateReport", True)
        plan_alerts = data.get("planAlerts", True)
        
        # Generate task ID
        task_id = f"orch-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Update status to processing
        payload_store.update_status(user_id, "processing", {"task_id": task_id})
        
        # Import and run orchestration in background thread
        try:
            from flask_server.orchestration_helper import run_orchestration_in_thread
            
            # Start orchestration in background thread
            # Pass MongoDB payload_store instance to orchestrator
            run_orchestration_in_thread(
                user_id=user_id,
                task_id=task_id,
                run_kycv=run_kycv,
                run_risk_score=run_risk_score,
                generate_report=generate_report,
                plan_alerts=plan_alerts,
                payload_store_instance=payload_store,  # Pass MongoDB store
                users_collection_instance=users_collection,
            )
            
            return jsonify({
                "success": True,
                "task_id": task_id,
                "user_id": user_id,
                "status": "processing",
                "message": "Orchestration started. Check status endpoint for results."
            }), 202  # 202 Accepted (processing)
            
        except ImportError as e:
            return jsonify({
                "error": "Orchestrator not available",
                "message": f"Orchestrator module not available: {str(e)}"
            }), 503
        except Exception as e:
            logger.error(f"Failed to start orchestration: {e}")
            return jsonify({
                "error": "Failed to start orchestration",
                "message": str(e)
            }), 500
            
    except Exception as e:
        return jsonify({
            "error": "Orchestration trigger failed",
            "message": str(e)
        }), 500


@app.route("/api/v1/orchestrate/<user_id>/status", methods=["GET"])
def get_orchestration_status(user_id: str):
    """
    Get orchestration status and results for a user.
    
    Returns:
    {
        "user_id": "...",
        "status": "pending|processing|completed|failed",
        "task_id": "...",
        "kycv_report": "...",      // If completed
        "alert_plan": {...},        // If completed
        "risk_score": {...},       // If completed
        "errors": [...]            // If any errors
    }
    """
    try:
        if not PAYLOAD_STORAGE_AVAILABLE or not payload_store:
            return jsonify({
                "error": "Payload storage not available",
                "message": "Payload storage must be initialized"
            }), 503
        
        # Validate userId format
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId"
            }), 400
        
        # Get payload
        payload = payload_store.get(user_id)
        if payload is None:
            return jsonify({
                "error": "Payload not found",
                "message": f"No payload found for user_id: {user_id}"
            }), 404
        
        # Extract orchestration results from metadata
        metadata = payload.metadata or {}
        orchestration_result = metadata.get("orchestration_result", {})
        task_id = metadata.get("task_id")
        
        # Build response
        response = {
            "user_id": user_id,
            "status": payload.status,  # pending, processing, completed, failed
            "task_id": task_id,
        }
        
        # Add orchestration results if available
        if orchestration_result:
            response.update({
                "kycv_report": orchestration_result.get("kycv_report"),
                "alert_plan": orchestration_result.get("alert_plan"),
                "risk_score": orchestration_result.get("risk_score"),
                "actions_executed": orchestration_result.get("actions_executed", []),
                "errors": orchestration_result.get("errors", []),
                "started_at": orchestration_result.get("started_at"),
                "completed_at": orchestration_result.get("completed_at"),
            })
        
        return jsonify(response), 200
        
    except Exception as e:
        return jsonify({
            "error": "Failed to get orchestration status",
            "message": str(e)
        }), 500


@app.route("/", methods=["GET"])
def root():
    """Root endpoint."""
    endpoints = {
        "health": "GET /health",
        "signup": "POST /api/v1/auth/signup",
        "login": "POST /api/v1/auth/login",
        "getUserIdByEmail": "GET /api/v1/auth/user-id?email={email}",
        "updateQuestionnaireStatus": "POST /api/v1/user/questionnaire-status",
        "submitQuestionnaire": "POST /api/v1/user/questionnaire",
        "checkPayloadStorage": "GET /api/v1/payloads/check",
        "triggerOrchestration": "POST /api/v1/orchestrate",
        "getOrchestrationStatus": "GET /api/v1/orchestrate/<user_id>/status"
    }
    
    # Add payload endpoints if available
    if PAYLOAD_STORAGE_AVAILABLE:
        endpoints.update({
            "getPayload": "GET /api/v1/user/<user_id>/payload",
            "getPayloadMasked": "GET /api/v1/user/<user_id>/payload/masked",
            "getPayloadMaster": "GET /api/v1/user/<user_id>/payload/master",
            "getPayloadML": "GET /api/v1/user/<user_id>/payload/ml"
        })
    
    return jsonify({
        "message": "KYC Flask API",
        "version": "1.0.0",
        "endpoints": endpoints,
        "payload_storage_available": PAYLOAD_STORAGE_AVAILABLE
    }), 200


# ============================================================================
# Alerts API Endpoints
# ============================================================================

@app.route("/api/v1/user/<user_id>/alerts", methods=["GET"])
def get_user_alerts(user_id: str):
    """
    Get all alerts for a user (for polling).
    
    Query parameters:
        - read: Filter by read status (true/false, optional)
        - limit: Maximum number of alerts to return (default: 100)
    
    Returns:
        JSON array of alerts
    """
    if alerts_store is None:
        return jsonify({
            "error": "Alerts store not available",
            "message": "MongoDB alerts storage not initialized"
        }), 503
    
    # Validate userId format
    import re
    if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
        return jsonify({
            "error": "Invalid userId format",
            "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
        }), 400
    
    # Get query parameters
    read_param = request.args.get("read")
    read = None
    if read_param is not None:
        read = read_param.lower() == "true"
    
    limit = int(request.args.get("limit", 100))
    limit = min(limit, 1000)  # Cap at 1000
    
    try:
        alerts = alerts_store.get_alerts(user_id, read=read, limit=limit)
        return jsonify({
            "user_id": user_id,
            "alerts": alerts,
            "count": len(alerts)
        }), 200
    except Exception as e:
        logger.error(f"Failed to get alerts for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to retrieve alerts",
            "message": str(e)
        }), 500


@app.route("/api/v1/user/<user_id>/alerts/unread", methods=["GET"])
def get_unread_alerts(user_id: str):
    """
    Get unread alerts for a user (for polling).
    
    Query parameters:
        - limit: Maximum number of alerts to return (default: 100)
    
    Returns:
        JSON array of unread alerts
    """
    if alerts_store is None:
        return jsonify({
            "error": "Alerts store not available",
            "message": "MongoDB alerts storage not initialized"
        }), 503
    
    # Validate userId format
    import re
    if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
        return jsonify({
            "error": "Invalid userId format",
            "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
        }), 400
    
    limit = int(request.args.get("limit", 100))
    limit = min(limit, 1000)  # Cap at 1000
    
    try:
        alerts = alerts_store.get_unread_alerts(user_id, limit=limit)
        unread_count = alerts_store.get_unread_count(user_id)
        return jsonify({
            "user_id": user_id,
            "alerts": alerts,
            "count": len(alerts),
            "unread_count": unread_count
        }), 200
    except Exception as e:
        logger.error(f"Failed to get unread alerts for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to retrieve unread alerts",
            "message": str(e)
        }), 500


@app.route("/api/v1/user/<user_id>/alerts/unread/count", methods=["GET"])
def get_unread_count(user_id: str):
    """
    Get count of unread alerts for a user (for polling).
    
    Returns:
        JSON with unread count
    """
    if alerts_store is None:
        return jsonify({
            "error": "Alerts store not available",
            "message": "MongoDB alerts storage not initialized"
        }), 503
    
    # Validate userId format
    import re
    if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
        return jsonify({
            "error": "Invalid userId format",
            "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
        }), 400
    
    try:
        count = alerts_store.get_unread_count(user_id)
        return jsonify({
            "user_id": user_id,
            "unread_count": count
        }), 200
    except Exception as e:
        logger.error(f"Failed to get unread count for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to retrieve unread count",
            "message": str(e)
        }), 500


@app.route("/api/v1/alerts/<alert_id>/read", methods=["PATCH", "PUT"])
def mark_alert_as_read(alert_id: str):
    """
    Mark an alert as read.
    
    Returns:
        JSON with success status
    """
    if alerts_store is None:
        return jsonify({
            "error": "Alerts store not available",
            "message": "MongoDB alerts storage not initialized"
        }), 503
    
    try:
        success = alerts_store.mark_as_read(alert_id)
        if success:
            return jsonify({
                "alert_id": alert_id,
                "read": True,
                "message": "Alert marked as read"
            }), 200
        else:
            return jsonify({
                "error": "Alert not found or already read",
                "alert_id": alert_id
            }), 404
    except Exception as e:
        logger.error(f"Failed to mark alert {alert_id} as read: {e}")
        return jsonify({
            "error": "Failed to mark alert as read",
            "message": str(e)
        }), 500


@app.route("/api/v1/user/<user_id>/alerts/read-all", methods=["PATCH", "PUT"])
def mark_all_alerts_as_read(user_id: str):
    """
    Mark all unread alerts for a user as read.
    
    Returns:
        JSON with number of alerts marked as read
    """
    if alerts_store is None:
        return jsonify({
            "error": "Alerts store not available",
            "message": "MongoDB alerts storage not initialized"
        }), 503
    
    # Validate userId format
    import re
    if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
        return jsonify({
            "error": "Invalid userId format",
            "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
        }), 400
    
    try:
        count = alerts_store.mark_all_as_read(user_id)
        return jsonify({
            "user_id": user_id,
            "marked_read": count,
            "message": f"Marked {count} alert(s) as read"
        }), 200
    except Exception as e:
        logger.error(f"Failed to mark all alerts as read for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to mark all alerts as read",
            "message": str(e)
        }), 500


# ============================================================================
# Risk Score API Endpoints
# ============================================================================

@app.route("/api/v1/user/<user_id>/risk-score", methods=["GET"])
def get_user_risk_score(user_id: str):
    """
    Get risk score for a user from orchestration results.
    
    Returns:
        JSON with risk score data if available
    """
    if payload_store is None:
        return jsonify({
            "error": "Payload store not available",
            "message": "MongoDB payload storage not initialized"
        }), 503
    
    # Validate userId format
    import re
    if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
        return jsonify({
            "error": "Invalid userId format",
            "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
        }), 400
    
    try:
        payload = payload_store.get(user_id)
        if payload is None:
            return jsonify({
                "user_id": user_id,
                "risk_score": None,
                "message": "No payload found for user"
            }), 200
        
        # Extract risk score from orchestration result
        orchestration_result = payload.metadata.get("orchestration_result", {})
        risk_score = orchestration_result.get("risk_score")
        
        if risk_score is None:
            return jsonify({
                "user_id": user_id,
                "risk_score": None,
                "message": "Risk score not yet calculated"
            }), 200
        
        return jsonify({
            "user_id": user_id,
            "risk_score": risk_score,
            "available": True
        }), 200
    except Exception as e:
        logger.error(f"Failed to get risk score for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to retrieve risk score",
            "message": str(e)
        }), 500


# ============================================================================
# Portfolio API Endpoints
# ============================================================================

def get_stream_data(tickers: list = None):
    """
    Read the latest stream CSV data to get current prices and daily changes.
    
    Args:
        tickers: Optional list of tickers to filter. If None, returns all tickers.
    
    Returns:
        dict: {ticker: {'price': float, 'daily_change': float, 'date': str}}
    """
    try:
        # Path to stream data directory
        stream_dir = Path(__file__).resolve().parent.parent / "SmartFolio" / "display_data" / "stream"
        
        # Try to find the latest stream file (by date in filename)
        stream_files = list(stream_dir.glob("*.csv"))
        if not stream_files:
            # Fallback to stream_snapshot.csv
            snapshot_file = stream_dir.parent / "stream_snapshot.csv"
            if snapshot_file.exists():
                stream_files = [snapshot_file]
            else:
                return {}
        
        # Sort by filename (which contains date) and get the latest
        stream_files.sort(reverse=True)
        latest_file = stream_files[0]
        
        # Read CSV
        df = pd.read_csv(latest_file)
        
        # Store all tickers in CSV for missing ticker detection (before date filtering)
        all_tickers_in_csv_full = df['kdcode'].unique().tolist() if 'kdcode' in df.columns else []
        
        # Ensure we have the required columns
        if 'kdcode' not in df.columns or 'close' not in df.columns:
            return {}
        
        # Get latest date in the file
        if 'dt' in df.columns:
            df['dt'] = pd.to_datetime(df['dt'])
            latest_date = df['dt'].max()
            df = df[df['dt'] == latest_date]
        
        # Calculate daily_change if not present
        if 'daily_change' not in df.columns and 'prev_close' in df.columns:
            df['daily_change'] = (df['close'] / df['prev_close']) - 1.0
        elif 'daily_change' not in df.columns:
            df['daily_change'] = 0.0
        
        # Filter by tickers if provided
        if tickers:
            # Create list of all possible ticker formats
            ticker_variants = []
            for t in tickers:
                # Add original ticker
                ticker_variants.append(t)
                # Add with .NS suffix if not present
                if '.' not in t:
                    ticker_variants.append(f"{t}.NS")
                # Add without .NS suffix if present
                elif t.endswith('.NS'):
                    ticker_variants.append(t.replace('.NS', ''))
            
            df = df[df['kdcode'].isin(ticker_variants)]
        
        # Build result dictionary
        result = {}
        for _, row in df.iterrows():
            ticker = row['kdcode']
            # Remove .NS suffix for consistency with portfolio weights
            ticker_clean = ticker.replace('.NS', '')
            
            # Extract daily_change value
            daily_change_val = 0.0
            if 'daily_change' in row and pd.notna(row['daily_change']):
                try:
                    daily_change_val = float(row['daily_change'])
                except (ValueError, TypeError):
                    daily_change_val = 0.0
            
            result[ticker_clean] = {
                'price': float(row['close']) if pd.notna(row['close']) else 0.0,
                'daily_change': daily_change_val,
                'date': str(row['dt']) if 'dt' in row and pd.notna(row['dt']) else None,
                'sector': str(row['sector']) if 'sector' in row and pd.notna(row['sector']) else 'Unknown'
            }
        
        return result
    except Exception as e:
        logger.error(f"Failed to read stream data: {e}")
        import traceback
        traceback.print_exc()
        return {}


def get_previous_day_portfolio_value(stream_dir: Path, tickers_weights: dict, invested_amount: float, current_stock_values: dict):
    """
    Calculate portfolio value from previous day using stream data.
    
    Args:
        stream_dir: Path to stream directory
        tickers_weights: {ticker: weight} dictionary
        invested_amount: Initial invested amount
        current_stock_values: {ticker: current_value} dictionary
    
    Returns:
        float: Previous day portfolio value
    """
    try:
        # Get stream files sorted by date
        stream_files = sorted(stream_dir.glob("*.csv"), reverse=True)
        if len(stream_files) < 2:
            return None
        
        # Get previous day file (second most recent)
        prev_file = stream_files[1]
        df = pd.read_csv(prev_file)
        
        if 'dt' in df.columns:
            df['dt'] = pd.to_datetime(df['dt'])
            prev_date = df['dt'].max()
            df = df[df['dt'] == prev_date]
        
        # Calculate previous day value by reversing today's daily change
        prev_value = 0.0
        for ticker, weight in tickers_weights.items():
            if weight <= 0:
                continue
            
            current_value = current_stock_values.get(ticker, 0.0)
            if current_value <= 0:
                continue
            
            # Try with and without .NS suffix
            ticker_variants = [ticker, f"{ticker}.NS"]
            ticker_row = df[df['kdcode'].isin(ticker_variants)]
            
            if not ticker_row.empty:
                # Get previous day's daily change
                prev_daily_change = float(ticker_row.iloc[0].get('daily_change', 0.0))
                # Reverse today's change: prev_value = current_value / (1 + daily_change)
                if prev_daily_change != -1.0:  # Avoid division by zero
                    prev_stock_value = current_value / (1 + prev_daily_change)
                    prev_value += prev_stock_value
                else:
                    prev_value += current_value
            else:
                # Fallback: use current value (no change)
                prev_value += current_value
        
        return prev_value if prev_value > 0 else None
    except Exception as e:
        return None


@app.route("/api/v1/user/<user_id>/portfolio", methods=["GET"])
def get_user_portfolio(user_id: str):
    """
    Get portfolio allocation for a user.
    
    Returns:
        JSON with portfolio data if available
    """
    if mongodb_client is None or users_collection is None:
        return jsonify({
            "error": "Database unavailable",
            "message": "MongoDB connection not established"
        }), 503
    
    # Validate userId format
    import re
    if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
        return jsonify({
            "error": "Invalid userId format",
            "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
        }), 400
    
    try:
        user_object_id = ObjectId(user_id)
        user = users_collection.find_one(
            {"_id": user_object_id},
            {"portfolio": 1, "portfolioGeneratedAt": 1, "portfolioDateRange": 1}
        )
        
        if user is None:
            return jsonify({
                "error": "User not found",
                "message": f"User with id {user_id} not found"
            }), 404
        
        portfolio = user.get("portfolio")
        if portfolio is None:
            return jsonify({
                "user_id": user_id,
                "portfolio": None,
                "message": "No portfolio allocated. Complete KYC Verification to generate a portfolio"
            }), 200
        
        # Get invested amount from payload collection
        invested_amount = 0.0
        if payload_store:
            try:
                payload = payload_store.get(user_id)
                if payload and payload.master_json:
                    # Try financial_details.amount_to_invest.value first
                    financial_details = payload.master_json.get("financial_details", {})
                    amount_to_invest_obj = financial_details.get("amount_to_invest", {})
                    if isinstance(amount_to_invest_obj, dict):
                        amount_value = amount_to_invest_obj.get("value")
                        if amount_value:
                            try:
                                invested_amount = float(amount_value)
                            except (ValueError, TypeError):
                                pass
                    
                    # Fallback to questionnaire.additionalDetails.amountToInvest
                    if invested_amount == 0.0:
                        questionnaire = payload.master_json.get("questionnaire", {})
                        if questionnaire:
                            additional_details = questionnaire.get("additionalDetails", {})
                            amount_str = additional_details.get("amountToInvest", "")
                            if amount_str:
                                try:
                                    invested_amount = float(amount_str)
                                except (ValueError, TypeError):
                                    pass
            except Exception as e:
                pass
        
        # Extract portfolio data
        final_weights = portfolio.get("final_weights", {})
        all_weights_data = portfolio.get("all_weights_data", [])
        final_portfolio_value = portfolio.get("final_portfolio_value", 0.0) or 0.0
        
        # Count non-zero allocations
        non_zero_allocations = sum(1 for weight in final_weights.values() if weight > 0.001)
        total_allocations = len(final_weights)
        
        # Calculate unrealized gain/loss
        unrealized_gain_loss = final_portfolio_value - invested_amount
        unrealized_gain_loss_percent = (unrealized_gain_loss / invested_amount * 100) if invested_amount > 0 else 0.0
        
        # Get stream data for current prices and daily changes
        portfolio_tickers = list(final_weights.keys()) if final_weights else []
        stream_data = get_stream_data(tickers=portfolio_tickers)
        
        # Note: We'll check for missing tickers after lookup (which handles .NS suffix removal)
        # So we don't log false positives here
        
        # Calculate stock values and returns using stream data
        # Formula: total value = initial investment * (1 + cumulative daily changes)
        stock_values = {}  # {ticker: current_value}
        stock_initial_investments = {}  # {ticker: initial_investment}
        stock_returns = {}  # {ticker: return_amount}
        stock_returns_percent = {}  # {ticker: return_percent}
        stock_prices = {}  # {ticker: current_price}
        stock_daily_changes = {}  # {ticker: daily_change}
        stock_sectors = {}  # {ticker: sector}
        
        if invested_amount > 0 and final_weights:
            # Get initial weights from all_weights_data if available, otherwise use final_weights
            initial_weights = {}
            if all_weights_data:
                min_step = min((w.get("step", 0) for w in all_weights_data), default=0)
                for w in all_weights_data:
                    if w.get("step") == min_step and w.get("weight", 0) > 0.0001:
                        ticker = w.get("ticker", "")
                        if ticker:
                            initial_weights[ticker] = w.get("weight", 0.0)
            else:
                # Use final weights as initial if no historical data
                initial_weights = final_weights.copy()
            
            # Calculate for each ticker in portfolio
            for ticker, final_weight in final_weights.items():
                if final_weight <= 0.001:
                    continue
                
                # Get initial weight (use final weight if no initial weight found)
                initial_weight = initial_weights.get(ticker, final_weight)
                initial_investment = invested_amount * initial_weight
                stock_initial_investments[ticker] = initial_investment
                
                # Get current price and daily change from stream data
                # Try to find ticker with and without .NS suffix
                # Portfolio tickers have .NS suffix, but stream_data keys don't have .NS
                stream_info = stream_data.get(ticker, {})
                if not stream_info:
                    # Try without .NS suffix if ticker has it
                    if ticker.endswith('.NS'):
                        ticker_without_suffix = ticker.replace('.NS', '')
                        stream_info = stream_data.get(ticker_without_suffix, {})
                    # Also try with .NS suffix if ticker doesn't have it
                    elif '.' not in ticker:
                        ticker_with_suffix = f"{ticker}.NS"
                        stream_info = stream_data.get(ticker_with_suffix, {})
                
                current_price = stream_info.get('price', 0.0)
                daily_change = stream_info.get('daily_change', 0.0)
                sector = stream_info.get('sector', 'Unknown')
                
                stock_prices[ticker] = current_price
                stock_daily_changes[ticker] = daily_change
                stock_sectors[ticker] = sector
                
                # Calculate current value using stream data
                # If we have historical data, use cumulative returns
                if all_weights_data:
                    # Find all steps for this ticker
                    ticker_steps = [
                        w for w in all_weights_data 
                        if w.get("ticker") == ticker and w.get("weight", 0) > 0.0001
                    ]
                    ticker_steps.sort(key=lambda x: x.get("step", 0))
                    
                    # Calculate cumulative value: value = initial * product(1 + daily_return)
                    current_value = initial_investment
                    for step_data in ticker_steps:
                        daily_return = step_data.get("daily_return", 0.0)
                        if daily_return is not None:
                            current_value = current_value * (1 + daily_return)
                    
                    # Apply today's change from stream data
                    if daily_change is not None:
                        current_value = current_value * (1 + daily_change)
                    
                    stock_values[ticker] = current_value
                else:
                    # No historical data: use price ratio method
                    # Find initial price from stream or use a default
                    if current_price > 0:
                        # Estimate initial price: current_price / (1 + cumulative_change)
                        # For simplicity, use final_portfolio_value * weight as current value
                        current_value = final_portfolio_value * final_weight
                    else:
                        current_value = initial_investment
                    
                    stock_values[ticker] = current_value
                
                # Calculate returns
                return_amount = stock_values[ticker] - initial_investment
                stock_returns[ticker] = return_amount
                stock_returns_percent[ticker] = (return_amount / initial_investment * 100) if initial_investment > 0 else 0.0
        
        # Calculate total portfolio value as sum of all stock values
        calculated_total_value = sum(stock_values.values()) if stock_values else final_portfolio_value
        
        # Calculate today's change using previous day portfolio value
        today_change = 0.0
        today_change_percent = 0.0
        
        if calculated_total_value > 0:
            # Try to get previous day value from stream data
            stream_dir = Path(__file__).resolve().parent.parent / "SmartFolio" / "display_data" / "stream"
            prev_day_value = get_previous_day_portfolio_value(
                stream_dir, 
                {t: w for t, w in final_weights.items() if w > 0.001},
                invested_amount,
                stock_values
            )
            
            if prev_day_value and prev_day_value > 0:
                today_change = calculated_total_value - prev_day_value
                today_change_percent = (today_change / prev_day_value * 100) if prev_day_value > 0 else 0.0
            else:
                # Fallback: estimate using daily changes from stream
                portfolio_daily_change = 0.0
                total_weight = 0.0
                for ticker, weight in final_weights.items():
                    if weight > 0.001:
                        daily_change_val = stock_daily_changes.get(ticker, 0.0)
                        portfolio_daily_change += weight * daily_change_val
                        total_weight += weight
                
                if total_weight > 0:
                    portfolio_daily_change = portfolio_daily_change / total_weight
                    today_change = calculated_total_value * portfolio_daily_change
                    today_change_percent = portfolio_daily_change * 100
        
        return jsonify({
            "user_id": user_id,
            "portfolio": portfolio,
            "portfolioGeneratedAt": user.get("portfolioGeneratedAt"),
            "portfolioDateRange": user.get("portfolioDateRange"),
            "available": True,
            "calculated_metrics": {
                "invested_amount": invested_amount,
                "total_portfolio_value": calculated_total_value,
                "unrealized_gain_loss": calculated_total_value - invested_amount,
                "unrealized_gain_loss_percent": ((calculated_total_value - invested_amount) / invested_amount * 100) if invested_amount > 0 else 0.0,
                "today_change": today_change,
                "today_change_percent": today_change_percent,
                "non_zero_allocations": non_zero_allocations,
                "total_allocations": total_allocations,
                "stock_values": stock_values,
                "stock_initial_investments": stock_initial_investments,
                "stock_returns": stock_returns,
                "stock_returns_percent": stock_returns_percent,
                "stock_prices": stock_prices,
                "stock_daily_changes": stock_daily_changes,
                "stock_sectors": stock_sectors,
            }
        }), 200
    
    except Exception as e:
        logger.error(f"Failed to get portfolio for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to retrieve portfolio",
            "message": str(e)
        }), 500


# ============================================================================
# Stock Historical Data API Endpoints
# ============================================================================

@app.route("/api/v1/stock/<ticker>/history", methods=["GET"])
def get_stock_history(ticker: str):
    """
    Get historical stock data for a specific ticker from stream CSV files.
    
    Args:
        ticker: Stock ticker symbol (e.g., "RELIANCE", "ITC.NS")
    
    Returns:
        JSON with historical price data
    """
    try:
        # Normalize ticker (add .NS if not present)
        if '.' not in ticker:
            ticker_with_suffix = f"{ticker}.NS"
        else:
            ticker_with_suffix = ticker
            ticker = ticker.replace('.NS', '')
        
        # Path to stream directory
        display_data_dir = Path(__file__).resolve().parent.parent / "SmartFolio" / "display_data"
        stream_dir = display_data_dir / "stream"
        
        if not stream_dir.exists():
            return jsonify({
                "error": "No display data available",
                "message": "Stream directory not found"
            }), 404
        
        # Get all CSV files in stream directory
        stream_files = sorted(stream_dir.glob("*.csv"))
        
        if not stream_files:
            return jsonify({
                "error": "No display data available",
                "message": "No stream CSV files found"
            }), 404
        
        # Aggregate data from all CSV files
        all_data = []
        sector = "Unknown"
        industry = "Unknown"
        
        for csv_file in stream_files:
            try:
                df = pd.read_csv(csv_file)
                
                if 'kdcode' not in df.columns:
                    continue
                
                # Filter for this ticker
                ticker_rows = df[df['kdcode'] == ticker_with_suffix]
                
                if ticker_rows.empty:
                    continue
                
                # Get the row for this ticker (should be one row per file)
                row = ticker_rows.iloc[0]
                
                # Extract date from filename (format: YYYY-MM-DD.csv)
                file_date = csv_file.stem  # Gets filename without .csv extension
                
                # If dt column exists, use it; otherwise use filename date
                if 'dt' in df.columns:
                    try:
                        date_value = pd.to_datetime(row['dt']).date()
                        file_date = str(date_value)
                    except:
                        pass
                
                # Build data point
                data_point = {
                    'date': file_date,
                    'close': float(row['close']) if 'close' in row and pd.notna(row['close']) else 0.0,
                    'open': float(row['open']) if 'open' in row and pd.notna(row['open']) else 0.0,
                    'high': float(row['high']) if 'high' in row and pd.notna(row['high']) else 0.0,
                    'low': float(row['low']) if 'low' in row and pd.notna(row['low']) else 0.0,
                    'volume': float(row['volume']) if 'volume' in row and pd.notna(row['volume']) else 0.0,
                    'daily_change': float(row['daily_change']) if 'daily_change' in row and pd.notna(row['daily_change']) else 0.0,
                }
                
                all_data.append(data_point)
                
                # Get sector and industry from latest file
                if 'sector' in row and pd.notna(row['sector']):
                    sector = row['sector']
                if 'industry' in row and pd.notna(row['industry']):
                    industry = row['industry']
                    
            except Exception as e:
                logger.error(f"Error reading {csv_file}: {e}", exc_info=True)
                continue
        
        if not all_data:
            return jsonify({
                "error": "Stock not found",
                "message": f"No historical data found for ticker {ticker}"
            }), 404
        
        # Sort by date
        all_data.sort(key=lambda x: x['date'])
        
        # Get latest data for current stats
        latest_data = all_data[-1] if all_data else {}
        
        return jsonify({
            "ticker": ticker,
            "sector": sector,
            "industry": industry,
            "current_price": latest_data.get('close', 0.0),
            "current_change": latest_data.get('daily_change', 0.0),
            "history": all_data
        }), 200
    
    except Exception as e:
        logger.error(f"Failed to get stock history for {ticker}: {e}", exc_info=True)
        return jsonify({
            "error": "Failed to retrieve stock history",
            "message": str(e)
        }), 500


@app.route("/api/v1/stock/<ticker>/xai", methods=["GET"])
def get_stock_xai(ticker: str):
    """
    Get XAI (explainability) report for a specific stock from MongoDB.
    
    Args:
        ticker: Stock ticker symbol (e.g., "RELIANCE", "ITC.NS")
    
    Returns:
        JSON with summary points and markdown content
    """
    try:
        if db is None:
            return jsonify({
                "error": "Database not available",
                "message": "MongoDB connection not established"
            }), 500
        
        # Normalize ticker (add .NS if not present)
        if '.' not in ticker:
            ticker_with_suffix = f"{ticker}.NS"
        else:
            ticker_with_suffix = ticker
            ticker = ticker.replace('.NS', '')
        
        # Query MongoDB for latest stock report
        stock_reports_collection = db.smartfolio_xai_stock_reports
        
        # Get the latest report for this ticker
        latest_report = stock_reports_collection.find_one(
            {"ticker": ticker_with_suffix},
            sort=[("created_at", -1)]
        )
        
        if not latest_report:
            return jsonify({
                "ticker": ticker,
                "summary_points": [],
                "markdown": None,
                "available": False
            }), 200
        
        # Extract all summary points (don't limit)
        summary_points = latest_report.get("summary_points", [])
        if not isinstance(summary_points, list):
            summary_points = []
        
        # Extract markdown content (can be used for full report)
        markdown = latest_report.get("markdown")
        
        return jsonify({
            "ticker": ticker,
            "summary_points": summary_points,
            "markdown": markdown,
            "as_of": latest_report.get("as_of"),
            "weight": latest_report.get("weight"),
            "llm_used": latest_report.get("llm_used", False),
            "run_date": latest_report.get("run_date"),
            "available": True
        }), 200
    
    except Exception as e:
        logger.error(f"Failed to get stock XAI for {ticker}: {e}", exc_info=True)
        return jsonify({
            "error": "Failed to retrieve stock XAI",
            "message": str(e)
        }), 500


# ============================================================================
# KYC Report API Endpoints
# ============================================================================

@app.route("/api/v1/user/<user_id>/fetchKYCreport", methods=["GET"])
def fetch_kyc_report(user_id: str):
    """
    Fetch KYC report for a user from orchestration results.
    
    Returns:
        JSON with KYC report data if available
    """
    if payload_store is None:
        return jsonify({
            "error": "Payload store not available",
            "message": "MongoDB payload storage not initialized"
        }), 503
    
    # Validate userId format
    import re
    if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
        return jsonify({
            "error": "Invalid userId format",
            "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
        }), 400
    
    try:
        payload = payload_store.get(user_id)
        if payload is None:
            return jsonify({
                "user_id": user_id,
                "report": None,
                "message": "No payload found for user"
            }), 200
        
        # Extract KYC report and master_json from payload
        orchestration_result = payload.metadata.get("orchestration_result", {})
        kyc_report = orchestration_result.get("kycv_report")
        master_json = payload.master_json if hasattr(payload, 'master_json') else None
        
        # Get validation status (image/video verification result: "passed" or "failed")
        validation_status = "pending"
        if mongodb_client is not None and users_collection is not None:
            try:
                user_object_id = ObjectId(user_id)
                user = users_collection.find_one(
                    {"_id": user_object_id},
                    {"validationStatus": 1, "kycApprovalStatus": 1}
                )
                if user:
                    validation_status = user.get("validationStatus", "pending")
                    # If validation_status not set, calculate from master_json
                    if validation_status == "pending" and master_json:
                        verification_status = master_json.get("verification_status", {})
                        overall_verified = verification_status.get("overall_status", False)
                        validation_status = "passed" if overall_verified else "failed"
            except Exception as e:
                pass
        
        # Get KYC approval status (admin approval/rejection)
        kyc_approval_status = "pending"
        if mongodb_client is not None and users_collection is not None:
            try:
                user_object_id = ObjectId(user_id)
                user = users_collection.find_one(
                    {"_id": user_object_id},
                    {"kycApprovalStatus": 1}
                )
                if user:
                    kyc_approval_status = user.get("kycApprovalStatus", "pending")
            except Exception as e:
                pass
        
        # Determine KYC status for user frontend based on admin approval/rejection
        if kyc_approval_status in ["pending", "review"]:
            kyc_status = "IN REVIEW"
        elif kyc_approval_status == "approved":
            kyc_status = "VERIFIED"
        elif kyc_approval_status == "rejected":
            kyc_status = "REJECTED"
        else:
            # Default to IN REVIEW if validation completed but not yet reviewed by admin
            if kyc_report:
                kyc_status = "IN REVIEW"
            else:
                kyc_status = "PENDING"
        
        if kyc_report is None and master_json is None:
            return jsonify({
                "user_id": user_id,
                "report": None,
                "master_json": None,
                "message": "KYC report not yet generated",
                "kyc_status": kyc_status,
                "validation_status": validation_status
            }), 200
        
        return jsonify({
            "user_id": user_id,
            "report": kyc_report,
            "master_json": master_json,
            "available": True,
            "generated_at": orchestration_result.get("completed_at"),
            "kyc_status": kyc_status,  # Admin approval/rejection status
            "validation_status": validation_status,  # Image/video verification result (passed/failed)
            "kyc_approval_status": kyc_approval_status  # Admin approval/rejection status
        }), 200
    except Exception as e:
        logger.error(f"Failed to fetch KYC report for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to retrieve KYC report",
            "message": str(e)
        }), 500


# ============================================================================
# Admin KYC Verification API Endpoints
# ============================================================================

@app.route("/api/v1/admin/users", methods=["GET"])
def get_all_users():
    """
    Get all users with their KYC status for admin dashboard.
    
    Returns:
        JSON array of users with KYC status and validation status
    """
    try:
        if mongodb_client is None or users_collection is None:
            return jsonify({
                "error": "Database unavailable",
                "message": "MongoDB connection not established"
            }), 503
        
        if payload_store is None:
            return jsonify({
                "error": "Payload store not available",
                "message": "MongoDB payload storage not initialized"
            }), 503
        
        # Get all users
        users = list(users_collection.find({}, {"password": 0}))  # Exclude passwords
        
        # Enrich with KYC status from payloads
        users_with_kyc = []
        for user in users:
            user_id = str(user["_id"])
            
            # Get KYC status from payload
            payload = payload_store.get(user_id) if payload_store else None
            
            # Determine KYC status
            if payload is None:
                kyc_status = "Pending"
            elif payload.status == "completed":
                # Check if there's a report
                orchestration_result = payload.metadata.get("orchestration_result", {})
                if orchestration_result.get("kycv_report"):
                    kyc_status = "Submitted"
                else:
                    kyc_status = "Pending"
            elif payload.status == "processing":
                kyc_status = "Pending"
            else:
                kyc_status = "Pending"
            
            # Get validation status (image/video verification result: "passed" or "failed")
            validation_status = user.get("validationStatus", "pending")
            
            # Calculate validation status from verification results if not set
            if validation_status == "pending" and payload and payload.master_json:
                verification_status = payload.master_json.get("verification_status", {})
                overall_verified = verification_status.get("overall_status", False)
                validation_status = "passed" if overall_verified else "failed"
            
            # Get KYC approval status (admin approval/rejection: "pending", "review", "approved", "rejected")
            kyc_approval_status = user.get("kycApprovalStatus", "pending")
            
            # Determine KYC status based on admin approval/rejection
            if kyc_approval_status == "review" or kyc_approval_status == "pending":
                # If validation has completed, show IN REVIEW (waiting for admin)
                if payload and payload.status == "completed":
                    kyc_status = "IN REVIEW"
                # Otherwise keep the kyc_status from payload status (Pending/Processing)
            elif kyc_approval_status == "approved":
                kyc_status = "Verified"
            elif kyc_approval_status == "rejected":
                kyc_status = "Rejected"
            # Otherwise keep the kyc_status from payload status
            
            # Check which documents are available
            documents = {
                "aadhaar": False,
                "pan": False,
                "itr": False,
                "video": False
            }
            
            if payload and payload.master_json:
                master_json = payload.master_json
                # Check for document references in master_json
                if master_json.get("aadhaar") or master_json.get("aadhaar_number"):
                    documents["aadhaar"] = True
                if master_json.get("pan") or master_json.get("pan_number"):
                    documents["pan"] = True
                if master_json.get("itr") or master_json.get("income_tax_return"):
                    documents["itr"] = True
                if master_json.get("video") or master_json.get("video_url"):
                    documents["video"] = True
            
            # Check questionnaire data for documents
            questionnaire = user.get("questionnaire", {})
            if questionnaire:
                if questionnaire.get("documents", {}).get("aadhaar"):
                    documents["aadhaar"] = True
                if questionnaire.get("documents", {}).get("pan"):
                    documents["pan"] = True
                if questionnaire.get("documents", {}).get("itr"):
                    documents["itr"] = True
                if questionnaire.get("videoCloudinaryUrl"):
                    documents["video"] = True
            
            users_with_kyc.append({
                "id": user_id,
                "name": user.get("name", ""),
                "email": user.get("email", ""),
                "kycStatus": kyc_status,  # Admin approval/rejection status
                "validationStatus": validation_status,  # Image/video verification result (passed/failed)
                "documents": documents,
                "createdAt": user.get("createdAt").isoformat() if user.get("createdAt") else None,
                "updatedAt": user.get("updatedAt").isoformat() if user.get("updatedAt") else None
            })
        
        return jsonify({
            "success": True,
            "users": users_with_kyc,
            "total": len(users_with_kyc)
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get all users: {e}")
        return jsonify({
            "error": "Failed to retrieve users",
            "message": str(e)
        }), 500


@app.route("/api/v1/admin/users/<user_id>", methods=["GET"])
def get_user_details(user_id: str):
    """
    Get detailed user information for KYC review.
    
    Returns:
        JSON with user details, questionnaire data, and KYC report
    """
    try:
        if mongodb_client is None or users_collection is None:
            return jsonify({
                "error": "Database unavailable",
                "message": "MongoDB connection not established"
            }), 503
        
        if payload_store is None:
            return jsonify({
                "error": "Payload store not available",
                "message": "MongoDB payload storage not initialized"
            }), 503
        
        # Validate userId format
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
            }), 400
        
        # Get user from MongoDB
        try:
            user_object_id = ObjectId(user_id)
            user = users_collection.find_one({"_id": user_object_id}, {"password": 0})
        except Exception:
            return jsonify({
                "error": "Invalid userId",
                "message": "userId must be a valid MongoDB ObjectId"
            }), 400
        
        if not user:
            return jsonify({
                "error": "User not found",
                "message": f"User with id {user_id} not found"
            }), 404
        
        # Get KYC payload
        payload = payload_store.get(user_id)
        
        # Get questionnaire data
        questionnaire = user.get("questionnaire", {})
        
        # Extract personal information
        personal_info = questionnaire.get("personalInformation", {})
        address_info = questionnaire.get("addressInformation", {})
        additional_details = questionnaire.get("additionalDetails", {})
        investment_profile = questionnaire.get("investmentProfile", {})
        
        # Extract documents info
        documents_data = questionnaire.get("documents", {})
        document_urls = questionnaire.get("documentUrls", {})  # Cloudinary URLs
        video_url = questionnaire.get("videoCloudinaryUrl", "") or questionnaire.get("video", {}).get("cloudinaryUrl", "")
        
        # Get validation status (image/video verification result: "passed" or "failed")
        validation_status = user.get("validationStatus", "pending")
        # Calculate from payload if not set
        if validation_status == "pending" and payload and payload.master_json:
            verification_status = payload.master_json.get("verification_status", {})
            overall_verified = verification_status.get("overall_status", False)
            validation_status = "passed" if overall_verified else "failed"
        
        # Get KYC approval status (admin approval/rejection)
        kyc_approval_status = user.get("kycApprovalStatus", "pending")
        
        # Determine KYC status based on admin approval/rejection
        if kyc_approval_status == "review" or kyc_approval_status == "pending":
            kyc_status = "IN REVIEW" if (payload and payload.status == "completed") else "Pending"
        elif kyc_approval_status == "approved":
            kyc_status = "Verified"
        elif kyc_approval_status == "rejected":
            kyc_status = "Rejected"
        else:
            kyc_status = "Pending"
        
        # Build response
        response = {
            "id": user_id,
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "kycStatus": kyc_status,  # Admin approval/rejection status
            "validationStatus": validation_status,  # Image/video verification result (passed/failed)
            "kycApprovalStatus": kyc_approval_status,  # Admin approval/rejection status
            "dateOfBirth": personal_info.get("dateOfBirth", ""),
            "contactNumber": personal_info.get("contactNumber", ""),
            "address": f"{address_info.get('addressLine1', '')}, {address_info.get('addressLine2', '')}, {address_info.get('city', '')}, {address_info.get('state', '')} - {address_info.get('pinCode', '')}".strip(", "),
            "occupation": additional_details.get("occupation", ""),
            "maritalStatus": additional_details.get("maritalStatus", ""),
            "citizenship": additional_details.get("citizenship", ""),
            "incomeRange": additional_details.get("incomeRange", ""),
            "amountToInvest": additional_details.get("amountToInvest", ""),
            "dependents": additional_details.get("dependents", 0),
            "dependentDetails": additional_details.get("dependentDetails", ""),
            "documents": {
                "aadhaar": bool(documents_data.get("aadhaar")),
                "pan": bool(documents_data.get("pan")),
                "itr": bool(documents_data.get("itr")),
                "video": bool(video_url)
            },
            "documentUrls": {
                "aadhaar": document_urls.get("aadhaar") or documents_data.get("aadhaar", {}).get("cloudinaryUrl"),
                "pan": document_urls.get("pan") or documents_data.get("pan", {}).get("cloudinaryUrl"),
                "itr": document_urls.get("itr") or documents_data.get("itr", {}).get("cloudinaryUrl"),
                "video": video_url
            },
            "videoCloudinaryUrl": video_url,
            "investmentQ1": investment_profile.get("investmentGoals", ""),
            "investmentQ2": investment_profile.get("investmentHorizon", ""),
            "investmentQ3": investment_profile.get("riskTolerance", ""),
            "investmentQ4": investment_profile.get("investmentExperience", ""),
            "investmentQ5": investment_profile.get("investmentStrategy", ""),
            "investmentQ6": investment_profile.get("investmentFrequency", "")
        }
        
        # Add KYC status - prioritize validationStatus from user document
        # If validationStatus is "pending" or "review", show "IN REVIEW" regardless of validation result
        # Only show final status when admin has approved/rejected
        if validation_status == "review" or validation_status == "pending":
            # Check if validation has completed - if yes, show IN REVIEW (waiting for admin)
            if payload and payload.status == "completed":
                response["kycStatus"] = "IN REVIEW"
            else:
                response["kycStatus"] = "Pending"
        elif validation_status == "approved":
            response["kycStatus"] = "Verified"
        elif validation_status == "rejected":
            response["kycStatus"] = "Rejected"
        elif payload:
            # Fallback to payload status if validationStatus not set
            if payload.status == "completed":
                orchestration_result = payload.metadata.get("orchestration_result", {})
                if orchestration_result.get("kycv_report"):
                    # Validation completed but not yet reviewed by admin - show IN REVIEW
                    response["kycStatus"] = "IN REVIEW"
                else:
                    response["kycStatus"] = "Pending"
            elif payload.status == "processing":
                response["kycStatus"] = "Pending"
        
        # Add master_json if available (for document access)
        if payload and payload.master_json:
            response["master_json"] = payload.master_json
        
        return jsonify({
            "success": True,
            "user": response
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get user details for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to retrieve user details",
            "message": str(e)
        }), 500


@app.route("/api/v1/admin/users/<user_id>/approve", methods=["POST"])
def approve_kyc(user_id: str):
    """
    Approve user KYC verification and trigger portfolio allocation.
    
    Returns:
        JSON confirmation
    """
    try:
        if mongodb_client is None or users_collection is None:
            return jsonify({
                "error": "Database unavailable",
                "message": "MongoDB connection not established"
            }), 503
        
        # Validate userId format
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
            }), 400
        
        # Get request data (optional: reason, notes, etc.)
        data = request.get_json() or {}
        admin_notes = data.get("notes", "")
        
        # Update user document
        try:
            user_object_id = ObjectId(user_id)
            approval_time = datetime.utcnow()
            result = users_collection.update_one(
                {"_id": user_object_id},
                    {
                        "$set": {
                            "kycApprovalStatus": "approved",  # Separate field for admin approval
                            "kycApprovedAt": approval_time,
                            "kycApprovedBy": "admin",  # TODO: Get actual admin ID from session
                            "kycAdminNotes": admin_notes,
                            "updatedAt": approval_time
                        }
                    }
            )
        except Exception:
            return jsonify({
                "error": "Invalid userId",
                "message": "userId must be a valid MongoDB ObjectId"
            }), 400
        
        if result.matched_count == 0:
            return jsonify({
                "error": "User not found",
                "message": f"User with id {user_id} not found"
            }), 404
        
        # Trigger portfolio allocation after approval
        try:
            from flask_server.orchestration_helper import (
                get_user_risk_score_from_payload,
                trigger_portfolio_allocation
            )
            
            # Get user risk score from payload
            risk_score = get_user_risk_score_from_payload(user_id, payload_store)
            
            if risk_score is not None:
                
                # Get portfolio API URL from environment
                portfolio_api_url = os.environ.get(
                    "PORTFOLIO_API_URL",
                    "http://localhost:8000"
                )
                
                # Trigger portfolio allocation with approval date as reference
                portfolio_result = trigger_portfolio_allocation(
                    risk_score=risk_score,
                    user_id=user_id,
                    api_url=portfolio_api_url,
                    reference_date=approval_time,
                )
                
                if portfolio_result:
                    # Save portfolio to user document
                    try:
                        # Calculate dates for reference
                        from flask_server.orchestration_helper import calculate_sliding_window_dates
                        start_date, end_date = calculate_sliding_window_dates(approval_time)
                        
                        # Extract actual ticker names from all_weights_data if final_weights has "stock_X" keys
                        final_weights = portfolio_result.get("final_weights", {})
                        all_weights_data = portfolio_result.get("all_weights_data", [])
                        
                        # Check if final_weights has "stock_X" keys and we have all_weights_data
                        if final_weights and all_weights_data:
                            has_stock_keys = any(k.startswith("stock_") for k in final_weights.keys())
                            if has_stock_keys:
                                # Extract final step's ticker names from all_weights_data
                                # Find the maximum step value
                                max_step = max((w.get("step", 0) for w in all_weights_data), default=0)
                                # Create a mapping from stock index to actual ticker name
                                final_step_data = [w for w in all_weights_data if w.get("step") == max_step]
                                
                                # Create a new final_weights dict with actual ticker names
                                new_final_weights = {}
                                for w in final_step_data:
                                    ticker = w.get("ticker", "")
                                    weight = w.get("weight", 0)
                                    if weight > 0.0001 and ticker:
                                        # Use actual ticker name if available, otherwise keep stock_X
                                        new_final_weights[ticker] = weight
                                
                                # Replace final_weights if we found actual ticker names
                                if new_final_weights and any(not k.startswith("stock_") for k in new_final_weights.keys()):
                                    portfolio_result["final_weights"] = new_final_weights
                        
                        portfolio_doc = {
                            "portfolio": portfolio_result,
                            "portfolioGeneratedAt": datetime.utcnow(),
                            "portfolioDateRange": {
                                "start": start_date,
                                "end": end_date,
                            },
                            "updatedAt": datetime.utcnow()
                        }
                        
                        users_collection.update_one(
                            {"_id": user_object_id},
                            {"$set": portfolio_doc}
                        )
                    except Exception as save_error:
                        logger.error(f"[APPROVAL] Failed to save portfolio to user DB: {save_error}", exc_info=True)
                else:
                    pass
            else:
                pass
        
        except Exception as portfolio_error:
            # Don't fail approval if portfolio allocation fails
            logger.error(f"[APPROVAL] Portfolio allocation error (non-fatal): {portfolio_error}", exc_info=True)
        
        return jsonify({
            "success": True,
            "message": "KYC approved successfully",
            "user_id": user_id,
            "kycApprovalStatus": "approved"
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to approve KYC for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to approve KYC",
            "message": str(e)
        }), 500


@app.route("/api/v1/admin/users/<user_id>/reject", methods=["POST"])
def reject_kyc(user_id: str):
    """
    Reject user KYC verification.
    
    Expects JSON body (optional):
    {
        "reason": "Reason for rejection",
        "notes": "Additional notes"
    }
    
    Returns:
        JSON confirmation
    """
    try:
        if mongodb_client is None or users_collection is None:
            return jsonify({
                "error": "Database unavailable",
                "message": "MongoDB connection not established"
            }), 503
        
        # Validate userId format
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
            }), 400
        
        # Get request data
        data = request.get_json() or {}
        rejection_reason = data.get("reason", "")
        admin_notes = data.get("notes", "")
        
        # Update user document
        try:
            user_object_id = ObjectId(user_id)
            result = users_collection.update_one(
                {"_id": user_object_id},
                    {
                        "$set": {
                            "kycApprovalStatus": "rejected",  # Separate field for admin rejection
                            "kycRejectedAt": datetime.utcnow(),
                            "kycRejectedBy": "admin",  # TODO: Get actual admin ID from session
                            "kycRejectionReason": rejection_reason,
                            "kycAdminNotes": admin_notes,
                            "updatedAt": datetime.utcnow()
                        }
                    }
            )
        except Exception:
            return jsonify({
                "error": "Invalid userId",
                "message": "userId must be a valid MongoDB ObjectId"
            }), 400
        
        if result.matched_count == 0:
            return jsonify({
                "error": "User not found",
                "message": f"User with id {user_id} not found"
            }), 404
        
        return jsonify({
            "success": True,
            "message": "KYC rejected successfully",
            "user_id": user_id,
            "kycApprovalStatus": "rejected"
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to reject KYC for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to reject KYC",
            "message": str(e)
        }), 500


@app.route("/api/v1/admin/users/<user_id>/documents", methods=["GET"])
def get_user_documents(user_id: str):
    """
    Get user documents for KYC review.
    
    Query params:
    - type: Optional document type filter (aadhaar, pan, itr, video)
    
    Returns:
        JSON with document URLs or base64 data
    """
    try:
        if mongodb_client is None or users_collection is None:
            return jsonify({
                "error": "Database unavailable",
                "message": "MongoDB connection not established"
            }), 503
        
        if payload_store is None:
            return jsonify({
                "error": "Payload store not available",
                "message": "MongoDB payload storage not initialized"
            }), 503
        
        # Validate userId format
        import re
        if not re.match(r'^[0-9a-fA-F]{24}$', user_id):
            return jsonify({
                "error": "Invalid userId format",
                "message": "userId must be a valid MongoDB ObjectId (24 hex characters)"
            }), 400
        
        # Get document type filter
        doc_type = request.args.get("type", "").lower()
        
        # Get user
        try:
            user_object_id = ObjectId(user_id)
            user = users_collection.find_one({"_id": user_object_id}, {"password": 0})
        except Exception:
            return jsonify({
                "error": "Invalid userId",
                "message": "userId must be a valid MongoDB ObjectId"
            }), 400
        
        if not user:
            return jsonify({
                "error": "User not found",
                "message": f"User with id {user_id} not found"
            }), 404
        
        # Get questionnaire documents
        questionnaire = user.get("questionnaire", {})
        documents_data = questionnaire.get("documents", {})
        document_urls = questionnaire.get("documentUrls", {})  # Cloudinary URLs
        video_url = questionnaire.get("videoCloudinaryUrl", "") or questionnaire.get("video", {}).get("cloudinaryUrl", "")
        
        # Get payload for master_json documents
        payload = payload_store.get(user_id)
        master_json = payload.master_json if payload else {}
        
        # Build documents response
        documents = {}
        
        if not doc_type or doc_type == "aadhaar":
            aadhaar_url = document_urls.get("aadhaar") or documents_data.get("aadhaar", {}).get("cloudinaryUrl")
            aadhaar_doc = documents_data.get("aadhaar")
            if aadhaar_url:
                documents["aadhaar"] = {
                    "available": True,
                    "url": aadhaar_url,
                    "filename": aadhaar_doc.get("filename", "aadhaar.pdf") if aadhaar_doc else "aadhaar.pdf",
                    "mime_type": aadhaar_doc.get("mime_type", "application/pdf") if aadhaar_doc else "application/pdf",
                    "type": "cloudinary"
                }
            elif aadhaar_doc:
                documents["aadhaar"] = {
                    "available": True,
                    "filename": aadhaar_doc.get("filename", "aadhaar.pdf"),
                    "note": "Document stored but Cloudinary URL not available"
                }
            elif master_json.get("aadhaar") or master_json.get("aadhaar_number"):
                documents["aadhaar"] = {
                    "available": True,
                    "note": "Document available in master_json"
                }
        
        if not doc_type or doc_type == "pan":
            pan_url = document_urls.get("pan") or documents_data.get("pan", {}).get("cloudinaryUrl")
            pan_doc = documents_data.get("pan")
            if pan_url:
                documents["pan"] = {
                    "available": True,
                    "url": pan_url,
                    "filename": pan_doc.get("filename", "pan.pdf") if pan_doc else "pan.pdf",
                    "mime_type": pan_doc.get("mime_type", "application/pdf") if pan_doc else "application/pdf",
                    "type": "cloudinary"
                }
            elif pan_doc:
                documents["pan"] = {
                    "available": True,
                    "filename": pan_doc.get("filename", "pan.pdf"),
                    "note": "Document stored but Cloudinary URL not available"
                }
            elif master_json.get("pan") or master_json.get("pan_number"):
                documents["pan"] = {
                    "available": True,
                    "note": "Document available in master_json"
                }
        
        if not doc_type or doc_type == "itr":
            itr_url = document_urls.get("itr") or documents_data.get("itr", {}).get("cloudinaryUrl")
            itr_doc = documents_data.get("itr")
            if itr_url:
                documents["itr"] = {
                    "available": True,
                    "url": itr_url,
                    "filename": itr_doc.get("filename", "itr.pdf") if itr_doc else "itr.pdf",
                    "mime_type": itr_doc.get("mime_type", "application/pdf") if itr_doc else "application/pdf",
                    "type": "cloudinary"
                }
            elif itr_doc:
                documents["itr"] = {
                    "available": True,
                    "filename": itr_doc.get("filename", "itr.pdf"),
                    "note": "Document stored but Cloudinary URL not available"
                }
            elif master_json.get("itr") or master_json.get("income_tax_return"):
                documents["itr"] = {
                    "available": True,
                    "note": "Document available in master_json"
                }
        
        if not doc_type or doc_type == "video":
            if video_url:
                documents["video"] = {
                    "available": True,
                    "url": video_url,
                    "type": "video"
                }
            elif master_json.get("video") or master_json.get("video_url"):
                documents["video"] = {
                    "available": True,
                    "note": "Video available in master_json"
                }
        
        return jsonify({
            "success": True,
            "user_id": user_id,
            "documents": documents
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get documents for user_id={user_id}: {e}")
        return jsonify({
            "error": "Failed to retrieve documents",
            "message": str(e)
        }), 500


# =============================================================================
# Monthly Batch Processing Endpoints
# =============================================================================

@app.route("/api/v1/finrag/batch-process-monthly", methods=["POST"])
def batch_process_monthly():
    """
    Run monthly batch scoring for all stocks and save to MongoDB.
    Should be called on 27th of every month.
    """
    try:
        import time
        start_time = time.time()
        
        # Check if already run this month
        today = datetime.utcnow()
        year_month = today.strftime("%Y-%m")
        batch_date = today.strftime("%Y-%m-%d")
        
        if db is None:
            return jsonify({
                "error": "Database not available",
                "message": "MongoDB connection not established"
            }), 500
        
        batch_scores_collection = db.finrag_batch_scores
        
        # Check if already run this month (unless force_run)
        force_run = request.json.get("force_run", False) if request.is_json else False
        existing_batch = batch_scores_collection.find_one({"year_month": year_month})
        
        if existing_batch and not force_run:
            return jsonify({
                "error": "Batch already processed",
                "message": f"Batch processing already completed for {year_month}",
                "existing_batch_id": str(existing_batch["_id"]),
                "batch_date": existing_batch.get("batch_date")
            }), 400
        
        # Call FinRAG MCP API
        finrag_api_url = os.environ.get("FINRAG_MCP_API_URL", "http://localhost:8003")
        api_url = f"{finrag_api_url}/batch_score_all"
        
        try:
            response = requests.post(
                api_url,
                params={"save_output": True, "output_file": f"batch_scores_{batch_date}.json"},
                timeout=3600  # 1 hour timeout for batch processing
            )
            response.raise_for_status()
            batch_result = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"FinRAG API request failed: {e}")
            return jsonify({
                "error": "FinRAG API request failed",
                "message": str(e)
            }), 500
        
        # Save to MongoDB
        processing_time = time.time() - start_time
        
        batch_doc = {
            "batch_date": batch_date,
            "year_month": year_month,
            "timestamp": batch_result.get("timestamp", datetime.utcnow().isoformat()),
            "created_at": datetime.utcnow(),
            "summary": batch_result.get("summary", {}),
            "results": batch_result.get("results", []),
            "metadata": {
                "finrag_version": "1.0.0",
                "api_endpoint": "/batch_score_all",
                "processing_time_seconds": processing_time
            }
        }
        
        result = batch_scores_collection.insert_one(batch_doc)
        
        return jsonify({
            "success": True,
            "message": "Batch processing completed",
            "batch_date": batch_date,
            "year_month": year_month,
            "total_stocks_scored": len(batch_result.get("results", [])),
            "mongodb_id": str(result.inserted_id),
            "processing_time_seconds": processing_time
        }), 200
        
    except Exception as e:
        logger.error(f"Batch processing error: {e}", exc_info=True)
        return jsonify({
            "error": "Batch processing failed",
            "message": str(e)
        }), 500


@app.route("/api/v1/smartfolio/finetune-monthly", methods=["POST"])
def finetune_monthly():
    """
    Run monthly fine-tuning for SmartFolio model.
    Should be called on 1st of every month.
    Uses the latest batch scores from previous month.
    """
    try:
        import time
        start_time = time.time()
        
        if db is None:
            return jsonify({
                "error": "Database not available",
                "message": "MongoDB connection not established"
            }), 500
        
        # Get request parameters
        request_data = request.json if request.is_json else {}
        risk_score = request_data.get("risk_score", 0.5)
        finetune_month = request_data.get("finetune_month")
        use_latest_batch = request_data.get("use_latest_batch", True)
        
        # Determine finetune_month (default to previous month)
        if not finetune_month:
            today = datetime.utcnow()
            # If today is 1st, fine-tune previous month
            if today.day == 1:
                prev_month = today.replace(day=1) - timedelta(days=1)
                finetune_month = prev_month.strftime("%Y-%m")
            else:
                finetune_month = today.strftime("%Y-%m")
        
        finetune_date = datetime.utcnow().strftime("%Y-%m-%d")
        
        # Get latest batch scores if requested
        batch_scores_collection = db.finrag_batch_scores
        finetune_runs_collection = db.smartfolio_finetune_runs
        
        batch_scores_doc = None
        if use_latest_batch:
            # Find batch scores for the month being fine-tuned
            batch_scores_doc = batch_scores_collection.find_one(
                {"year_month": finetune_month},
                sort=[("created_at", -1)]
            )
            
            if not batch_scores_doc:
                return jsonify({
                    "error": "Batch scores not found",
                    "message": f"No batch scores found for {finetune_month}. Run batch processing first."
                }), 404
        
        # Call SmartFolio API
        smartfolio_api_url = os.environ.get("SMARTFOLIO_API_URL", "http://localhost:8001")
        api_url = f"{smartfolio_api_url}/finetune"
        
        finetune_request = {
            "save_dir": "./checkpoints",
            "device": "cpu",
            "run_monthly_fine_tune": True,
            "market": "custom",
            "horizon": "1",
            "relation_type": "hy",
            "fine_tune_steps": 1,
            "risk_score": risk_score,
            "finetune_month": finetune_month,
            "ptr_mode": True,
            "use_ptr": True,
            "ptr_coef": 0.3,
            "ptr_memory_size": 1000,
            "ptr_priority_type": "max",
            "batch_size": 16,
            "n_steps": 2048,
            "promotion_min_sharpe": 0.5,
            "promotion_max_drawdown": 0.2
        }
        
        try:
            response = requests.post(
                api_url,
                json=finetune_request,
                timeout=7200  # 2 hour timeout for fine-tuning
            )
            response.raise_for_status()
            finetune_result = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"SmartFolio API request failed: {e}")
            return jsonify({
                "error": "SmartFolio API request failed",
                "message": str(e)
            }), 500
        
        # Save to MongoDB
        processing_time = time.time() - start_time
        
        finetune_doc = {
            "finetune_date": finetune_date,
            "finetune_month": finetune_month,
            "created_at": datetime.utcnow(),
            "checkpoint_path": finetune_result.get("checkpoint_path", ""),
            "risk_score": risk_score,
            "batch_scores_used": {
                "batch_date": batch_scores_doc.get("batch_date") if batch_scores_doc else None,
                "mongodb_id": str(batch_scores_doc["_id"]) if batch_scores_doc else None,
                "year_month": batch_scores_doc.get("year_month") if batch_scores_doc else None
            } if batch_scores_doc else None,
            "metrics": finetune_result.get("metrics", {}),
            "status": "completed",
            "error_message": None,
            "processing_time_seconds": processing_time
        }
        
        result = finetune_runs_collection.insert_one(finetune_doc)
        
        return jsonify({
            "success": True,
            "message": "Fine-tuning completed",
            "checkpoint_path": finetune_result.get("checkpoint_path", ""),
            "finetune_month": finetune_month,
            "batch_scores_used": {
                "batch_date": batch_scores_doc.get("batch_date") if batch_scores_doc else None,
                "mongodb_id": str(batch_scores_doc["_id"]) if batch_scores_doc else None
            } if batch_scores_doc else None,
            "metrics": finetune_result.get("metrics", {}),
            "mongodb_id": str(result.inserted_id),
            "processing_time_seconds": processing_time
        }), 200
        
    except Exception as e:
        logger.error(f"Fine-tuning error: {e}", exc_info=True)
        
        # Save failed run to MongoDB
        if db is not None:
            try:
                finetune_runs_collection = db.smartfolio_finetune_runs
                finetune_doc = {
                    "finetune_date": datetime.utcnow().strftime("%Y-%m-%d"),
                    "finetune_month": finetune_month if 'finetune_month' in locals() else None,
                    "created_at": datetime.utcnow(),
                    "status": "failed",
                    "error_message": str(e),
                    "processing_time_seconds": time.time() - start_time if 'start_time' in locals() else 0
                }
                finetune_runs_collection.insert_one(finetune_doc)
            except:
                pass
        
        return jsonify({
            "error": "Fine-tuning failed",
            "message": str(e)
        }), 500


@app.route("/api/v1/smartfolio/xai-monthly", methods=["POST"])
def xai_monthly():
    """
    Run monthly XAI (Explainability) analysis for all stocks and save to MongoDB.
    Should be called on 2nd of every month.
    """
    try:
        import time
        start_time = time.time()
        
        # Check if already run this month
        today = datetime.utcnow()
        year_month = today.strftime("%Y-%m")
        run_date = today.strftime("%Y-%m-%d")
        
        if db is None:
            return jsonify({
                "error": "Database not available",
                "message": "MongoDB connection not established"
            }), 500
        
        xai_runs_collection = db.smartfolio_xai_runs
        
        # Check if already run this month (unless force_run)
        force_run = request.json.get("force_run", False) if request.is_json else False
        existing_run = xai_runs_collection.find_one({"year_month": year_month})
        
        if existing_run and not force_run:
            return jsonify({
                "error": "XAI already processed",
                "message": f"XAI analysis already completed for {year_month}",
                "existing_run_id": str(existing_run["_id"]),
                "run_date": existing_run.get("run_date")
            }), 400
        
        # Get configuration from request or use defaults
        request_data = request.json if request.is_json else {}
        
        # Find latest monthly log CSV (from SmartFolio logs)
        smartfolio_root = Path(__file__).resolve().parent.parent / "SmartFolio"
        monthly_log_csv = request_data.get("monthly_log_csv")
        if not monthly_log_csv:
            # Find latest monthly log CSV
            logs_dir = smartfolio_root / "logs" / "monthly"
            if logs_dir.exists():
                monthly_dirs = sorted([d for d in logs_dir.iterdir() if d.is_dir()], reverse=True)
                if monthly_dirs:
                    latest_month_dir = monthly_dirs[0]
                    # Find final_test_weights CSV files, but exclude summary files
                    all_csv_files = list(latest_month_dir.glob("final_test_weights_*.csv"))
                    # Filter out summary files (they don't have date column)
                    csv_files = [f for f in all_csv_files if "summary" not in f.name.lower()]
                    if csv_files:
                        csv_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                        monthly_log_csv = str(csv_files[0])
        
        if not monthly_log_csv or not Path(monthly_log_csv).exists():
            return jsonify({
                "error": "Monthly log CSV not found",
                "message": f"Could not find monthly log CSV. Please provide monthly_log_csv path."
            }), 400
        
        # Convert to absolute path to ensure it resolves correctly
        monthly_log_csv = str(Path(monthly_log_csv).resolve())
        
        # Get the latest date from the CSV (use that instead of today's date)
        # This ensures we use a date that actually exists in the CSV
        try:
            df_check = pd.read_csv(monthly_log_csv)
            df_check.columns = [str(col).strip().lower() for col in df_check.columns]
            
            # Validate CSV has required columns
            if 'date' not in df_check.columns:
                return jsonify({
                    "error": "Invalid CSV format",
                    "message": f"CSV must have a 'date' column. Found columns: {df_check.columns.tolist()}"
                }), 400
            
            if 'weight' not in df_check.columns:
                return jsonify({
                    "error": "Invalid CSV format",
                    "message": f"CSV must have a 'weight' column. Found columns: {df_check.columns.tolist()}"
                }), 400
            
            df_check['date'] = pd.to_datetime(df_check['date'], errors='coerce')
            latest_csv_date = df_check['date'].max()
            if pd.notna(latest_csv_date):
                # Use the latest date from CSV, or today if CSV date is in the future
                csv_date = latest_csv_date.date()
                today_date = today.date()
                # Use the earlier of the two (CSV date or today)
                run_date = min(csv_date, today_date).strftime("%Y-%m-%d")
                logger.info(f"Using date from CSV: {run_date} (latest in CSV: {csv_date}, today: {today_date})")
            else:
                # Fallback to today if date parsing fails
                run_date = today.strftime("%Y-%m-%d")
        except Exception as e:
            logger.error(f"Error reading CSV to determine date: {e}", exc_info=True)
            return jsonify({
                "error": "CSV validation failed",
                "message": f"Could not read or validate monthly log CSV: {str(e)}"
            }), 400
        
        # Get model path (from latest fine-tune run or default)
        model_path = request_data.get("model_path")
        if not model_path:
            # Try to get from latest fine-tune run
            finetune_runs_collection = db.smartfolio_finetune_runs
            latest_finetune = finetune_runs_collection.find_one(
                {"status": "completed"},
                sort=[("created_at", -1)]
            )
            if latest_finetune and latest_finetune.get("checkpoint_path"):
                model_path = latest_finetune["checkpoint_path"]
            else:
                # Default model path
                model_path = str(smartfolio_root / "checkpoints_risk05" / "ppo_hgat_custom_20251204_105206.zip")
        
        # XAI Configuration
        xai_config = {
            "date": run_date,
            "monthly_log_csv": monthly_log_csv,
            "model_path": model_path,
            "market": request_data.get("market", "custom"),
            "data_root": request_data.get("data_root", str(smartfolio_root / "dataset_default")),
            "top_k": request_data.get("top_k", 3),  # Top 3 stocks only
            "lookback_days": request_data.get("lookback_days", 30),
            "monthly_run_id": request_data.get("monthly_run_id"),
            "output_dir": request_data.get("output_dir", str(smartfolio_root / "explainability_results" / "latest_run")),
            "llm": request_data.get("llm", True),
            "llm_model": request_data.get("llm_model", "gpt-5-mini"),
            "latent": request_data.get("latent", True)
        }
        
        # Call SmartFolio XAI Orchestrator directly (bypassing MCP for reliability)
        # This avoids MCP server compatibility issues
        try:
            # Import the orchestrator directly
            smartfolio_path = Path(__file__).resolve().parent.parent / "SmartFolio"
            sys.path.insert(0, str(smartfolio_path))
            
            try:
                from explainibility_agents.mcp.orchestrator_xai import run_orchestrator_job
                from explainibility_agents.mcp.config import XAIRequest
            except ImportError:
                # Fallback: try alternative import path
                sys.path.insert(0, str(smartfolio_path / "explainibility_agents" / "mcp"))
                from orchestrator_xai import run_orchestrator_job
                from config import XAIRequest
            
            # Create XAIRequest from config
            xai_request = XAIRequest.from_payload(xai_config)
            
            # Verify top_k is set correctly
            logger.info(f"XAI config - top_k: {xai_config.get('top_k')}, XAIRequest.top_k: {xai_request.top_k}")
            orchestrator_config = xai_request.to_orchestrator_config()
            logger.info(f"OrchestratorConfig.top_k: {orchestrator_config.top_k} (type: {type(orchestrator_config.top_k)})")
            
            # Run orchestrator
            logger.info(f"Running XAI orchestrator for date {run_date} with top_k={orchestrator_config.top_k}...")
            xai_result = run_orchestrator_job(xai_request)
            
            # Ensure result is a dict
            if not isinstance(xai_result, dict):
                xai_result = {"raw_result": str(xai_result)}
                
        except ImportError as e:
            logger.error(f"Failed to import SmartFolio XAI modules: {e}")
            # Save failed run to MongoDB
            if db is not None:
                try:
                    processing_time = time.time() - start_time
                    xai_doc = {
                        "run_date": run_date,
                        "year_month": year_month,
                        "created_at": datetime.utcnow(),
                        "status": "failed",
                        "error_message": f"Import error: {str(e)}",
                        "processing_time_seconds": processing_time,
                        "config": xai_config if 'xai_config' in locals() else {}
                    }
                    xai_runs_collection.insert_one(xai_doc)
                except Exception as save_err:
                    logger.error(f"Failed to save error to MongoDB: {save_err}")
            return jsonify({
                "error": "SmartFolio XAI modules not available",
                "message": f"Could not import XAI orchestrator. Ensure SmartFolio is properly set up. Error: {str(e)}"
            }), 500
        except Exception as e:
            logger.error(f"XAI orchestrator execution failed: {e}", exc_info=True)
            # Save failed run to MongoDB
            if db is not None:
                try:
                    processing_time = time.time() - start_time
                    xai_doc = {
                        "run_date": run_date,
                        "year_month": year_month,
                        "created_at": datetime.utcnow(),
                        "status": "failed",
                        "error_message": f"Execution error: {str(e)}",
                        "processing_time_seconds": processing_time,
                        "config": xai_config if 'xai_config' in locals() else {}
                    }
                    xai_runs_collection.insert_one(xai_doc)
                except Exception as save_err:
                    logger.error(f"Failed to save error to MongoDB: {save_err}")
            return jsonify({
                "error": "XAI orchestrator execution failed",
                "message": str(e)
            }), 500
        
        # Parse result (MCP server returns result in specific format)
        # The result might be in response.text or response.json() depending on MCP server implementation
        if isinstance(xai_result, str):
            try:
                import json
                xai_result = json.loads(xai_result)
            except:
                # If it's not JSON, wrap it
                xai_result = {"raw_output": xai_result}
        
        # Extract data from result
        xai_index = xai_result.get("index")
        stock_reports = xai_result.get("stock_reports", [])
        final_markdown = xai_result.get("final_markdown")
        final_json = xai_result.get("final_json")
        
        # If stock_reports not in result, extract from index
        if not stock_reports and isinstance(xai_index, dict):
            trading_agents = xai_index.get("trading_agents", [])
            for agent in trading_agents:
                ticker = agent.get("ticker")
                output_path = agent.get("output_path")
                if ticker and output_path:
                    # Try to read the markdown file
                    md_path = Path(output_path)
                    if md_path.exists():
                        try:
                            stock_md_content = md_path.read_text(encoding="utf-8")
                            stock_reports.append({
                                "ticker": ticker,
                                "markdown": stock_md_content,
                                "weight": agent.get("weight"),
                                "as_of": agent.get("as_of"),
                                "summary_points": agent.get("summary_points", []),
                                "llm_used": agent.get("llm_used", False),
                                "success": agent.get("success", False)
                            })
                        except Exception as e:
                            logger.warning(f"Could not read markdown for {ticker}: {e}")
        
        # Save to MongoDB
        processing_time = time.time() - start_time
        
        # Store main run document
        xai_doc = {
            "run_date": run_date,
            "year_month": year_month,
            "created_at": datetime.utcnow(),
            "status": "completed",
            "processing_time_seconds": processing_time,
            "config": xai_config,
            "summary": {
                "holdings_count": len(xai_index.get("holdings", [])) if isinstance(xai_index, dict) else 0,
                "trading_agents_count": len(xai_index.get("trading_agents", [])) if isinstance(xai_index, dict) else 0,
                "final_reports_count": len(xai_index.get("final_reports", [])) if isinstance(xai_index, dict) else 0
            } if xai_index else {},
            "final_markdown": final_markdown,
            "final_json": final_json
        }
        
        result = xai_runs_collection.insert_one(xai_doc)
        run_id = result.inserted_id
        
        # Store each stock report independently in a separate collection
        stock_reports_collection = db.smartfolio_xai_stock_reports
        for stock_report in stock_reports:
            stock_doc = {
                "run_id": run_id,
                "run_date": run_date,
                "year_month": year_month,
                "ticker": stock_report.get("ticker"),
                "weight": stock_report.get("weight"),
                "as_of": stock_report.get("as_of"),
                "markdown": stock_report.get("markdown"),
                "summary_points": stock_report.get("summary_points", []),
                "llm_used": stock_report.get("llm_used", False),
                "success": stock_report.get("success", False),
                "created_at": datetime.utcnow()
            }
            stock_reports_collection.insert_one(stock_doc)
        
        return jsonify({
            "success": True,
            "message": f"XAI analysis completed for {year_month}",
            "run_id": str(run_id),
            "run_date": run_date,
            "year_month": year_month,
            "processing_time_seconds": processing_time,
            "stock_reports_saved": len(stock_reports),
            "holdings_count": len(xai_index.get("holdings", [])) if isinstance(xai_index, dict) else 0,
            "trading_agents_count": len(xai_index.get("trading_agents", [])) if isinstance(xai_index, dict) else 0
        }), 200
        
    except Exception as e:
        logger.error(f"XAI monthly analysis error: {e}", exc_info=True)
        
        # Save failed run to MongoDB
        if db is not None:
            try:
                xai_runs_collection = db.smartfolio_xai_runs
                xai_doc = {
                    "run_date": datetime.utcnow().strftime("%Y-%m-%d"),
                    "year_month": datetime.utcnow().strftime("%Y-%m"),
                    "created_at": datetime.utcnow(),
                    "status": "failed",
                    "error_message": str(e),
                    "processing_time_seconds": time.time() - start_time if 'start_time' in locals() else 0,
                    "config": xai_config if 'xai_config' in locals() else {}
                }
                xai_runs_collection.insert_one(xai_doc)
            except:
                pass
        
        return jsonify({
            "error": "XAI analysis failed",
            "message": str(e)
        }), 500


if __name__ == "__main__":
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config["DEBUG"]
    )

