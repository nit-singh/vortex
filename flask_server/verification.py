"""Verification module for KYC document verification.

This module wraps the verification logic from combined_api.py and adapts it
for synchronous Flask usage.
"""

import os
import sys
import asyncio
import tempfile
import shutil
import base64
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from io import BytesIO
from datetime import datetime
from PIL import Image

# Add KYC directory to path
kyc_dir = Path(__file__).resolve().parent.parent / "KYC"
if str(kyc_dir) not in sys.path:
    sys.path.insert(0, str(kyc_dir))

# Import from combined_api.py
try:
    from combined_api import (
        parser_,
        PANCardExtractor,
        AadhaarExtractor,
        extract_itr_details,
        cross_verify_documents,
        resolve_field_value,
        sanitize_value,
        normalize_name,
        parse_date,
        calculate_age,
        validate_pan_format,
        validate_aadhaar_format,
        extract_filing_timeliness,
        parse_numeric_value,
        PANCardInput,
        AadhaarCardInput,
        ITRDocumentInput,
        QuestionnaireInput,
        AdditionalDetails,
    )
    VERIFICATION_AVAILABLE = True
except ImportError as e:
    VERIFICATION_AVAILABLE = False
    # Create dummy classes to avoid errors
    PANCardInput = None
    AadhaarCardInput = None
    ITRDocumentInput = None
    QuestionnaireInput = None
    AdditionalDetails = None

# Import VideoVerificationService
try:
    from combined_api import VideoVerificationService
    VIDEO_VERIFICATION_AVAILABLE = True
except ImportError:
    VIDEO_VERIFICATION_AVAILABLE = False
    VideoVerificationService = None

# Import alert functions
try:
    from kyc_alerts import build_alert_signal, plan_alert_from_signal
    ALERT_AVAILABLE = True
except ImportError:
    ALERT_AVAILABLE = False
    build_alert_signal = None
    plan_alert_from_signal = None


def run_async(coro):
    """Run async coroutine in sync context."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    if loop.is_running():
        # If loop is already running, use nest_asyncio
        try:
            import nest_asyncio
            nest_asyncio.apply()
        except ImportError:
            # Fallback: run in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
    
    return loop.run_until_complete(coro)


def parse_document_sync(image: Image.Image, doc_type: str) -> Dict[str, Any]:
    """Parse document synchronously."""
    if not VERIFICATION_AVAILABLE:
        raise RuntimeError("Verification modules not available")
    
    return run_async(parser_(image, doc_type))


def convert_base64_to_image(base64_content: str, mime_type: Optional[str] = None) -> Image.Image:
    """Convert base64 string to PIL Image. Handles both images and PDFs."""
    try:
        image_data = base64.b64decode(base64_content)
        
        # Check if it's a PDF
        if mime_type == "application/pdf" or (len(image_data) > 4 and image_data[:4] == b'%PDF'):
            try:
                from pdf2image import convert_from_bytes
                images = convert_from_bytes(image_data)
                if images:
                    # Convert first page to RGB
                    image = images[0].convert('RGB')
                    return image
                else:
                    raise ValueError("PDF conversion resulted in no images")
            except ImportError:
                raise ValueError("pdf2image not available for PDF conversion")
        
        # Handle regular images
        image = Image.open(BytesIO(image_data))
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        return image
    except Exception as e:
        raise ValueError(f"Failed to convert base64 to image: {str(e)}")


def extract_question_answer(full_answer: str) -> Optional[str]:
    """Extract A/B/C/D from full answer text like 'A) I have a clear...' or just 'A'."""
    if not full_answer:
        return None
    
    # Strip whitespace
    full_answer = full_answer.strip()
    
    # If it's already just a single letter A-D, return it
    if len(full_answer) == 1 and full_answer.upper() in ['A', 'B', 'C', 'D']:
        return full_answer.upper()
    
    # Look for pattern like "A)", "B)", "A.", "B:", etc. at the start
    if len(full_answer) >= 2:
        first_char = full_answer[0].upper()
        second_char = full_answer[1] if len(full_answer) > 1 else ''
        
        # Check if first char is A-D and second is ), ., or :
        if first_char in ['A', 'B', 'C', 'D'] and second_char in [')', '.', ':']:
            return first_char
        
        # Also check for patterns like "(A)", "(B)", etc.
        if len(full_answer) >= 3 and full_answer[0] == '(' and full_answer[2] == ')':
            middle_char = full_answer[1].upper()
            if middle_char in ['A', 'B', 'C', 'D']:
                return middle_char
    
    return None


def map_questionnaire_data(questionnaire_data: Dict[str, Any]) -> Dict[str, Any]:
    """Map questionnaire data from form format to verification format.
    
    Expects questionnaire_data with keys: "q1", "q2", "q3", "q4", "q5", "q6"
    Each value should be a string like "A) I have a clear..." or just "A"
    """
    questionnaire_dict = {}
    
    for i in range(1, 7):
        # Try lowercase key first (from questionnaire_payload["investmentQuestions"])
        key_lower = f"q{i}"
        # Also try the original form key for backward compatibility
        key_form = f"investmentQ{i}"
        
        # Get the answer text (try both key formats)
        full_answer = questionnaire_data.get(key_lower) or questionnaire_data.get(key_form) or ""
        
        # Extract just the letter (A, B, C, or D)
        answer = extract_question_answer(str(full_answer) if full_answer else "")
        
        if answer:
            questionnaire_dict[f"Q{i}"] = answer
        else:
            questionnaire_dict[f"Q{i}"] = None
    
    return questionnaire_dict


def map_additional_details(form_data: Dict[str, Any]) -> Dict[str, Any]:
    """Map additional details from form format to verification format."""
    # Combine address fields
    address_parts = [
        form_data.get("addressLine1", ""),
        form_data.get("addressLine2", ""),
        form_data.get("city", ""),
        form_data.get("state", ""),
        form_data.get("pinCode", "")
    ]
    address = ", ".join([part for part in address_parts if part])
    
    # Parse amount to invest
    amount_to_invest = form_data.get("amountToInvest", "")
    try:
        amount_to_invest = float(amount_to_invest) if amount_to_invest else None
    except (ValueError, TypeError):
        amount_to_invest = None
    
    # Parse dependents
    dependents = form_data.get("dependents", "0")
    try:
        dependents = int(dependents) if dependents else 0
    except (ValueError, TypeError):
        dependents = 0
    
    return {
        "amount_to_invest": amount_to_invest,
        "address": address,
        "main_occupation": form_data.get("occupation", ""),
        "marital_status": form_data.get("maritalStatus", ""),
        "dependents": dependents,
        "citizenship": form_data.get("citizenship", "")
    }


def verify_questionnaire_submission(
    pan_image: Image.Image,
    aadhaar_image: Image.Image,
    itr_image: Image.Image,
    video_url: str,
    questionnaire_data: Dict[str, Any],
    form_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Main verification function.
    
    Args:
        pan_image: PIL Image of PAN card
        aadhaar_image: PIL Image of Aadhaar card
        itr_image: PIL Image of ITR document
        video_url: Cloudinary URL for verification video
        questionnaire_data: Questionnaire answers (Q1-Q6)
        form_data: Form data (personal info, address, etc.)
    
    Returns:
        Dictionary with master_verification and ml_model_input
    """
    if not VERIFICATION_AVAILABLE:
        return {
            "error": "Verification modules not available",
            "master_verification": None,
            "ml_model_input": None
        }
    
    # Map data formats
    questionnaire_dict = map_questionnaire_data(questionnaire_data)
    additional_dict = map_additional_details(form_data)
    
    # Create Pydantic models
    try:
        questionnaire_input = QuestionnaireInput(**questionnaire_dict)
        additional_input = AdditionalDetails(**additional_dict)
    except Exception as e:
        return {
            "error": f"Failed to create input models: {str(e)}",
            "master_verification": None,
            "ml_model_input": None
        }
    
    # Parse documents
    pan_data_dict = {}
    aadhaar_data_dict = {}
    itr_data_dict = {}
    document_verification = {
        "is_verified": False,
        "mismatches": [],
        "warnings": [],
        "missing_fields": [],
        "verification_details": {},
    }
    video_verification_result = {
        "final_decision": "not_evaluated",
        "notes": ["Video verification not performed"],
        "aadhaar_pan_match": {"matched": False, "status": "not_evaluated"},
        "pan_video_match": {"matched": False, "status": "not_evaluated"},
        "liveness_check": {"passed": False}
    }
    
    # Initialize temp_dir for video verification cleanup
    temp_dir = None
    try:
        # Parse documents (using PIL Images directly)
        try:
            pan_data_dict = parse_document_sync(pan_image, 'pan')
        except Exception as pan_err:
            import traceback
            traceback.print_exc()
            raise
        
        try:
            aadhaar_data_dict = parse_document_sync(aadhaar_image, 'adhaar')
        except RuntimeError as e:
            if "cannot schedule new futures after interpreter shutdown" in str(e):
                # Handle interpreter shutdown gracefully
                print("⚠️  Warning: Document parser unavailable due to interpreter shutdown. This may occur during Flask reload.")
                print("   The system will retry on the next request.")
                raise RuntimeError("Document parsing temporarily unavailable. Please try again in a moment.") from e
            raise
        except Exception as aadhaar_err:
            import traceback
            traceback.print_exc()
            raise
        
        try:
            itr_data_dict = parse_document_sync(itr_image, 'itr')
        except Exception as itr_err:
            import traceback
            traceback.print_exc()
            raise
        
        # Build Pydantic objects
        pan_input = PANCardInput(**pan_data_dict)
        aadhaar_input = AadhaarCardInput(**aadhaar_data_dict)
        itr_input = ITRDocumentInput(**itr_data_dict)
        
        # Cross-verify documents
        document_verification = cross_verify_documents(pan_input, aadhaar_input, itr_input)
        
        # Video verification (requires temporary files)
        if video_url and VIDEO_VERIFICATION_AVAILABLE:
            temp_dir = tempfile.mkdtemp()
            try:
                # Download video
                import requests
                video_response = requests.get(video_url, timeout=30)
                video_response.raise_for_status()
                
                # Save images and video temporarily
                pan_temp_path = os.path.join(temp_dir, "pan_document.png")
                aadhaar_temp_path = os.path.join(temp_dir, "aadhaar_document.png")
                temp_video_webm_path = os.path.join(temp_dir, "temp_video.webm")
                video_temp_path = os.path.join(temp_dir, "selfie_video.mp4")
                
                pan_image.save(pan_temp_path, format='PNG')
                aadhaar_image.save(aadhaar_temp_path, format='PNG')
                
                # Save downloaded video (likely WebM from Cloudinary)
                with open(temp_video_webm_path, "wb") as f:
                    f.write(video_response.content)
                
                # Convert WebM to MP4 if needed
                try:
                    from moviepy.editor import VideoFileClip
                    video_clip = VideoFileClip(temp_video_webm_path)
                    video_clip.write_videofile(
                        video_temp_path,
                        codec='libx264',
                        audio_codec='aac',
                        preset='medium',
                        logger=None
                    )
                    video_clip.close()
                    # Remove temporary webm file
                    if os.path.exists(temp_video_webm_path):
                        os.unlink(temp_video_webm_path)
                except ImportError:
                    # If moviepy not available, try using original format
                    if os.path.exists(temp_video_webm_path):
                        video_temp_path = temp_video_webm_path
                except Exception as conv_error:
                    # Fallback to original format if conversion fails
                    if os.path.exists(temp_video_webm_path):
                        video_temp_path = temp_video_webm_path
                
                # Run video verification
                video_verifier = VideoVerificationService()
                video_verification_result = video_verifier.run_pipeline(
                    aadhaar_temp_path, pan_temp_path, video_temp_path
                )
            except Exception as e:
                import traceback
                traceback.print_exc()
                video_verification_result = {
                    "final_decision": "error_video_verification",
                    "notes": [f"Video verification error: {str(e)}"],
                    "aadhaar_pan_match": {"matched": False, "status": "error"},
                    "pan_video_match": {"matched": False, "status": "error"},
                    "liveness_check": {"passed": False}
                }
        
        # Resolve consolidated values
        pan_resolved = resolve_field_value("PAN", pan_input.pan_number, itr_input.PAN)
        aadhaar_resolved = resolve_field_value("Aadhaar", aadhaar_input.aadhaar_number)
        name_resolved = resolve_field_value("Name", pan_input.name, aadhaar_input.name, itr_input.Name)
        father_name_resolved = resolve_field_value("Father's Name", pan_input.father_name)
        dob_resolved = resolve_field_value("DOB", pan_input.dob, aadhaar_input.date_of_birth)
        
        age = calculate_age(dob_resolved["value"]) if dob_resolved["value"] else None
        age_resolved = {
            "value": age,
            "source": dob_resolved["source"] if age else None,
            "status": "calculated_from_dob" if age else "not_calculable_missing_dob"
        }
        
        gender_resolved = resolve_field_value(
            "Gender",
            aadhaar_input.gender.value if aadhaar_input.gender else None
        )
        
        address_resolved = resolve_field_value("Address", additional_input.address)
        
        # Financial details
        gross_income_value = parse_numeric_value(itr_input.Total_Income)
        tax_paid_value = parse_numeric_value(itr_input.Taxes_Paid)
        
        gross_income_resolved = {
            "value": gross_income_value,
            "source": "ITR" if gross_income_value is not None else None,
            "status": "found" if gross_income_value is not None else "not_found_in_itr_document"
        }
        
        tax_paid_resolved = {
            "value": tax_paid_value,
            "source": "ITR" if tax_paid_value is not None else None,
            "status": "found" if tax_paid_value is not None else "not_found_in_itr_document"
        }
        
        filing_timeliness = extract_filing_timeliness(itr_input.Filed_u_s)
        
        # Build alert signal and plan
        alert_signal = None
        alert_plan = None
        if ALERT_AVAILABLE:
            try:
                temp_master_json_id = "temp-id"
                alert_signal = build_alert_signal(
                    temp_master_json_id,
                    document_verification,
                    video_verification_result,
                )
                alert_plan = plan_alert_from_signal(alert_signal)
            except Exception as e:
                pass
        
        # Build master JSON
        master_json = {
            "verification_status": {
                "document_verification": document_verification["is_verified"],
                "video_verification": video_verification_result.get("final_decision") == "accept",
                "overall_status": (
                    document_verification["is_verified"] and
                    video_verification_result.get("final_decision") == "accept"
                ),
                "summary": {
                    "total_mismatches": len(document_verification.get("mismatches", [])),
                    "total_warnings": len(document_verification.get("warnings", [])),
                    "missing_fields": len(document_verification.get("missing_fields", []))
                }
            },
            "personal_details": {
                "pan_number": {
                    **pan_resolved,
                    "validated": validate_pan_format(pan_resolved["value"]) if pan_resolved["value"] else False
                },
                "aadhaar_number": {
                    **aadhaar_resolved,
                    "validated": validate_aadhaar_format(aadhaar_resolved["value"]) if aadhaar_resolved["value"] else False
                },
                "name": name_resolved,
                "father_name": father_name_resolved,
                "date_of_birth": dob_resolved,
                "age": age_resolved,
                "gender": gender_resolved,
                "address": address_resolved,
                "citizenship": {
                    "value": sanitize_value(additional_input.citizenship),
                    "source": "Additional Details" if sanitize_value(additional_input.citizenship) else None,
                    "status": "found" if sanitize_value(additional_input.citizenship) else "not_provided"
                }
            },
            "financial_details": {
                "itr_type": {
                    "value": sanitize_value(itr_input.ITR_Type),
                    "source": "ITR" if sanitize_value(itr_input.ITR_Type) else None,
                    "status": "found" if sanitize_value(itr_input.ITR_Type) else "not_found_in_itr_document"
                },
                "filing_status": {
                    "value": sanitize_value(itr_input.Status),
                    "source": "ITR" if sanitize_value(itr_input.Status) else None,
                    "status": "found" if sanitize_value(itr_input.Status) else "not_found_in_itr_document"
                },
                "filing_timeliness": {
                    "value": filing_timeliness if filing_timeliness not in ["Unknown", "Not found in ITR document"] else None,
                    "source": "ITR" if sanitize_value(itr_input.Filed_u_s) else None,
                    "status": "extracted" if filing_timeliness not in ["Unknown", "Not found in ITR document"] else "not_determinable"
                },
                "filed_under_section": {
                    "value": sanitize_value(itr_input.Filed_u_s),
                    "source": "ITR" if sanitize_value(itr_input.Filed_u_s) else None,
                    "status": "found" if sanitize_value(itr_input.Filed_u_s) else "not_found_in_itr_document"
                },
                "total_income": gross_income_resolved,
                "taxes_paid": tax_paid_resolved,
                "amount_to_invest": {
                    "value": additional_input.amount_to_invest,
                    "source": "Additional Details" if additional_input.amount_to_invest else None,
                    "status": "found" if additional_input.amount_to_invest else "not_provided"
                }
            },
            "family_details": {
                "marital_status": {
                    "value": additional_input.marital_status.value if additional_input.marital_status else None,
                    "source": "Additional Details" if additional_input.marital_status else None,
                    "status": "found" if additional_input.marital_status else "not_provided"
                },
                "dependents": {
                    "value": additional_input.dependents,
                    "source": "Additional Details" if additional_input.dependents is not None else None,
                    "status": "found" if additional_input.dependents is not None else "not_provided"
                },
                "main_occupation": {
                    "value": sanitize_value(additional_input.main_occupation),
                    "source": "Additional Details" if sanitize_value(additional_input.main_occupation) else None,
                    "status": "found" if sanitize_value(additional_input.main_occupation) else "not_provided"
                }
            },
            "questionnaire_responses": {
                f"Q{i+1}": {
                    "value": getattr(questionnaire_input, f"Q{i+1}").value if getattr(questionnaire_input, f"Q{i+1}") else None,
                    "status": "answered" if getattr(questionnaire_input, f"Q{i+1}") else "not_answered"
                } for i in range(6)
            },
            "document_verification_details": document_verification,
            "video_verification_details": video_verification_result,
            "parsed_documents": {
                "pan": pan_data_dict,
                "aadhaar": aadhaar_data_dict,
                "itr": itr_data_dict
            },
            "timestamp": datetime.now().isoformat()
        }
        
        # Add alerting if available
        if alert_signal and alert_plan:
            master_json["alerting"] = {
                "signal": alert_signal.to_dict() if hasattr(alert_signal, 'to_dict') else str(alert_signal),
                "plan": alert_plan.to_dict() if hasattr(alert_plan, 'to_dict') else str(alert_plan),
            }
        
        # Build ML model input JSON
        ml_input_json = {
            "age": age,
            "dependents": additional_input.dependents,
            "gross_income": gross_income_value,
            "tax_paid": tax_paid_value,
            "gender": aadhaar_input.gender.value if aadhaar_input.gender else None,
            "main_occupation": sanitize_value(additional_input.main_occupation),
            "marital_status": additional_input.marital_status.value if additional_input.marital_status else None,
            "filing_timeliness": filing_timeliness if filing_timeliness not in ["Unknown", "Not found in ITR document"] else None,
            "Q1": questionnaire_input.Q1.value if questionnaire_input.Q1 else None,
            "Q2": questionnaire_input.Q2.value if questionnaire_input.Q2 else None,
            "Q3": questionnaire_input.Q3.value if questionnaire_input.Q3 else None,
            "Q4": questionnaire_input.Q4.value if questionnaire_input.Q4 else None,
            "Q5": questionnaire_input.Q5.value if questionnaire_input.Q5 else None,
            "Q6": questionnaire_input.Q6.value if questionnaire_input.Q6 else None
        }
        
        return {
            "master_verification": master_json,
            "ml_model_input": ml_input_json,
            "error": None
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "error": f"Verification failed: {str(e)}",
            "master_verification": None,
            "ml_model_input": None
        }
    finally:
        # Clean up temporary directory
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                pass

