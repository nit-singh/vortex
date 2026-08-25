"""Pathway MCP server exposing the KYC verification pipeline as tools."""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pathway as pw
from pathway.xpacks.llm.mcp_server import McpServable, McpServer, PathwayMcp

pw.set_license_key(os.getenv("PW_LKEY"))

# Add flask_server to path for alerts store
flask_server_dir = Path(__file__).resolve().parent.parent / "flask_server"
if str(flask_server_dir) not in sys.path:
    sys.path.insert(0, str(flask_server_dir))

logger = logging.getLogger(__name__)

from combined_api import (  # type: ignore
    AdditionalDetails,
    AadhaarCardInput,
    ITRDocumentInput,
    PANCardInput,
    QuestionnaireInput,
    cross_verify_documents,
)
from kyc_observability import (
    increment,
    track_latency,
    track_generation,
    trace_kyc_flow,
    accumulate_cost,
    calculate_openai_cost,
    track_tool_invocation,
)
from kyc_agent_planner import generate_alert_plan
from kyc_alerts import (
    AlertPlan,
    AlertSeverity,
    build_alert_signal,
)
from kyc_master_store import get_master_json, register_master_json
from kyc_mcp_pipeline import (
    ParsedDocumentBundle,
    SensitiveDataEncryptor,
    VerificationContext,
    build_master_and_ml_payloads,
    build_video_placeholder,
    generate_llm_report,
    parse_documents_from_texts,
    redact_sensitive_structures,
)

# Import alerts store (optional - will fail gracefully if MongoDB not available)
try:
    from pymongo import MongoClient
    # Try importing from flask_server directory
    try:
        from flask_server.alerts_store_mongo import MongoAlertsStore
    except ImportError:
        # Fallback: try direct import if flask_server is in path
        from alerts_store_mongo import MongoAlertsStore
    ALERTS_STORE_AVAILABLE = True
except ImportError as e:
    ALERTS_STORE_AVAILABLE = False
    logger.warning(f"Alerts store not available - alerts will not be persisted to MongoDB: {e}")


def _get_alerts_store() -> Optional[MongoAlertsStore]:
    """Get MongoDB alerts store instance.
    
    Returns:
        MongoAlertsStore instance or None if not available
    """
    if not ALERTS_STORE_AVAILABLE:
        return None
    
    try:
        mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        mongodb_db_name = os.getenv("MONGODB_DB_NAME", "kyc_app")
        
        client = MongoClient(mongodb_uri)
        db = client[mongodb_db_name]
        return MongoAlertsStore(db)
    except Exception as e:
        logger.warning(f"Failed to initialize alerts store: {e}")
        return None


def _store_alert_in_mongodb(
    user_id: str,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    channel: str,
    audience: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Store an alert in MongoDB.
    
    Args:
        user_id: User ID associated with the alert
        alert_type: Type of alert ("user" or "ops")
        severity: Severity level
        title: Alert title
        message: Alert message
        channel: Channel used
        audience: Target audience
        metadata: Additional metadata
    
    Returns:
        Alert ID if stored successfully, None otherwise
    """
    store = _get_alerts_store()
    if store is None:
        return None
    
    try:
        # Extract user_id from context if available
        if metadata and "context" in metadata:
            context = metadata.get("context", {})
            if isinstance(context, dict) and "user_id" in context:
                user_id = context.get("user_id", user_id)
        
        alert_id = store.create_alert(
            user_id=user_id,
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            channel=channel,
            audience=audience,
            metadata=metadata,
        )
        logger.info(f"Stored alert {alert_id} in MongoDB for user_id={user_id}")
        return alert_id
    except Exception as e:
        logger.error(f"Failed to store alert in MongoDB: {e}")
        return None


class RawDocumentSchema(pw.Schema):
    pan_text: str
    aadhaar_text: str
    itr_text: str


class ParsedBundleSchema(pw.Schema):
    parsed_bundle: pw.Json


class PayloadAssemblySchema(pw.Schema):
    parsed_bundle: pw.Json
    questionnaire: pw.Json
    additional_details: pw.Json
    document_verification: pw.Json
    video_verification: pw.Json = pw.column_definition(
        dtype=pw.Json, default_value=None
    )


class MasterJsonSchema(pw.Schema):
    master_json_id: str = pw.column_definition(default_value="")
    master_json: pw.Json = pw.column_definition(dtype=pw.Json, default_value=None)
    alert_plan: pw.Json = pw.column_definition(dtype=pw.Json, default_value=None)
    channel: str = pw.column_definition(default_value="")
    context: pw.Json = pw.column_definition(dtype=pw.Json, default_value=None)
    llm_annotations: pw.Json = pw.column_definition(dtype=pw.Json, default_value=None)


def _unwrap_json(value: Any) -> Any:
    if isinstance(value, pw.Json):
        return value.value
    return value


def _bundle_from_dict(payload: Any) -> ParsedDocumentBundle:
    data = _unwrap_json(payload)
    if not isinstance(data, dict):
        raise TypeError("Parsed document bundle must be a dict-like object.")
    return ParsedDocumentBundle(
        pan=PANCardInput(**data["pan"]),
        aadhaar=AadhaarCardInput(**data["aadhaar"]),
        itr=ITRDocumentInput(**data["itr"]),
    )


def _load_master_json_payload(master_json_id: str, master_json: Any) -> Dict[str, Any]:
    payload = _unwrap_json(master_json)
    if master_json_id:
        stored = get_master_json(master_json_id)
        if stored is None and payload is None:
            raise ValueError(f"Master JSON not found for id: {master_json_id}")
        if stored is not None:
            payload = stored
    if payload is None:
        raise ValueError("Provide either master_json_id or master_json.")
    if not isinstance(payload, dict):
        raise TypeError("master_json payload must be a JSON object.")
    return payload


def _sanitize_llm_annotations(raw_annotations: Any) -> List[str]:
    if not raw_annotations:
        return []

    items = raw_annotations
    if isinstance(items, dict):
        preferred_keys = ("notes", "annotations", "items", "values")
        selected: Any = None
        for key in preferred_keys:
            if key in items:
                selected = items[key]
                break
        if selected is None:
            selected = list(items.values())
        items = selected

    if isinstance(items, str):
        items = [items]
    elif isinstance(items, (list, tuple)):
        items = list(items)
    else:
        items = [items]

    annotations: List[str] = []
    for note in items:
        if not isinstance(note, str):
            continue
        sanitized = redact_sensitive_structures(note)
        if sanitized:
            annotations.append(str(sanitized))
    return annotations


class KycMcpTools(McpServable):
    def __init__(self) -> None:
        super().__init__()
        self._encryptor = SensitiveDataEncryptor()

    def parse_documents(self, raw_inputs: pw.Table) -> pw.Table:
        @pw.udf
        def parse_udf(pan_text: str, aadhaar_text: str, itr_text: str) -> Dict[str, Any]:
            meta = {
                "pan_present": bool(pan_text),
                "aadhaar_present": bool(aadhaar_text),
                "itr_present": bool(itr_text),
            }
            with track_tool_invocation("kycv.parse_documents", metadata=meta):
                bundle = parse_documents_from_texts(pan_text, aadhaar_text, itr_text)
                return {
                    "pan": bundle.pan.dict(),
                    "aadhaar": bundle.aadhaar.dict(),
                    "itr": bundle.itr.dict(),
                }

        return raw_inputs.select(
            result=parse_udf(pw.this.pan_text, pw.this.aadhaar_text, pw.this.itr_text)
        )

    def verify_documents(self, parsed_table: pw.Table) -> pw.Table:
        @pw.udf
        def verify_udf(parsed_bundle: Any) -> Dict[str, Any]:
            bundle_payload = _unwrap_json(parsed_bundle)
            meta = {"bundle_keys": list(bundle_payload.keys()) if isinstance(bundle_payload, dict) else []}
            with track_tool_invocation("kycv.verify_documents", metadata=meta):
                bundle = _bundle_from_dict(bundle_payload)
                verification_results = cross_verify_documents(
                    bundle.pan, bundle.aadhaar, bundle.itr
                )
                return {
                    "parsed_bundle": bundle_payload,
                    "document_verification": redact_sensitive_structures(verification_results),
                }

        return parsed_table.select(result=verify_udf(pw.this.parsed_bundle))

    def assemble_payloads(self, payload_table: pw.Table) -> pw.Table:
        @pw.udf
        def assemble_udf(
            parsed_bundle: Any,
            questionnaire: Any,
            additional_details: Any,
            document_verification: Any,
            video_verification: Any,
        ) -> Dict[str, Any]:
            questionnaire_payload = _unwrap_json(questionnaire)
            additional_payload = _unwrap_json(additional_details)
            verification_payload = _unwrap_json(document_verification)
            video_payload = _unwrap_json(video_verification)

            meta = {
                "questionnaire_fields": list((questionnaire_payload or {}).keys()),
                "has_additional": bool(additional_payload),
            }

            with track_tool_invocation("kycv.assemble_payloads", metadata=meta):
                bundle = _bundle_from_dict(parsed_bundle)
                questionnaire_model = QuestionnaireInput(**questionnaire_payload)
                additional_model = AdditionalDetails(**additional_payload)
                video = video_payload or build_video_placeholder()
                ctx = VerificationContext(
                    parsed=bundle,
                    questionnaire=questionnaire_model,
                    additional=additional_model,
                    video_verification=video,
                )
                master_json, ml_input_json = build_master_and_ml_payloads(
                    ctx,
                    self._encryptor,
                    precomputed_document_verification=verification_payload,
                )
                master_json_id = register_master_json(master_json)
                return {
                    "master_json": master_json,
                    "ml_input_json": ml_input_json,
                    "master_json_id": master_json_id,
                }

        return payload_table.select(
            result=assemble_udf(
                pw.this.parsed_bundle,
                pw.this.questionnaire,
                pw.this.additional_details,
                pw.this.document_verification,
                pw.this.video_verification,
            )
        )

    def plan_alerts(self, master_table: pw.Table) -> pw.Table:
        @pw.udf
        def planner_udf(master_json_id: str, master_json: Any, llm_annotations: Any) -> Dict[str, Any]:
            import logging
            logger = logging.getLogger(__name__)
            
            try:
                logger.debug("plan_alerts called with master_json_id=%s, master_json type=%s", 
                            master_json_id, type(master_json).__name__)
                
                payload = _load_master_json_payload(master_json_id, master_json)
                logger.debug("Loaded payload keys: %s", list(payload.keys()) if isinstance(payload, dict) else "not a dict")
                
                doc_payload = payload.get("document_verification_details")
                if doc_payload is None:
                    error_msg = f"master_json missing document_verification_details. Available keys: {list(payload.keys())}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                
                doc_payload = redact_sensitive_structures(doc_payload)
                video_payload = payload.get("video_verification_details") or build_video_placeholder()
                video_payload = redact_sensitive_structures(video_payload)
                
                meta = {
                    "master_json_id": master_json_id,
                    "has_annotations": bool(llm_annotations),
                }
                
                with track_tool_invocation("kycv.plan_alerts", metadata=meta):
                    with track_latency("mcp.plan_alerts", master_json_id=master_json_id or ""):
                        try:
                            signal = build_alert_signal(
                                master_json_id or None,
                                doc_payload,
                                video_payload,
                            )
                            logger.debug("Alert signal built successfully")
                        except Exception as e:
                            logger.error("Failed to build_alert_signal: %s", e, exc_info=True)
                            raise
                        
                        annotations = _sanitize_llm_annotations(llm_annotations)
                        if annotations:
                            signal.notes.extend(annotations)
                        
                        try:
                            plan = generate_alert_plan(signal)
                            logger.debug("Alert plan generated successfully")
                        except Exception as e:
                            logger.error("Failed to generate_alert_plan: %s", e, exc_info=True)
                            raise
                
                increment(
                    "alert.plan.generated",
                    severity=plan.severity.value,
                )
                
                try:
                    result = {
                        "master_json_id": master_json_id,
                        "signal": signal.to_dict(),
                        "plan": plan.to_dict(),
                    }
                    logger.debug("plan_alerts returning result with keys: %s", list(result.keys()))
                    return result
                except Exception as e:
                    logger.error("Failed to convert signal/plan to dict: %s", e, exc_info=True)
                    raise
                    
            except Exception as e:
                error_msg = f"plan_alerts UDF failed: {type(e).__name__}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                # Re-raise with more context
                raise RuntimeError(error_msg) from e

        return master_table.select(
            result=planner_udf(
                pw.this.master_json_id,
                pw.this.master_json,
                pw.this.llm_annotations,
            )
        )

    def dispatch_user_alert(self, payload_table: pw.Table) -> pw.Table:
        @pw.udf
        def dispatch_udf(alert_plan: Any, channel: str, context: Any) -> Dict[str, Any]:
            plan_payload = _unwrap_json(alert_plan)
            plan = AlertPlan.from_payload(plan_payload)
            if not plan.user_targets:
                raise ValueError("No user targets configured in alert plan")
            target = plan.user_targets[0]
            channel_to_use = channel or target.channel
            if plan.severity == AlertSeverity.CRITICAL and channel_to_use == "email":
                raise ValueError("Critical alerts require a real-time channel")
            meta = {
                "severity": plan.severity.value,
                "channel": channel_to_use,
                "audience": target.audience,
            }
            with track_tool_invocation("kycv.dispatch_user_alert", metadata=meta):
                with track_latency("mcp.dispatch_user_alert", channel=channel_to_use):
                    increment(
                        "alert.dispatched",
                        audience=target.audience,
                        channel=channel_to_use,
                    )
                
                # Extract user_id from context
                context_dict = _unwrap_json(context)
                user_id = context_dict.get("user_id", "") if isinstance(context_dict, dict) else ""
                
                # Generate alert title and message
                severity_display = plan.severity.value.upper()
                title = f"KYC Alert - {severity_display}"
                message = target.instructions or f"KYC verification alert: {severity_display} severity"
                
                # Store alert in MongoDB
                alert_metadata = {
                    "alert_plan": plan_payload,
                    "context": context_dict,
                    "channel": channel_to_use,
                }
                alert_id = _store_alert_in_mongodb(
                    user_id=user_id,
                    alert_type="user",
                    severity=plan.severity.value,
                    title=title,
                    message=message,
                    channel=channel_to_use,
                    audience=target.audience,
                    metadata=alert_metadata,
                )
                
                return {
                    "dispatched": True,
                    "channel": channel_to_use,
                    "audience": target.audience,
                    "instructions": target.instructions,
                    "context": context_dict,
                    "alert_id": alert_id,  # Include alert ID if stored
                }

        return payload_table.select(
            result=dispatch_udf(
                pw.this.alert_plan,
                pw.this.channel,
                pw.this.context,
            )
        )

    def dispatch_ops_alert(self, payload_table: pw.Table) -> pw.Table:
        @pw.udf
        def dispatch_udf(alert_plan: Any, channel: str, context: Any) -> Dict[str, Any]:
            plan_payload = _unwrap_json(alert_plan)
            plan = AlertPlan.from_payload(plan_payload)
            if not plan.ops_targets:
                raise ValueError("No ops targets configured in alert plan")
            target = plan.ops_targets[0]
            channel_to_use = channel or target.channel
            if plan.severity in {AlertSeverity.MAJOR, AlertSeverity.CRITICAL} and channel_to_use not in {"pagerduty", "slack", "sms"}:
                raise ValueError("High severity alerts must use a monitored ops channel")
            requires_human = plan.requires_human_review
            meta = {
                "severity": plan.severity.value,
                "channel": channel_to_use,
                "audience": target.audience,
            }
            with track_tool_invocation("kycv.dispatch_ops_alert", metadata=meta):
                with track_latency("mcp.dispatch_ops_alert", channel=channel_to_use):
                    increment(
                        "alert.ops_dispatched",
                        audience=target.audience,
                        channel=channel_to_use,
                        severity=plan.severity.value,
                    )
                
                # Extract user_id from context
                context_dict = _unwrap_json(context)
                user_id = context_dict.get("user_id", "") if isinstance(context_dict, dict) else ""
                
                # Generate alert title and message
                severity_display = plan.severity.value.upper()
                title = f"KYC Ops Alert - {severity_display}"
                message = target.instructions or f"KYC verification alert requiring ops attention: {severity_display} severity"
                if requires_human:
                    message += " (Requires human review)"
                
                # Store alert in MongoDB
                alert_metadata = {
                    "alert_plan": plan_payload,
                    "context": context_dict,
                    "channel": channel_to_use,
                    "requires_human_review": requires_human,
                }
                alert_id = _store_alert_in_mongodb(
                    user_id=user_id,
                    alert_type="ops",
                    severity=plan.severity.value,
                    title=title,
                    message=message,
                    channel=channel_to_use,
                    audience=target.audience,
                    metadata=alert_metadata,
                )
                
                return {
                    "dispatched": True,
                    "channel": channel_to_use,
                    "audience": target.audience,
                    "instructions": target.instructions,
                    "requires_human_review": requires_human,
                    "context": context_dict,
                    "alert_id": alert_id,  # Include alert ID if stored
                }

        return payload_table.select(
            result=dispatch_udf(
                pw.this.alert_plan,
                pw.this.channel,
                pw.this.context,
            )
        )

    def generate_report(self, master_table: pw.Table) -> pw.Table:
        @pw.udf
        def report_udf(master_json: Any) -> Dict[str, Any]:
            payload = _unwrap_json(master_json)
            meta = {
                "contains_verification_status": bool((payload or {}).get("verification_status")) if isinstance(payload, dict) else False,
            }
            with track_tool_invocation("kycv.generate_report", metadata=meta):
                return {"report": generate_llm_report(payload)}

        return master_table.select(result=report_udf(pw.this.master_json))

    def generate_report_from_reference(self, reference_table: pw.Table) -> pw.Table:
        @pw.udf
        def reference_udf(
            master_json_id: str,
            master_json: Any,
        ) -> Dict[str, Any]:
            payload = _unwrap_json(master_json)
            if master_json_id:
                stored = get_master_json(master_json_id)
                if stored is None:
                    raise ValueError(f"Master JSON not found for id: {master_json_id}")
                payload = stored
            if payload is None:
                raise ValueError("Provide either master_json_id or master_json.")
            meta = {"master_json_id": master_json_id}
            with track_tool_invocation("kycv.generate_report_from_master", metadata=meta):
                return {"report": generate_llm_report(payload)}

        return reference_table.select(
            result=reference_udf(pw.this.master_json_id, pw.this.master_json)
        )

    def register_mcp(self, server: McpServer) -> None:
        server.tool(
            "parse_documents",
            request_handler=self.parse_documents,
            schema=RawDocumentSchema,
        )
        server.tool(
            "verify_documents",
            request_handler=self.verify_documents,
            schema=ParsedBundleSchema,
        )
        server.tool(
            "assemble_payloads",
            request_handler=self.assemble_payloads,
            schema=PayloadAssemblySchema,
        )
        server.tool(
            "plan_alerts",
            request_handler=self.plan_alerts,
            schema=MasterJsonSchema,
        )
        server.tool(
            "dispatch_user_alert",
            request_handler=self.dispatch_user_alert,
            schema=MasterJsonSchema,
        )
        server.tool(
            "dispatch_ops_alert",
            request_handler=self.dispatch_ops_alert,
            schema=MasterJsonSchema,
        )
        server.tool(
            "generate_report",
            request_handler=self.generate_report,
            schema=MasterJsonSchema,
        )
        server.tool(
            "generate_report_from_master",
            request_handler=self.generate_report_from_reference,
            schema=MasterJsonSchema,
        )


def build_server() -> PathwayMcp:
    tools = KycMcpTools()
    return PathwayMcp(
        name="KYC Verification MCP Server",
        transport="streamable-http",
        host=os.getenv("KYC_MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("KYC_MCP_PORT", "8123")),
        serve=[tools],
    )


kyc_mcp_server = build_server()


if __name__ == "__main__":
    pw.run(monitoring_level=pw.MonitoringLevel.NONE, terminate_on_error=False)
