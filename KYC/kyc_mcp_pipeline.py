"""Shared utilities for the KYC Pathway MCP server.

This module reuses the domain logic defined in ``combined_api.py`` so the
Pathway MCP server can stay in sync with the FastAPI workflow while enforcing
privacy controls (PAN & Aadhaar encryption + redaction) before exposing any
payloads to LLM-powered agents.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

from cryptography.fernet import Fernet, InvalidToken

# Import observability for LLM tracking
try:
    from kyc_observability import (
        track_llm_generation,
        increment,
        accumulate_cost,
        calculate_openai_cost,
    )
    OBSERVABILITY_ENABLED = True
except ImportError:
    OBSERVABILITY_ENABLED = False

# Import the existing KYC primitives so we don't fork business logic.
from combined_api import (  # type: ignore
    AadhaarCardInput,
    AdditionalDetails,
    ITRDocumentInput,
    PANCardInput,
    QuestionnaireInput,
    adhaar_extract,
    calculate_age,
    cross_verify_documents,
    extract_filing_timeliness,
    itr_extract,
    parse_numeric_value,
    pan_extract,
    resolve_field_value,
    validate_aadhaar_format,
    validate_pan_format,
)
from kyc_alerts import build_alert_signal, plan_alert_from_signal


LOGGER = logging.getLogger(__name__)

PAN_PATTERN = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
AADHAAR_PATTERN = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")


class SensitiveDataEncryptor:
    """Utility that encrypts PAN/Aadhaar before sharing with other systems."""

    def __init__(self, key: Optional[str] = None) -> None:
        key = key or os.getenv("KYC_ENCRYPTION_KEY")
        if not key:
            # Generate an ephemeral key so at least the MCP output hides data.
            key = Fernet.generate_key().decode()
            LOGGER.warning(
                "KYC_ENCRYPTION_KEY is not set. Generated an ephemeral key; "
                "encrypted identifiers cannot be decrypted later."
            )
        try:
            self._fernet = Fernet(key)
            self.key_id = "env:KYC_ENCRYPTION_KEY"
        except (ValueError, TypeError):
            raise RuntimeError(
                "Invalid KYC_ENCRYPTION_KEY. Provide a valid base64 Fernet key."
            )

    @staticmethod
    def _mask_value(value: str) -> str:
        if not value:
            return ""
        return f"{'*' * max(len(value) - 4, 0)}{value[-4:]}"

    def encrypt(self, value: Optional[str]) -> Dict[str, Optional[str]]:
        if value is None or value == "":
            return {
                "encrypted": None,
                "mask": None,
                "last4": None,
                "key": self.key_id,
            }
        token = self._fernet.encrypt(value.encode()).decode()
        return {
            "encrypted": token,
            "mask": self._mask_value(value),
            "last4": value[-4:],
            "key": self.key_id,
        }

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:  # pragma: no cover - only for debugging
            raise RuntimeError("Unable to decrypt identifier") from exc


def _redact_identifiers_from_text(text: str) -> str:
    text = PAN_PATTERN.sub(lambda m: SensitiveDataEncryptor._mask_value(m.group(0)), text)
    text = AADHAAR_PATTERN.sub(
        lambda m: SensitiveDataEncryptor._mask_value(re.sub(r"\D", "", m.group(0))),
        text,
    )
    return text


def redact_sensitive_structures(payload: Any) -> Any:
    """Recursively mask PAN/Aadhaar values in dictionaries/lists/strings."""

    if isinstance(payload, dict):
        return {k: redact_sensitive_structures(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact_sensitive_structures(item) for item in payload]
    if isinstance(payload, str):
        return _redact_identifiers_from_text(payload)
    return payload


@dataclass
class ParsedDocumentBundle:
    pan: PANCardInput
    aadhaar: AadhaarCardInput
    itr: ITRDocumentInput


def parse_documents_from_texts(
    pan_text: str,
    aadhaar_text: str,
    itr_text: str,
) -> ParsedDocumentBundle:
    """Run the extraction stack on raw OCR strings."""

    pan_data = PANCardInput(**pan_extract(pan_text))
    aadhaar_data = AadhaarCardInput(**adhaar_extract(aadhaar_text))
    itr_data = ITRDocumentInput(**itr_extract(itr_text))
    return ParsedDocumentBundle(pan=pan_data, aadhaar=aadhaar_data, itr=itr_data)


@dataclass
class VerificationContext:
    parsed: ParsedDocumentBundle
    questionnaire: QuestionnaireInput
    additional: AdditionalDetails
    video_verification: Dict[str, Any]


def build_video_placeholder() -> Dict[str, Any]:
    return {
        "aadhaar_pan_match": {
            "matched": True,
            "confidence": None,
            "status": "Video verification module not integrated - placeholder result",
        },
        "pan_video_match": {
            "matched": True,
            "confidence": None,
            "status": "Video verification module not integrated - placeholder result",
        },
        "liveness_check": {
            "passed": True,
            "confidence": None,
            "status": "Video verification module not integrated - placeholder result",
        },
        "final_decision": "accept",
        "notes": [
            "Video verification placeholder - integrate actual module for production use"
        ],
    }


def build_master_and_ml_payloads(
    ctx: VerificationContext,
    encryptor: SensitiveDataEncryptor | None = None,
    precomputed_document_verification: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    encryptor = encryptor or SensitiveDataEncryptor()

    pan_input = ctx.parsed.pan
    aadhaar_input = ctx.parsed.aadhaar
    itr_input = ctx.parsed.itr

    document_verification = precomputed_document_verification or cross_verify_documents(
        pan_input, aadhaar_input, itr_input
    )

    pan_resolved = resolve_field_value("PAN", pan_input.pan_number, itr_input.PAN)
    aadhaar_resolved = resolve_field_value("Aadhaar", aadhaar_input.aadhaar_number)
    name_resolved = resolve_field_value("Name", pan_input.name, aadhaar_input.name, itr_input.Name)
    father_name_resolved = resolve_field_value("Father's Name", pan_input.father_name)
    dob_resolved = resolve_field_value("DOB", pan_input.dob, aadhaar_input.date_of_birth)
    age = calculate_age(dob_resolved["value"]) if dob_resolved["value"] else None
    age_resolved = {
        "value": age,
        "source": dob_resolved["source"] if age else None,
        "status": "calculated_from_dob" if age else "not_calculable_missing_dob",
    }
    gender_resolved = resolve_field_value(
        "Gender", aadhaar_input.gender.value if aadhaar_input.gender else None
    )
    address_resolved = resolve_field_value("Address", ctx.additional.address)

    gross_income_value = parse_numeric_value(itr_input.Total_Income)
    tax_paid_value = parse_numeric_value(itr_input.Taxes_Paid)

    gross_income_resolved = {
        "value": gross_income_value,
        "source": "ITR" if gross_income_value is not None else None,
        "status": "found" if gross_income_value is not None else "not_found_in_itr_document",
    }
    tax_paid_resolved = {
        "value": tax_paid_value,
        "source": "ITR" if tax_paid_value is not None else None,
        "status": "found" if tax_paid_value is not None else "not_found_in_itr_document",
    }

    filing_timeliness = extract_filing_timeliness(itr_input.Filed_u_s)

    # Encrypt sensitive identifiers before storing/returning them.
    pan_encrypted = encryptor.encrypt(pan_resolved.get("value"))
    aadhaar_encrypted = encryptor.encrypt(aadhaar_resolved.get("value"))
    pan_resolved.pop("value", None)
    aadhaar_resolved.pop("value", None)

    master_json = {
        "verification_status": {
            "document_verification": document_verification["is_verified"],
            "video_verification": ctx.video_verification["final_decision"] == "accept",
            "overall_status": document_verification["is_verified"]
            and ctx.video_verification["final_decision"] == "accept",
            "summary": {
                "total_mismatches": len(document_verification["mismatches"]),
                "total_warnings": len(document_verification["warnings"]),
                "missing_fields": len(document_verification["missing_fields"]),
            },
        },
        "personal_details": {
            "pan_number": {
                **pan_resolved,
                "encrypted": pan_encrypted,
                "validated": validate_pan_format(pan_input.pan_number),
            },
            "aadhaar_number": {
                **aadhaar_resolved,
                "encrypted": aadhaar_encrypted,
                "validated": validate_aadhaar_format(aadhaar_input.aadhaar_number),
            },
            "name": name_resolved,
            "father_name": father_name_resolved,
            "date_of_birth": dob_resolved,
            "age": age_resolved,
            "gender": gender_resolved,
            "address": address_resolved,
            "citizenship": {
                "value": ctx.additional.citizenship,
                "source": "Additional Details" if ctx.additional.citizenship else None,
                "status": "found" if ctx.additional.citizenship else "not_provided",
            },
        },
        "financial_details": {
            "itr_type": {
                "value": itr_input.ITR_Type,
                "source": "ITR" if itr_input.ITR_Type else None,
                "status": "found" if itr_input.ITR_Type else "not_found_in_itr_document",
            },
            "filing_status": {
                "value": itr_input.Status,
                "source": "ITR" if itr_input.Status else None,
                "status": "found" if itr_input.Status else "not_found_in_itr_document",
            },
            "filing_timeliness": {
                "value": filing_timeliness if filing_timeliness not in {"Unknown", "Not found in ITR document"} else None,
                "source": "ITR" if itr_input.Filed_u_s else None,
                "status": "extracted"
                if filing_timeliness not in {"Unknown", "Not found in ITR document"}
                else "not_determinable",
            },
            "filed_under_section": {
                "value": itr_input.Filed_u_s,
                "source": "ITR" if itr_input.Filed_u_s else None,
                "status": "found" if itr_input.Filed_u_s else "not_found_in_itr_document",
            },
            "total_income": gross_income_resolved,
            "taxes_paid": tax_paid_resolved,
            "amount_to_invest": {
                "value": ctx.additional.amount_to_invest,
                "source": "Additional Details" if ctx.additional.amount_to_invest else None,
                "status": "found" if ctx.additional.amount_to_invest else "not_provided",
            },
        },
        "family_details": {
            "marital_status": {
                "value": ctx.additional.marital_status.value if ctx.additional.marital_status else None,
                "source": "Additional Details" if ctx.additional.marital_status else None,
                "status": "found" if ctx.additional.marital_status else "not_provided",
            },
            "dependents": {
                "value": ctx.additional.dependents,
                "source": "Additional Details" if ctx.additional.dependents is not None else None,
                "status": "found" if ctx.additional.dependents is not None else "not_provided",
            },
            "main_occupation": {
                "value": ctx.additional.main_occupation,
                "source": "Additional Details" if ctx.additional.main_occupation else None,
                "status": "found" if ctx.additional.main_occupation else "not_provided",
            },
        },
        "questionnaire_responses": {
            f"Q{i+1}": {
                "value": getattr(ctx.questionnaire, f"Q{i+1}").value
                if getattr(ctx.questionnaire, f"Q{i+1}")
                else None,
                "status": "answered" if getattr(ctx.questionnaire, f"Q{i+1}") else "not_answered",
            }
            for i in range(6)
        },
        "document_verification_details": redact_sensitive_structures(document_verification),
        "video_verification_details": ctx.video_verification,
        "parsed_documents": redact_sensitive_structures(
            {
                "pan": ctx.parsed.pan.dict(),
                "aadhaar": ctx.parsed.aadhaar.dict(),
                "itr": ctx.parsed.itr.dict(),
            }
        ),
    }

    alert_signal = build_alert_signal(None, document_verification, ctx.video_verification)
    alert_plan = plan_alert_from_signal(alert_signal)
    master_json["alerting"] = {
        "signal": alert_signal.to_dict(),
        "plan": alert_plan.to_dict(),
    }

    ml_input_json = {
        "age": age,
        "dependents": ctx.additional.dependents,
        "gross_income": gross_income_value,
        "tax_paid": tax_paid_value,
        "gender": ctx.parsed.aadhaar.gender.value if ctx.parsed.aadhaar.gender else None,
        "main_occupation": ctx.additional.main_occupation,
        "marital_status": ctx.additional.marital_status.value if ctx.additional.marital_status else None,
        "filing_timeliness": filing_timeliness if filing_timeliness not in {"Unknown", "Not found in ITR document"} else None,
        "Q1": ctx.questionnaire.Q1.value if ctx.questionnaire.Q1 else None,
        "Q2": ctx.questionnaire.Q2.value if ctx.questionnaire.Q2 else None,
        "Q3": ctx.questionnaire.Q3.value if ctx.questionnaire.Q3 else None,
        "Q4": ctx.questionnaire.Q4.value if ctx.questionnaire.Q4 else None,
        "Q5": ctx.questionnaire.Q5.value if ctx.questionnaire.Q5 else None,
        "Q6": ctx.questionnaire.Q6.value if ctx.questionnaire.Q6 else None,
    }

    return master_json, ml_input_json


KYC_REPORT_PROMPT = """
You are an expert KYC Compliance Officer. Analyze the provided KYC data and generate a professional markdown report.

=== INPUT DATA ===
{master_json}

=== QUESTIONNAIRE CONTEXT ===

**Question 1 (Investment Strategy):**
- A: Clear, well-researched strategy (Sophisticated)
- B: Follows market trends and news (Trend-driven)
- C: Gets tips from friends/family/social media (Social-influenced)
- D: No clear approach, hope-based (Inexperienced)

**Question 2 (Activity & Anxiety Level):**
- A: Multiple times a day (High anxiety/over-monitoring)
- B: Once a day (Moderate monitoring)
- C: A few times a week (Balanced approach)
- D: Few times a month or less (Low anxiety/passive)

**Question 3 (Disposition Effect - Bias Detection):**
- A: Sell Stock A (winner) - Rational, willing to realize gains
- B: Sell Stock B (loser) - May hold losers too long (common bias)
- C: Sell half of each - Balanced/cautious approach

**Question 4 (Level of Involvement):**
- A: Fully delegated - Prefers hands-off approach
- B: Collaborative - Wants strategic involvement
- C: Hands-on - Needs high control/involvement

**Question 5 (Success Benchmark):**
- A: Absolute return - Simple profit focus
- B: Market benchmark - Index-relative performance
- C: Goal-based - Long-term planning oriented
- D: Peer comparison - Social comparison driven

**Question 6 (Crisis Communication):**
- A: Needs proactive reassurance - Requires handholding
- B: Trusts the plan - Independent/disciplined
- C: Wants detailed reports - Detail-oriented
- D: Wants to actively discuss options - Collaborative decision-making

=== CRITICAL INSTRUCTIONS ===
1. ONLY use data present in the JSON input
2. For null/missing/empty fields: write "Not Available"
3. Mask sensitive data properly (PAN: show last 4 digits, Aadhaar: show last 4 digits)
4. Use [PASS] for verified/passed, [FAIL] for failed/issues
5. Calculate income-to-investment ratio: (investment_amount / total_income) × 100
6. Interpret questionnaire based on the context provided above
7. Keep language professional and factual - no speculation
8. Do NOT fabricate any values or analysis not supported by data
9. Do NOT include the prompt or instructions in your output
10. Do NOT use bold formatting for section content, only for field labels

=== OUTPUT FORMAT ===

Generate ONLY the markdown report in the following format. Do not repeat these instructions or the input data.

---

# KYC VERIFICATION REPORT

Report ID: [generate from timestamp]
Date: [use today's date: November 30, 2025]
Overall Status: PASS / FAIL / REVIEW

## 1. Summary
[Provide a 3–4 sentence overview covering: applicant name & age, overall verification outcome, key confirmations or concerns, notable financial observation]

## 2. Identity Verification
- PAN Number: [mask properly - show only last 4 digits]
- Aadhaar Number: [mask properly - show only last 4 digits]
- Name Verification: [PAN and Aadhaar name match status]
- Validation Status: [PASS] / [FAIL]
- Video KYC: [Face match & liveness check status]
- Data Quality: [mention any mismatches, warnings, or missing fields]

## 3. Financial Overview
- Total Income Declared: ₹[amount]
- Taxes Paid: ₹[amount]
- Investment Amount: ₹[amount]
- Income-to-Investment Ratio: [percentage]% ([Low/Reasonable/High])
- ITR Filing: [type and timeliness]
- Financial Notes: [any observations from tax filing]

## 4. Behavioral Assessment

Investment Sophistication: [Based on Q1]

Monitoring Behavior: [Based on Q2]

Decision Biases: [Based on Q3]

Client Management Style: [Based on Q4]

Success Definition: [Based on Q5]

Support Requirements: [Based on Q6]

Overall Profile: [Synthesize into 2-3 sentences]

## 5. Final Decision

Decision: APPROVED / REJECTED / REVIEW

Rationale:
- Document Validity: [PASS] / [FAIL] [description]
- Video KYC: [PASS] / [FAIL] [description]
- Financial Suitability: [PASS] / [FAIL] [description]
- Behavioral Fit: [if relevant]
- Risk Factors: [if present]

Recommendation: [brief statement]

---

BEGIN YOUR RESPONSE WITH "# KYC VERIFICATION REPORT" AND NOTHING ELSE BEFORE IT.
"""

PRIMARY_MODEL = "gpt-4o-mini"
FALLBACK_MODEL = "google/flan-t5-large"  # Can use flan-t5-base, flan-t5-large, or flan-t5-xl
MAX_TOKENS = 1500
TEMPERATURE = 0.2
OUTPUT_FILE = "kyc_report.md"

# Initialize clients
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
fallback_tokenizer = None
fallback_model = None


def initialize_fallback_model():
    """Initialize FLAN-T5 model for fallback use."""
    global fallback_tokenizer, fallback_model
    try:
        fallback_tokenizer = AutoTokenizer.from_pretrained(FALLBACK_MODEL)
        fallback_model = AutoModelForSeq2SeqLM.from_pretrained(FALLBACK_MODEL)
        return True
    except Exception as e:
        return False


def generate_with_openai(prompt: str) -> Optional[str]:
    """Generate report using OpenAI GPT-4o-mini."""
    try:
        messages = [
            {
                "role": "system",
                "content": "You are an expert KYC Compliance Officer. Generate professional, accurate, and concise KYC verification reports."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        response = client.chat.completions.create(
            model=PRIMARY_MODEL,
            messages=messages,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        
        content = response.choices[0].message.content.strip()
        
        # Track LLM usage with observability
        if OBSERVABILITY_ENABLED:
            usage = response.usage
            if usage:
                input_tokens = usage.prompt_tokens
                output_tokens = usage.completion_tokens
                cost = calculate_openai_cost(PRIMARY_MODEL, input_tokens, output_tokens)
                
                # Track the generation
                track_llm_generation(
                    name="kyc_report_generation",
                    model=PRIMARY_MODEL,
                    input_messages=messages,
                    output=content[:500] + "..." if len(content) > 500 else content,  # Truncate for tracking
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost=cost,
                    metadata={"operation": "generate_report"}
                )
                
                # Accumulate cost for summary
                accumulate_cost(PRIMARY_MODEL, input_tokens, output_tokens, cost)
                increment("llm_report_generations")
                LOGGER.debug(f"Report generation cost: ${cost:.6f}")
        
        return content
    except Exception as e:
        LOGGER.error(f"OpenAI generation failed: {e}")
        return None


def generate_with_flan_t5(prompt: str) -> Optional[str]:
    """Generate report using FLAN-T5 fallback model."""
    global fallback_tokenizer, fallback_model
    
    if fallback_tokenizer is None or fallback_model is None:
        if not initialize_fallback_model():
            return None
    
    try:
        # Truncate prompt if too long for FLAN-T5
        inputs = fallback_tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True)
        
        with torch.no_grad():
            outputs = fallback_model.generate(
                **inputs,
                max_length=MAX_TOKENS,
                temperature=TEMPERATURE,
                do_sample=True,
                top_p=0.9
            )
        
        report = fallback_tokenizer.decode(outputs[0], skip_special_tokens=True)
        return report
    except Exception as e:
        return None


def generate_llm_report(master_json: Dict[str, Any]) -> str:
    """Generate KYC report with fallback mechanism."""
    prompt = KYC_REPORT_PROMPT.format(master_json=json.dumps(master_json, indent=2))
    
    # Try primary model (OpenAI)
    report = generate_with_openai(prompt)
    
    # Fallback to FLAN-T5 if OpenAI fails
    if report is None:
        report = generate_with_flan_t5(prompt)
    
    # Final fallback: return error message
    if report is None:
        report = "# KYC VERIFICATION REPORT\n\n**ERROR**: Failed to generate report. Both primary and fallback models encountered errors."
    
    return report
