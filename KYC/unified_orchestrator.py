"""Unified KYC Orchestrator - Coordinates KYCV and RiskScore MCP servers.

This orchestrator:
1. Fetches overall payload (master_json + ml_input_json) from database by user_id
2. Calls KYCV MCP server with master_json for report generation, alerts, etc.
3. Uses LLM to decide which additional tools to execute
4. Calls RiskScore MCP server with ml_input_json for risk scoring
5. Updates the database with results

Usage (CLI):
    python unified_orchestrator.py --user-id USER123 --kycv-url http://localhost:8123/mcp/ --risk-url http://localhost:8124/mcp/

Usage (Programmatic):
    from unified_orchestrator import UnifiedOrchestrator
    
    async with UnifiedOrchestrator() as orchestrator:
        result = await orchestrator.run(user_id="USER123")
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastmcp import Client
except ImportError as exc:
    raise SystemExit("Install fastmcp: pip install fastmcp") from exc

from payload_store import (
    PayloadStore,
    OverallPayload,
    get_payload_store,
    get_overall_payload,
)
from llm_tool_selector import (
    LLMToolSelector,
    RuleBasedToolSelector,
    ToolAction,
    ToolCategory,
    filter_valid_actions,
)

# Import observability
try:
    from kyc_observability import (
        trace_kyc_flow,
        track_generation,
        increment,
        observe_latency,
        accumulate_cost,
        get_cost_summary,
        shutdown_langfuse,
    )
    OBSERVABILITY_ENABLED = True
except ImportError:
    OBSERVABILITY_ENABLED = False
    trace_kyc_flow = None
    track_generation = None

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class OrchestratorConfig:
    """Configuration for the unified orchestrator."""
    kycv_mcp_url: str = "http://127.0.0.1:8123/mcp/"
    risk_mcp_url: str = "http://127.0.0.1:8124/mcp/"
    risk_artifact_dir: str = os.path.join(os.path.dirname(__file__), "risk_artifacts")
    use_llm_selector: bool = True
    openai_api_key: Optional[str] = None
    max_retries: int = 3
    timeout_seconds: int = 60


@dataclass
class OrchestrationResult:
    """Result of an orchestration run."""
    user_id: str
    task_id: str
    status: str  # success, partial, failed
    kycv_report: Optional[str] = None
    alert_plan: Optional[Dict[str, Any]] = None
    risk_score: Optional[Dict[str, Any]] = None
    actions_executed: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "task_id": self.task_id,
            "status": self.status,
            "kycv_report": self.kycv_report,
            "alert_plan": self.alert_plan,
            "risk_score": self.risk_score,
            "actions_executed": self.actions_executed,
            "errors": self.errors,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# ============================================================================
# MCP Client Wrappers
# ============================================================================

class KycvMcpClient:
    """Async client wrapper for KYCV MCP server."""
    
    def __init__(self, mcp_url: str):
        self._url = mcp_url
        self._client = Client(mcp_url)
    
    async def __aenter__(self) -> "KycvMcpClient":
        await self._client.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.__aexit__(exc_type, exc, tb)
    
    async def list_tools(self) -> Any:
        return await self._client.list_tools()
    
    async def generate_report(self, master_json: Dict[str, Any]) -> Any:
        return await self._client.call_tool(
            name="generate_report",
            arguments={"master_json": master_json}
        )
    
    async def generate_report_from_master(
        self,
        master_json_id: Optional[str] = None,
        master_json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        payload: Dict[str, Any] = {}
        if master_json_id:
            payload["master_json_id"] = master_json_id
        if master_json:
            payload["master_json"] = master_json
        return await self._client.call_tool(
            name="generate_report_from_master",
            arguments=payload
        )
    
    async def plan_alerts(
        self,
        master_json: Optional[Dict[str, Any]] = None,
        master_json_id: Optional[str] = None,
        llm_annotations: Optional[Dict[str, Any]] = None,
    ) -> Any:
        import logging
        logger = logging.getLogger(__name__)
        
        payload: Dict[str, Any] = {"master_json_id": master_json_id or ""}
        if master_json:
            payload["master_json"] = master_json
            logger.debug("plan_alerts payload has master_json with keys: %s", 
                        list(master_json.keys()) if isinstance(master_json, dict) else "not a dict")
        if llm_annotations:
            payload["llm_annotations"] = llm_annotations
        
        try:
            response = await self._client.call_tool(name="plan_alerts", arguments=payload)
            logger.debug("plan_alerts call_tool returned: type=%s, value=%s", type(response), response)
            return response
        except Exception as e:
            logger.error("plan_alerts call_tool raised exception: %s (type=%s)", e, type(e).__name__, exc_info=True)
            raise
    
    async def dispatch_user_alert(
        self,
        alert_plan: Dict[str, Any],
        channel: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return await self._client.call_tool(
            name="dispatch_user_alert",
            arguments={
                "alert_plan": alert_plan,
                "channel": channel,
                "context": context or {},
                "master_json_id": "",
            }
        )
    
    async def dispatch_ops_alert(
        self,
        alert_plan: Dict[str, Any],
        channel: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return await self._client.call_tool(
            name="dispatch_ops_alert",
            arguments={
                "alert_plan": alert_plan,
                "channel": channel,
                "context": context or {},
                "master_json_id": "",
            }
        )


class RiskMcpClient:
    """Async client wrapper for RiskScore MCP server."""
    
    def __init__(self, mcp_url: str):
        self._url = mcp_url
        self._client = Client(mcp_url)
    
    async def __aenter__(self) -> "RiskMcpClient":
        await self._client.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.__aexit__(exc_type, exc, tb)
    
    async def list_tools(self) -> Any:
        return await self._client.list_tools()
    
    async def load_artifacts(
        self,
        artifact_dir: str,
        use_offline_centroids: bool = True,
    ) -> Any:
        return await self._client.call_tool(
            name="load_artifacts",
            arguments={
                "artifact_dir": artifact_dir,
                "use_offline_centroids": use_offline_centroids,
            }
        )
    
    async def score_online(
        self,
        user: Dict[str, Any],
        update: bool = False,
    ) -> Any:
        return await self._client.call_tool(
            name="score_online",
            arguments={"user": user, "update": update}
        )
    
    async def score_offline(self, user: Dict[str, Any]) -> Any:
        return await self._client.call_tool(
            name="score_offline",
            arguments={"user": user}
        )
    
    async def get_status(self) -> Any:
        return await self._client.call_tool(name="get_status", arguments={})
    
    async def get_risk_ranges(self) -> Any:
        return await self._client.call_tool(name="get_risk_ranges", arguments={})


# ============================================================================
# Response Parsing Utilities
# ============================================================================

def _maybe_parse_response(response: Any) -> Any:
    """Best-effort parsing of MCP tool responses."""
    if response is None:
        return None
    
    # Handle string responses
    if isinstance(response, str):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return response
    
    # Handle list of one element
    if isinstance(response, list) and len(response) == 1:
        return _maybe_parse_response(response[0])
    
    # Handle dict responses
    if isinstance(response, dict):
        if "result" in response and len(response) == 1:
            return _maybe_parse_response(response["result"])
        if "content" in response:
            return _maybe_parse_response(response["content"])
        if "text" in response:
            return _maybe_parse_response(response["text"])
    
    # Handle MCP CallToolResult objects with content attribute
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, list) and len(content) > 0:
            first_content = content[0]
            # Handle TextContent objects
            if hasattr(first_content, "text"):
                text = first_content.text
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
            return _maybe_parse_response(first_content)
        return _maybe_parse_response(content)
    
    # Try common attributes
    for attr in ("structured_content", "data", "result", "text"):
        if hasattr(response, attr):
            val = getattr(response, attr)
            if val is not None:
                return _maybe_parse_response(val)
    
    return response
    
    return response


def _extract_report(response: Any) -> Optional[str]:
    """Extract report text from response."""
    parsed = _maybe_parse_response(response)
    if isinstance(parsed, dict):
        return parsed.get("report")
    return None


def _extract_plan(response: Any) -> Optional[Dict[str, Any]]:
    """Extract alert plan from response."""
    parsed = _maybe_parse_response(response)
    if isinstance(parsed, dict):
        # Check for error responses
        if "error" in parsed:
            logger.warning("plan_alerts returned error: %s", parsed.get("error"))
            return None
        if "plan" in parsed:
            return parsed["plan"]
        return parsed
    return None


def _extract_risk_score(response: Any) -> Optional[Dict[str, Any]]:
    """Extract risk score from response."""
    parsed = _maybe_parse_response(response)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        try:
            return json.loads(parsed)
        except json.JSONDecodeError:
            pass
    return None


# ============================================================================
# Unified Orchestrator
# ============================================================================

class UnifiedOrchestrator:
    """
    Unified orchestrator that coordinates KYCV and RiskScore MCP servers.
    
    Flow:
    1. Fetch payload from database by user_id
    2. Connect to KYCV MCP server
    3. Generate report from master_json
    4. Plan and dispatch alerts based on verification status
    5. Use LLM (or rules) to decide additional actions
    6. Connect to RiskScore MCP server
    7. Score risk using ml_input_json
    8. Update database with results
    """
    
    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.config = config or OrchestratorConfig()
        self._kycv_client: Optional[KycvMcpClient] = None
        self._risk_client: Optional[RiskMcpClient] = None
        self._store = get_payload_store()
        
        # Initialize tool selector
        if self.config.use_llm_selector:
            self._tool_selector = LLMToolSelector(
                api_key=self.config.openai_api_key
            )
        else:
            self._tool_selector = RuleBasedToolSelector()
    
    async def __aenter__(self) -> "UnifiedOrchestrator":
        return self
    
    async def __aexit__(self, exc_type, exc, tb) -> None:
        pass
    
    async def run(
        self,
        user_id: str,
        task_id: Optional[str] = None,
        run_kycv: bool = True,
        run_risk_score: bool = True,
        generate_report: bool = True,
        plan_alerts: bool = True,
    ) -> OrchestrationResult:
        """
        Run the full orchestration flow for a user.
        
        Args:
            user_id: User ID to process
            task_id: Optional task ID for tracking
            run_kycv: Whether to call KYCV MCP server
            run_risk_score: Whether to call RiskScore MCP server
            generate_report: Whether to generate KYC report
            plan_alerts: Whether to plan and dispatch alerts
        
        Returns:
            OrchestrationResult with all outputs
        """
        task_id = task_id or f"orch-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Use Langfuse tracing if available
        trace_context = None
        if OBSERVABILITY_ENABLED and trace_kyc_flow:
            trace_context = trace_kyc_flow(user_id=user_id, metadata={"task_id": task_id})
            trace_context.__enter__()
        
        result = OrchestrationResult(
            user_id=user_id,
            task_id=task_id,
            status="processing",
            started_at=datetime.utcnow().isoformat(),
        )
        
        try:
            # Track start
            if OBSERVABILITY_ENABLED:
                increment("orchestrations_started")
            
            # 1. Fetch payload from database
            payload = self._store.get(user_id)
            if payload is None:
                raise ValueError(f"Payload not found for user_id: {user_id}")
            
            master_json = payload.master_json
            ml_input_json = payload.ml_input_json
            
            logger.info("Fetched payload for user_id=%s", user_id)
            
            # Update status
            self._store.update_status(user_id, "processing", {"task_id": task_id})
            
            # 2. KYCV MCP Server operations
            if run_kycv:
                await self._run_kycv_operations(
                    result=result,
                    master_json=master_json,
                    generate_report=generate_report,
                    plan_alerts=plan_alerts,
                )
            
            # 3. LLM/Rule-based tool selection for additional actions
            context = {
                "master_json": master_json,
                "ml_input_json": ml_input_json,
                "kycv_report": result.kycv_report,
                "alert_plan": result.alert_plan,
            }
            
            options = {
                "generate_report": False,  # Already done if requested
                "plan_alerts": False,  # Already done if requested
                "run_risk_score": run_risk_score,
                "dispatch_alerts": plan_alerts,
            }
            
            if isinstance(self._tool_selector, LLMToolSelector):
                # Filter to only risk-related tools since KYCV is done
                additional_actions = await self._tool_selector.decide_tools(
                    context=context,
                    available_tools=["score_online", "score_offline", "get_status"]
                )
            else:
                additional_actions = self._tool_selector.decide_tools(context, options)
            
            # Filter to only risk tools (KYCV already handled)
            additional_actions = [
                a for a in additional_actions
                if a.category == ToolCategory.RISK
            ]
            
            logger.info("LLM/Rules decided %d additional actions", len(additional_actions))
            
            # 4. RiskScore MCP Server operations
            if run_risk_score:
                await self._run_risk_operations(
                    result=result,
                    ml_input_json=ml_input_json,
                )
            
            # 5. Execute any additional actions from tool selector
            for action in additional_actions:
                if action.tool_name not in ["score_online", "score_offline"]:
                    # Already handled scoring above
                    await self._execute_additional_action(result, action)
            
            # 6. Update final status
            if result.errors:
                result.status = "partial" if (result.kycv_report or result.risk_score) else "failed"
            else:
                result.status = "success"
            
            result.completed_at = datetime.utcnow().isoformat()
            
            # Update database
            self._store.update_status(
                user_id,
                "completed" if result.status == "success" else result.status,
                {
                    "task_id": task_id,
                    "orchestration_result": result.to_dict(),
                }
            )
            
            logger.info(
                "Orchestration completed for user_id=%s with status=%s",
                user_id, result.status
            )
            
            # Track success and close trace
            if OBSERVABILITY_ENABLED:
                increment("orchestrations_completed")
                if trace_context:
                    trace_context.__exit__(None, None, None)
            
            return result
            
        except Exception as e:
            logger.error("Orchestration failed for user_id=%s: %s", user_id, e)
            result.status = "failed"
            result.errors.append(str(e))
            result.completed_at = datetime.utcnow().isoformat()
            
            self._store.update_status(
                user_id,
                "failed",
                {"task_id": task_id, "error": str(e)}
            )
            
            # Track failure and close trace
            if OBSERVABILITY_ENABLED:
                increment("orchestrations_failed")
                if trace_context:
                    trace_context.__exit__(type(e), e, e.__traceback__)
            
            return result
    
    async def _run_kycv_operations(
        self,
        result: OrchestrationResult,
        master_json: Dict[str, Any],
        generate_report: bool,
        plan_alerts: bool,
    ) -> None:
        """Run KYCV MCP server operations."""
        try:
            async with KycvMcpClient(self.config.kycv_mcp_url) as kycv:
                # List available tools
                tools = await kycv.list_tools()
                logger.info("KYCV MCP tools available: %s", tools)
                
                # Generate report
                if generate_report:
                    logger.info("Generating KYC report...")
                    report_resp = await kycv.generate_report(master_json)
                    result.kycv_report = _extract_report(report_resp)
                    result.actions_executed.append({
                        "tool": "generate_report",
                        "server": "kycv",
                        "success": result.kycv_report is not None,
                    })
                    logger.info("Report generated: %d chars", len(result.kycv_report or ""))
                
                # Plan alerts
                if plan_alerts:
                    logger.info("Planning alerts...")
                    try:
                        plan_resp = await kycv.plan_alerts(master_json=master_json)
                        logger.debug("Raw plan_alerts response: %s (type=%s)", plan_resp, type(plan_resp))
                        result.alert_plan = _extract_plan(plan_resp)
                        result.actions_executed.append({
                            "tool": "plan_alerts",
                            "server": "kycv",
                            "success": result.alert_plan is not None,
                        })
                        
                        # Dispatch alerts if there are targets
                        if result.alert_plan:
                            await self._dispatch_alerts(kycv, result)
                    except Exception as plan_err:
                        logger.error("plan_alerts tool failed: %s", plan_err, exc_info=True)
                        result.errors.append(f"plan_alerts error: {plan_err}")
                        result.actions_executed.append({
                            "tool": "plan_alerts",
                            "server": "kycv",
                            "success": False,
                        })
                        
        except Exception as e:
            logger.error("KYCV operations failed: %s", e)
            result.errors.append(f"KYCV error: {e}")
    
    async def _dispatch_alerts(
        self,
        kycv: KycvMcpClient,
        result: OrchestrationResult,
    ) -> None:
        """Dispatch alerts based on plan."""
        if not result.alert_plan:
            return
        
        # Dispatch user alert if targets exist
        user_targets = result.alert_plan.get("user_targets", [])
        if user_targets:
            try:
                logger.info("Dispatching user alert...")
                await kycv.dispatch_user_alert(
                    alert_plan=result.alert_plan,
                    context={"source": "orchestrator", "user_id": result.user_id},
                )
                result.actions_executed.append({
                    "tool": "dispatch_user_alert",
                    "server": "kycv",
                    "success": True,
                })
            except Exception as e:
                logger.warning("User alert dispatch failed: %s", e)
                result.errors.append(f"User alert dispatch: {e}")
        
        # Dispatch ops alert if targets exist
        ops_targets = result.alert_plan.get("ops_targets", [])
        if ops_targets:
            try:
                logger.info("Dispatching ops alert...")
                await kycv.dispatch_ops_alert(
                    alert_plan=result.alert_plan,
                    context={"source": "orchestrator", "user_id": result.user_id},
                )
                result.actions_executed.append({
                    "tool": "dispatch_ops_alert",
                    "server": "kycv",
                    "success": True,
                })
            except Exception as e:
                logger.warning("Ops alert dispatch failed: %s", e)
                result.errors.append(f"Ops alert dispatch: {e}")
    
    async def _run_risk_operations(
        self,
        result: OrchestrationResult,
        ml_input_json: Dict[str, Any],
    ) -> None:
        """Run RiskScore MCP server operations."""
        try:
            async with RiskMcpClient(self.config.risk_mcp_url) as risk:
                # Check status / load artifacts if needed
                status_resp = await risk.get_status()
                logger.debug("Raw status response: %s (type=%s)", status_resp, type(status_resp))
                status = _maybe_parse_response(status_resp)
                logger.info("RiskScore MCP status: %s", status)
                
                # Load artifacts if not loaded
                if isinstance(status, dict) and not status.get("loaded"):
                    artifact_dir = os.path.abspath(self.config.risk_artifact_dir)
                    if os.path.isdir(artifact_dir):
                        logger.info("Loading risk artifacts from %s", artifact_dir)
                        load_resp = await risk.load_artifacts(artifact_dir)
                        logger.info("Load artifacts response: %s", _maybe_parse_response(load_resp))
                    else:
                        logger.warning("Risk artifact dir not found: %s", artifact_dir)
                
                # Score online
                logger.info("Scoring investor risk with input: %s", ml_input_json)
                score_resp = await risk.score_online(ml_input_json, update=False)
                logger.debug("Raw score response: %s (type=%s)", score_resp, type(score_resp))
                result.risk_score = _extract_risk_score(score_resp)
                logger.info("Extracted risk_score: %s", result.risk_score)
                
                result.actions_executed.append({
                    "tool": "score_online",
                    "server": "risk",
                    "success": result.risk_score is not None,
                })
                
                if result.risk_score:
                    logger.info(
                        "Risk score: cluster=%s, label=%s, score=%.2f",
                        result.risk_score.get("cluster_id"),
                        result.risk_score.get("risk_label"),
                        result.risk_score.get("risk_score", 0),
                    )
                else:
                    logger.warning("Risk score extraction returned None")
                    
        except Exception as e:
            logger.error("Risk operations failed: %s", e, exc_info=True)
            result.errors.append(f"Risk error: {e}")
    
    async def _execute_additional_action(
        self,
        result: OrchestrationResult,
        action: ToolAction,
    ) -> None:
        """Execute an additional tool action."""
        logger.info("Executing additional action: %s", action.tool_name)
        
        try:
            if action.category == ToolCategory.RISK:
                async with RiskMcpClient(self.config.risk_mcp_url) as risk:
                    if action.tool_name == "get_status":
                        await risk.get_status()
                    elif action.tool_name == "get_risk_ranges":
                        await risk.get_risk_ranges()
                    # Add more as needed
            
            result.actions_executed.append({
                "tool": action.tool_name,
                "category": action.category.value,
                "success": True,
            })
        except Exception as e:
            logger.warning("Additional action %s failed: %s", action.tool_name, e)
            result.errors.append(f"{action.tool_name}: {e}")


# ============================================================================
# Background Task Runner (for FastAPI)
# ============================================================================

async def run_orchestration_async(
    task_id: str,
    user_id: str,
    run_kycv: bool = True,
    run_risk_score: bool = True,
    generate_report: bool = True,
    plan_alerts: bool = True,
    config: Optional[OrchestratorConfig] = None,
) -> OrchestrationResult:
    """Run orchestration asynchronously."""
    orchestrator = UnifiedOrchestrator(config)
    return await orchestrator.run(
        user_id=user_id,
        task_id=task_id,
        run_kycv=run_kycv,
        run_risk_score=run_risk_score,
        generate_report=generate_report,
        plan_alerts=plan_alerts,
    )


def run_orchestration_background(
    task_id: str,
    user_id: str,
    run_kycv: bool = True,
    run_risk_score: bool = True,
    generate_report: bool = True,
    plan_alerts: bool = True,
) -> None:
    """Background task entry point for FastAPI."""
    asyncio.run(run_orchestration_async(
        task_id=task_id,
        user_id=user_id,
        run_kycv=run_kycv,
        run_risk_score=run_risk_score,
        generate_report=generate_report,
        plan_alerts=plan_alerts,
    ))


# ============================================================================
# CLI
# ============================================================================

def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unified KYC Orchestrator - coordinates KYCV and RiskScore MCP servers",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="User ID to orchestrate (must have payload stored in database)",
    )
    parser.add_argument(
        "--kycv-url",
        default="http://127.0.0.1:8123/mcp/",
        help="KYCV MCP server URL",
    )
    parser.add_argument(
        "--risk-url",
        default="http://127.0.0.1:8124/mcp/",
        help="RiskScore MCP server URL",
    )
    parser.add_argument(
        "--artifact-dir",
        default="./risk_artifacts",
        help="Path to risk scorer artifacts",
    )
    parser.add_argument(
        "--no-kycv",
        action="store_true",
        help="Skip KYCV MCP server operations",
    )
    parser.add_argument(
        "--no-risk",
        action="store_true",
        help="Skip RiskScore MCP server operations",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip report generation",
    )
    parser.add_argument(
        "--no-alerts",
        action="store_true",
        help="Skip alert planning/dispatch",
    )
    parser.add_argument(
        "--use-rules",
        action="store_true",
        help="Use rule-based tool selector instead of LLM",
    )
    parser.add_argument(
        "--output",
        help="Path to write result JSON",
    )
    return parser


async def main_async(args: argparse.Namespace) -> OrchestrationResult:
    config = OrchestratorConfig(
        kycv_mcp_url=args.kycv_url,
        risk_mcp_url=args.risk_url,
        risk_artifact_dir=args.artifact_dir,
        use_llm_selector=not args.use_rules,
    )
    
    orchestrator = UnifiedOrchestrator(config)
    return await orchestrator.run(
        user_id=args.user_id,
        run_kycv=not args.no_kycv,
        run_risk_score=not args.no_risk,
        generate_report=not args.no_report,
        plan_alerts=not args.no_alerts,
    )


def main() -> None:
    parser = _build_cli()
    args = parser.parse_args()
    
    result = asyncio.run(main_async(args))
    
    # Print result
    print("\n" + "=" * 60)
    print("ORCHESTRATION RESULT")
    print("=" * 60)
    print(f"User ID: {result.user_id}")
    print(f"Task ID: {result.task_id}")
    print(f"Status: {result.status}")
    print(f"Started: {result.started_at}")
    print(f"Completed: {result.completed_at}")
    
    if result.kycv_report:
        print(f"\nKYC Report: {len(result.kycv_report)} characters")
    
    if result.alert_plan:
        print(f"\nAlert Plan: severity={result.alert_plan.get('severity')}")
    
    if result.risk_score:
        print(f"\nRisk Score:")
        print(f"  Label: {result.risk_score.get('risk_label')}")
        print(f"  Score: {result.risk_score.get('risk_score', 0):.2f}")
        print(f"  Cluster: {result.risk_score.get('cluster_id')}")
    
    print(f"\nActions Executed: {len(result.actions_executed)}")
    for action in result.actions_executed:
        status = "✓" if action.get("success") else "✗"
        print(f"  {status} {action.get('tool')} ({action.get('server', '')})")
    
    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")
    
    # Print LLM cost summary if observability is enabled
    if OBSERVABILITY_ENABLED:
        cost_summary = get_cost_summary()
        print("\n" + "=" * 60)
        print("LLM COST SUMMARY (Langfuse)")
        print("=" * 60)
        print(f"Total Cost: ${cost_summary['total_cost']:.6f}")
        print(f"Total Input Tokens: {cost_summary['total_input_tokens']}")
        print(f"Total Output Tokens: {cost_summary['total_output_tokens']}")
        if cost_summary['by_model']:
            print("\nBy Model:")
            for model, stats in cost_summary['by_model'].items():
                print(f"  {model}:")
                print(f"    Calls: {stats['calls']}")
                print(f"    Input: {stats['input_tokens']} tokens")
                print(f"    Output: {stats['output_tokens']} tokens")
                print(f"    Cost: ${stats['cost']:.6f}")
    
    # Write output file if requested
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(result.to_dict(), indent=2))
        print(f"\nResult written to: {output_path}")
    
    # Shutdown Langfuse
    if OBSERVABILITY_ENABLED:
        shutdown_langfuse()


if __name__ == "__main__":
    main()
