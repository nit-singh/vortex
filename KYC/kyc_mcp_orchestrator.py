"""Async orchestrator for the KYC Pathway MCP server using only master payloads.

Example usage:

    python kyc_mcp_orchestrator.py \
        --mcp-url http://localhost:8123/mcp/ \
        --master-json-file master_payload.json \
        --plan-alerts --dispatch-user-alert --dispatch-ops-alert
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from fastmcp import Client
except ImportError as exc:  # pragma: no cover - convenience guard
    raise SystemExit("Install fastmcp with `pip install fastmcp`." ) from exc


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class KycMcpOrchestrator:
    """Thin async wrapper above the FastMCP client."""

    def __init__(self, mcp_url: str):
        self._client = Client(mcp_url)

    async def __aenter__(self) -> "KycMcpOrchestrator":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401 - protocol-mandated signature
        await self._client.__aexit__(exc_type, exc, tb)

    async def list_tools(self) -> Any:
        return await self._client.list_tools()

    async def parse_documents(self, payload: Dict[str, Any]) -> Any:
        return await self._client.call_tool(name="parse_documents", arguments=payload)

    async def verify_documents(self, parsed_bundle: Dict[str, Any]) -> Any:
        return await self._client.call_tool(
            name="verify_documents",
            arguments={"parsed_bundle": parsed_bundle},
        )

    async def assemble_payloads(
        self,
        parsed_bundle: Dict[str, Any],
        questionnaire: Dict[str, Any],
        additional_details: Dict[str, Any],
        document_verification: Dict[str, Any],
        video_verification: Optional[Dict[str, Any]] = None,
    ) -> Any:
        payload = {
            "parsed_bundle": parsed_bundle,
            "questionnaire": questionnaire,
            "additional_details": additional_details,
            "document_verification": document_verification,
            "video_verification": video_verification,
        }
        return await self._client.call_tool(name="assemble_payloads", arguments=payload)

    async def generate_report(self, master_json: Dict[str, Any]) -> Any:
        return await self._client.call_tool(
            name="generate_report",
            arguments={"master_json": master_json},
        )

    async def plan_alerts(self, payload: Dict[str, Any]) -> Any:
        return await self._client.call_tool(
            name="plan_alerts",
            arguments=payload,
        )

    async def dispatch_user_alert(self, payload: Dict[str, Any]) -> Any:
        return await self._client.call_tool(
            name="dispatch_user_alert",
            arguments=payload,
        )

    async def dispatch_ops_alert(self, payload: Dict[str, Any]) -> Any:
        return await self._client.call_tool(
            name="dispatch_ops_alert",
            arguments=payload,
        )

    async def generate_report_from_store(
        self,
        master_json_id: Optional[str] = None,
        master_json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        payload: Dict[str, Any] = {}
        if master_json_id is not None:
            payload["master_json_id"] = master_json_id
        if master_json is not None:
            payload["master_json"] = master_json
        return await self._client.call_tool(
            name="generate_report_from_master",
            arguments=payload,
        )


def _maybe_parse_response(response: Any) -> Any:
    if response is None:
        return None

    if isinstance(response, str):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return response

    if isinstance(response, list) and len(response) == 1:
        return _maybe_parse_response(response[0])

    if isinstance(response, dict):
        if "result" in response and len(response) == 1:
            return _maybe_parse_response(response["result"])  # unwrap
        if "content" in response:
            return _maybe_parse_response(response["content"])

    for attr in ("structured_content", "data", "result", "content", "text"):
        if hasattr(response, attr):
            return _maybe_parse_response(getattr(response, attr))

    return response


def _extract_payload(response: Any) -> Any:
    parsed = _maybe_parse_response(response)
    if isinstance(parsed, dict) and "result" in parsed:
        return parsed["result"]
    return parsed


def _extract_plan_dict(plan_response: Any) -> Optional[Dict[str, Any]]:
    parsed = _maybe_parse_response(plan_response)

    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return None

    if isinstance(parsed, dict):
        if "plan" in parsed and isinstance(parsed["plan"], dict):
            return parsed["plan"]
        if "result" in parsed:
            return _extract_plan_dict(parsed["result"])
        if "structured_content" in parsed:
            return _extract_plan_dict(parsed["structured_content"])
        if "data" in parsed:
            return _extract_plan_dict(parsed["data"])

    if isinstance(parsed, list) and parsed:
        return _extract_plan_dict(parsed[0])

    for attr in ("structured_content", "data", "result", "content", "text"):
        if hasattr(parsed, attr):
            return _extract_plan_dict(getattr(parsed, attr))

    return None


def _read_json_argument(arg_json: Optional[str], file_path: Optional[str], fallback: Dict[str, Any]) -> Dict[str, Any]:
    if arg_json:
        return json.loads(arg_json)
    if file_path:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"JSON file not found: {file_path}")
        return json.loads(path.read_text())
    return fallback


def _load_master_json_argument(arg_json: Optional[str], file_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if arg_json:
        return json.loads(arg_json)
    if file_path:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Master JSON file not found: {file_path}")
        return json.loads(path.read_text())
    return None


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="End-to-end orchestrator for the KYC MCP server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mcp-url",
        default="http://127.0.0.1:8123/mcp/",
        help="Base MCP endpoint",
    )
    parser.add_argument(
        "--master-json-id",
        help="Existing master_json identifier registered via FastAPI or prior MCP calls",
    )
    parser.add_argument(
        "--master-json-json",
        help="Inline JSON payload containing a master_json object",
    )
    parser.add_argument(
        "--master-json-file",
        help="Path to a JSON file containing a master_json payload",
    )
    parser.add_argument(
        "--generate-report",
        action="store_true",
        help="Invoke the report generator with the provided master payload",
    )
    parser.add_argument(
        "--plan-alerts",
        action="store_true",
        help="Invoke alert planner with the provided master payload",
    )
    parser.add_argument(
        "--dispatch-user-alert",
        action="store_true",
        help="Dispatch the user-facing alert target after planning",
    )
    parser.add_argument(
        "--dispatch-ops-alert",
        action="store_true",
        help="Dispatch the ops-facing alert target after planning",
    )
    parser.add_argument(
        "--user-alert-channel",
        default="",
        help="Override user alert channel (default uses plan target)",
    )
    parser.add_argument(
        "--ops-alert-channel",
        default="",
        help="Override ops alert channel (default uses plan target)",
    )
    parser.add_argument(
        "--skip-user-dispatch",
        action="store_true",
        help="Prevent automatic user dispatch even if the LLM plan includes targets",
    )
    parser.add_argument(
        "--skip-ops-dispatch",
        action="store_true",
        help="Prevent automatic ops dispatch even if the LLM plan includes targets",
    )
    parser.add_argument(
        "--context-json",
        help="Inline JSON forwarded as the context payload to dispatch tools",
    )
    parser.add_argument(
        "--context-file",
        help="Path to JSON file forwarded as the dispatch context",
    )
    parser.add_argument(
        "--llm-note",
        action="append",
        help="Optional annotation(s) the LLM would add to the alert signal",
    )
    return parser


async def orchestrate(args: argparse.Namespace) -> None:
    master_json_payload = _load_master_json_argument(
        args.master_json_json,
        args.master_json_file,
    )

    if master_json_payload is None and not args.master_json_id:
        raise SystemExit("Provide --master-json-file/--master-json-json or --master-json-id")

    # Default to generating a report and planning alerts if no explicit action is requested.
    if not any(
        [
            args.generate_report,
            args.plan_alerts,
            args.dispatch_user_alert,
            args.dispatch_ops_alert,
        ]
    ):
        logger.info(
            "No action flags supplied; defaulting to --generate-report and --plan-alerts"
        )
        args.generate_report = True
        args.plan_alerts = True

    user_dispatch_requested = not args.skip_user_dispatch
    ops_dispatch_requested = not args.skip_ops_dispatch
    if args.dispatch_user_alert:
        user_dispatch_requested = True
    if args.dispatch_ops_alert:
        ops_dispatch_requested = True

    default_context = {"master_json_id": args.master_json_id or ""}
    context_payload = _read_json_argument(
        args.context_json,
        args.context_file,
        default_context,
    )

    async with KycMcpOrchestrator(args.mcp_url) as orchestrator:
        tools = await orchestrator.list_tools()
        logger.info("Available KYC MCP tools: %s", tools)

        if args.generate_report:
            logger.info("Calling generate_report_from_master")
            report_resp = await orchestrator.generate_report_from_store(
                master_json_id=args.master_json_id,
                master_json=master_json_payload,
            )
            logger.info(
                "generate_report_from_master -> %s",
                _maybe_parse_response(report_resp),
            )

        needs_plan = args.plan_alerts or user_dispatch_requested or ops_dispatch_requested
        plan_dict: Optional[Dict[str, Any]] = None

        if needs_plan:
            annotations_payload: Dict[str, Any] = {}
            if args.llm_note:
                annotations_payload = {"notes": args.llm_note}

            verification_event: Dict[str, Any] = {
                "master_json_id": args.master_json_id or "",
                "llm_annotations": annotations_payload,
            }
            if master_json_payload is not None:
                verification_event["master_json"] = master_json_payload

            logger.info("Calling plan_alerts")
            plan_resp = await orchestrator.plan_alerts(verification_event)
            plan_raw = _maybe_parse_response(plan_resp)
            logger.info("plan_alerts -> %s", plan_raw)

            plan_dict = _extract_plan_dict(plan_raw)
            if plan_dict is None:
                raise RuntimeError("plan_alerts did not return a plan payload")

        if user_dispatch_requested:
            user_targets = plan_dict.get("user_targets") if plan_dict else None
            if not user_targets:
                logger.info(
                    "Alert plan contained no user targets; user dispatch skipped"
                )
            else:
                dispatch_payload = {
                    "alert_plan": plan_dict,
                    "channel": args.user_alert_channel,
                    "context": context_payload,
                    "master_json_id": args.master_json_id or "",
                }
                logger.info("dispatch_user_alert -> sending")
                user_alert_resp = await orchestrator.dispatch_user_alert(dispatch_payload)
                logger.info(
                    "dispatch_user_alert -> %s",
                    _maybe_parse_response(user_alert_resp),
                )

        if ops_dispatch_requested:
            ops_targets = plan_dict.get("ops_targets") if plan_dict else None
            if not ops_targets:
                logger.info(
                    "Alert plan contained no ops targets; ops dispatch skipped"
                )
            else:
                dispatch_payload = {
                    "alert_plan": plan_dict,
                    "channel": args.ops_alert_channel,
                    "context": context_payload,
                    "master_json_id": args.master_json_id or "",
                }
                logger.info("dispatch_ops_alert -> sending")
                ops_alert_resp = await orchestrator.dispatch_ops_alert(dispatch_payload)
                logger.info(
                    "dispatch_ops_alert -> %s",
                    _maybe_parse_response(ops_alert_resp),
                )


def main() -> None:
    parser = _build_cli()
    args = parser.parse_args()
    asyncio.run(orchestrate(args))


if __name__ == "__main__":
    main()
