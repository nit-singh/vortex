"""Pathway MCP server exposing the KYC verification pipeline as tools."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import pathway as pw
from pathway.xpacks.llm.mcp_server import McpServable, McpServer, PathwayMcp

pw.set_license_key("6EBD5C-32A968-0CBE85-1FA4CF-81C84C-V3")

from combined_api import (  # type: ignore
    AdditionalDetails,
    AadhaarCardInput,
    ITRDocumentInput,
    PANCardInput,
    QuestionnaireInput,
    cross_verify_documents,
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


class ReportSchema(pw.Schema):
    master_json: pw.Json


class MasterJsonReferenceSchema(pw.Schema):
    master_json_id: str = pw.column_definition(default_value="")
    master_json: pw.Json = pw.column_definition(
        dtype=pw.Json, default_value=None
    )


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


class KycMcpTools(McpServable):
    def __init__(self) -> None:
        super().__init__()
        self._encryptor = SensitiveDataEncryptor()

    def parse_documents(self, raw_inputs: pw.Table) -> pw.Table:
        @pw.udf
        def parse_udf(pan_text: str, aadhaar_text: str, itr_text: str) -> Dict[str, Any]:
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
            bundle = _bundle_from_dict(parsed_bundle)
            questionnaire_payload = _unwrap_json(questionnaire)
            additional_payload = _unwrap_json(additional_details)
            verification_payload = _unwrap_json(document_verification)
            video_payload = _unwrap_json(video_verification)

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

    def generate_report(self, master_table: pw.Table) -> pw.Table:
        @pw.udf
        def report_udf(master_json: Any) -> Dict[str, Any]:
            payload = _unwrap_json(master_json)
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
            "generate_report",
            request_handler=self.generate_report,
            schema=ReportSchema,
        )
        server.tool(
            "generate_report_from_master",
            request_handler=self.generate_report_from_reference,
            schema=MasterJsonReferenceSchema,
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
