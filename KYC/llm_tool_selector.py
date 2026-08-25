"""LLM-based tool selector for KYC orchestration.

This module provides an LLM-powered decision engine that analyzes KYC data
and decides which tools/actions to execute. It enforces an allowlist of
tools and validates LLM outputs for safety.

Usage:
    from llm_tool_selector import LLMToolSelector, ToolAction

    selector = LLMToolSelector()
    actions = await selector.decide_tools(
        context={"master_json": {...}, "kycv_report": {...}},
        available_tools=["send_alert", "generate_report", "score_risk"]
    )
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from openai import OpenAI

# Import observability
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
    track_llm_generation = None

logger = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    """Categories of tools available in the orchestration pipeline."""
    KYCV = "kycv"           # KYCV MCP server tools
    RISK = "risk"           # RiskScore MCP server tools
    ALERT = "alert"         # Alert dispatch tools
    REPORT = "report"       # Report generation tools
    DATA = "data"           # Data enrichment/validation tools


@dataclass
class ToolAction:
    """Represents a tool action decided by the LLM."""
    tool_name: str
    category: ToolCategory
    args: Dict[str, Any] = field(default_factory=dict)
    priority: int = 1  # 1 = highest priority
    reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "category": self.category.value,
            "args": self.args,
            "priority": self.priority,
            "reason": self.reason,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolAction":
        return cls(
            tool_name=data["tool_name"],
            category=ToolCategory(data.get("category", "kycv")),
            args=data.get("args", {}),
            priority=data.get("priority", 1),
            reason=data.get("reason", ""),
        )


# ============================================================================
# Tool Registry - Allowlist of permitted tools
# ============================================================================

ALLOWED_TOOLS: Dict[str, Dict[str, Any]] = {
    # KYCV MCP Server Tools
    "parse_documents": {
        "category": ToolCategory.KYCV,
        "description": "Parse raw document texts (PAN, Aadhaar, ITR)",
        "required_args": ["pan_text", "aadhaar_text", "itr_text"],
    },
    "verify_documents": {
        "category": ToolCategory.KYCV,
        "description": "Cross-verify parsed documents for consistency",
        "required_args": ["parsed_bundle"],
    },
    "assemble_payloads": {
        "category": ToolCategory.KYCV,
        "description": "Assemble master_json and ml_input_json from verified documents",
        "required_args": ["parsed_bundle", "questionnaire", "additional_details", "document_verification"],
    },
    "generate_report": {
        "category": ToolCategory.REPORT,
        "description": "Generate KYC verification report from master_json",
        "required_args": ["master_json"],
    },
    "generate_report_from_master": {
        "category": ToolCategory.REPORT,
        "description": "Generate report from stored master_json by ID",
        "required_args": [],
        "optional_args": ["master_json_id", "master_json"],
    },
    "plan_alerts": {
        "category": ToolCategory.ALERT,
        "description": "Plan alert targets based on verification results",
        "required_args": [],
        "optional_args": ["master_json_id", "master_json", "llm_annotations"],
    },
    "dispatch_user_alert": {
        "category": ToolCategory.ALERT,
        "description": "Dispatch alert to user-facing channels",
        "required_args": ["alert_plan"],
        "optional_args": ["channel", "context"],
    },
    "dispatch_ops_alert": {
        "category": ToolCategory.ALERT,
        "description": "Dispatch alert to operations team",
        "required_args": ["alert_plan"],
        "optional_args": ["channel", "context"],
    },
    
    # RiskScore MCP Server Tools
    "load_artifacts": {
        "category": ToolCategory.RISK,
        "description": "Load risk scoring model artifacts",
        "required_args": ["artifact_dir"],
        "optional_args": ["use_offline_centroids"],
    },
    "score_online": {
        "category": ToolCategory.RISK,
        "description": "Score investor risk using online model",
        "required_args": ["user"],
        "optional_args": ["update"],
    },
    "score_offline": {
        "category": ToolCategory.RISK,
        "description": "Score investor risk using offline model",
        "required_args": ["user"],
    },
    "get_status": {
        "category": ToolCategory.RISK,
        "description": "Get risk scorer server status",
        "required_args": [],
    },
    "get_cluster_context": {
        "category": ToolCategory.RISK,
        "description": "Get cluster label mappings",
        "required_args": [],
    },
    "get_risk_ranges": {
        "category": ToolCategory.RISK,
        "description": "Get risk score ranges by label",
        "required_args": [],
    },
}


# Tool name aliases - map common variations/typos to correct tool names
_TOOL_ALIASES: Dict[str, str] = {
    "alert_plan": "plan_alerts",  # Common confusion: alert_plan vs plan_alerts
    "plan_alert": "plan_alerts",  # Singular form
    "alerts_plan": "plan_alerts",  # Plural form variation
    "alert_dispatch": None,  # Special case: route based on args
    "dispatch_alert": None,  # Special case: route based on args
    "send_alert": None,  # Special case: route based on args
}


def _normalize_tool_name(tool_name: str, action_args: Optional[Dict[str, Any]] = None) -> str:
    """
    Normalize tool name by applying aliases.
    
    For generic alert dispatch tools, routes to dispatch_user_alert or dispatch_ops_alert
    based on the audience/channel in the args.
    """
    if tool_name in _TOOL_ALIASES:
        alias = _TOOL_ALIASES[tool_name]
        if alias is None:
            # Special routing for generic alert dispatch tools
            if action_args:
                audience = action_args.get("audience", "").lower()
                channel = action_args.get("channel", "").lower()
                
                # Route to user alert if audience is user-related
                if any(term in audience for term in ["user", "customer", "client", "investor"]):
                    return "dispatch_user_alert"
                # Route to ops alert for ops/compliance/admin audiences or ops channels
                if any(term in audience for term in ["ops", "operations", "compliance", "admin", "team"]):
                    return "dispatch_ops_alert"
                if any(term in channel for term in ["pagerduty", "slack", "ops"]):
                    return "dispatch_ops_alert"
                # Default to ops for safety
                return "dispatch_ops_alert"
            # Default to ops if no args provided
            return "dispatch_ops_alert"
        return alias
    return tool_name


def get_allowed_tool_names() -> Set[str]:
    """Return set of all allowed tool names."""
    return set(ALLOWED_TOOLS.keys())


def is_tool_allowed(tool_name: str, action_args: Optional[Dict[str, Any]] = None) -> bool:
    """Check if a tool is in the allowlist (after normalization)."""
    normalized = _normalize_tool_name(tool_name, action_args)
    return normalized in ALLOWED_TOOLS


def get_tool_info(tool_name: str, action_args: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Get tool information from registry (after normalization)."""
    normalized = _normalize_tool_name(tool_name, action_args)
    return ALLOWED_TOOLS.get(normalized)


# ============================================================================
# LLM Tool Selector
# ============================================================================

TOOL_SELECTION_PROMPT = """You are a KYC orchestration assistant. Based on the provided context, decide which tools should be executed and in what order.

Available Tools:
{available_tools}

Current Context:
{context}

Task: Analyze the context and determine which tools to execute. Consider:
1. Verification status - are there any mismatches or warnings?
2. Alert requirements - do alerts need to be planned/dispatched?
3. Report generation - should a report be generated?
4. Risk scoring - should the risk score be calculated?

IMPORTANT RULES:
- Only select tools from the Available Tools list
- Use EXACT tool names from the Available Tools list (do not invent variations)
- For alert dispatch, use "dispatch_user_alert" for user-facing alerts or "dispatch_ops_alert" for operations team alerts
- Do NOT use generic names like "alert_dispatch" - use the specific tool names
- Provide clear reasoning for each tool selection
- Order tools by priority (1 = highest)
- For alert dispatch, check if there are user/ops targets in the alert plan

Return a JSON array of tool actions in this exact format:
```json
[
    {{
        "tool_name": "tool_name_here",
        "category": "kycv|risk|alert|report|data",
        "args": {{}},
        "priority": 1,
        "reason": "Brief explanation"
    }}
]
```

Only return the JSON array, no other text.
"""


class LLMToolSelector:
    """LLM-powered tool selector for KYC orchestration."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.1,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.temperature = temperature
        self._client: Optional[OpenAI] = None
    
    @property
    def client(self) -> OpenAI:
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("OpenAI API key not configured")
            self._client = OpenAI(api_key=self.api_key)
        return self._client
    
    def _format_available_tools(self, tool_names: Optional[List[str]] = None) -> str:
        """Format available tools for the prompt."""
        if tool_names:
            tools = {k: v for k, v in ALLOWED_TOOLS.items() if k in tool_names}
        else:
            tools = ALLOWED_TOOLS
        
        lines = []
        for name, info in tools.items():
            required = info.get("required_args", [])
            optional = info.get("optional_args", [])
            args_str = ""
            if required:
                args_str += f"Required: {', '.join(required)}"
            if optional:
                args_str += f" Optional: {', '.join(optional)}"
            lines.append(f"- {name} ({info['category'].value}): {info['description']}. {args_str}")
        
        return "\n".join(lines)
    
    def _format_context(self, context: Dict[str, Any]) -> str:
        """Format context for the prompt, sanitizing sensitive data."""
        # Create a sanitized copy
        sanitized = {}
        
        for key, value in context.items():
            if isinstance(value, dict):
                # For nested dicts, only include summary info
                if key == "master_json":
                    sanitized[key] = {
                        "verification_status": value.get("verification_status"),
                        "alerting": value.get("alerting"),
                        "has_personal_details": "personal_details" in value,
                        "has_financial_details": "financial_details" in value,
                    }
                elif key == "alert_plan":
                    sanitized[key] = {
                        "severity": value.get("severity"),
                        "has_user_targets": bool(value.get("user_targets")),
                        "has_ops_targets": bool(value.get("ops_targets")),
                        "requires_human_review": value.get("requires_human_review"),
                    }
                else:
                    sanitized[key] = value
            else:
                sanitized[key] = value
        
        return json.dumps(sanitized, indent=2, default=str)
    
    async def decide_tools(
        self,
        context: Dict[str, Any],
        available_tools: Optional[List[str]] = None,
    ) -> List[ToolAction]:
        """
        Use LLM to decide which tools to execute based on context.
        
        Args:
            context: Dictionary containing master_json, reports, alert plans, etc.
            available_tools: Optional list of tool names to consider (defaults to all)
        
        Returns:
            List of ToolAction objects sorted by priority
        """
        prompt = TOOL_SELECTION_PROMPT.format(
            available_tools=self._format_available_tools(available_tools),
            context=self._format_context(context),
        )
        
        try:
            messages = [
                {
                    "role": "system",
                    "content": "You are a KYC orchestration assistant that decides which tools to execute. Always respond with valid JSON."
                },
                {"role": "user", "content": prompt}
            ]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=1000,
            )
            
            content = response.choices[0].message.content.strip()
            
            # Track LLM usage with observability
            if OBSERVABILITY_ENABLED and track_llm_generation:
                usage = response.usage
                if usage:
                    input_tokens = usage.prompt_tokens
                    output_tokens = usage.completion_tokens
                    cost = calculate_openai_cost(self.model, input_tokens, output_tokens)
                    
                    # Track the generation
                    track_llm_generation(
                        name="tool_selection",
                        model=self.model,
                        input_messages=messages,
                        output=content,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost=cost,
                        metadata={"operation": "decide_tools"}
                    )
                    
                    # Accumulate cost for summary
                    accumulate_cost(self.model, input_tokens, output_tokens, cost)
                    increment("llm_tool_selections")
                    logger.debug(f"Tool selection cost: ${cost:.6f}")
            
            # Extract JSON from response (handle markdown code blocks)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            # Try to find JSON array in the content if parsing fails
            original_content = content
            try:
                actions_data = json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning("Initial JSON parse failed: %s. Attempting to extract/fix JSON...", e)
                # Try to fix common JSON issues first
                content = self._fix_json_string(content)
                try:
                    actions_data = json.loads(content)
                    logger.info("Successfully parsed JSON after fixing common issues")
                except json.JSONDecodeError:
                    # Try to extract JSON array from the content using regex
                    import re
                    # Look for JSON array pattern (more flexible)
                    json_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', content, re.DOTALL)
                    if json_match:
                        extracted = json_match.group(0)
                        extracted = self._fix_json_string(extracted)
                        try:
                            actions_data = json.loads(extracted)
                            logger.info("Successfully extracted and parsed JSON from response")
                        except json.JSONDecodeError as e2:
                            logger.warning("Still failed to parse extracted JSON: %s", e2)
                            logger.debug("Extracted JSON (first 500 chars): %s", extracted[:500])
                            raise e
                    else:
                        # Try to find any JSON-like structure
                        logger.warning("Could not extract JSON array from LLM response")
                        logger.debug("LLM response content (first 500 chars): %s", original_content[:500])
                        raise e
            
            # Validate and convert to ToolAction objects
            actions = []
            for action_dict in actions_data:
                tool_name = action_dict.get("tool_name", "")
                action_args = action_dict.get("args", {})
                normalized_name = _normalize_tool_name(tool_name, action_args)
                
                # Check with normalized name (since is_tool_allowed normalizes internally, but be explicit)
                if normalized_name not in ALLOWED_TOOLS:
                    logger.warning(
                        "LLM suggested disallowed tool: '%s' (normalized: '%s', type: %s) - skipping. Full action_dict: %s. Allowed tools: %s",
                        tool_name,
                        normalized_name,
                        type(tool_name).__name__,
                        action_dict,
                        sorted(get_allowed_tool_names())
                    )
                    continue
                
                # Update tool_name with normalized version if it was aliased
                if normalized_name != tool_name:
                    logger.info("Normalized tool name '%s' to '%s' (based on args: %s)", 
                              tool_name, normalized_name, action_args)
                    action_dict = action_dict.copy()
                    action_dict["tool_name"] = normalized_name
                
                action = ToolAction.from_dict(action_dict)
                actions.append(action)
            
            # Sort by priority
            actions.sort(key=lambda a: a.priority)
            
            logger.info("LLM decided on %d tool actions", len(actions))
            return actions
            
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response as JSON: %s", e)
            return self._fallback_decision(context)
        except Exception as e:
            logger.error("LLM tool selection failed: %s", e)
            return self._fallback_decision(context)
    
    def _fix_json_string(self, json_str: str) -> str:
        """Attempt to fix common JSON issues like trailing commas."""
        import re
        # Remove trailing commas before closing brackets/braces
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        return json_str
    
    def _fallback_decision(self, context: Dict[str, Any]) -> List[ToolAction]:
        """Fallback tool decision when LLM fails."""
        actions = []
        
        # Always generate report if we have master_json
        if "master_json" in context:
            actions.append(ToolAction(
                tool_name="generate_report",
                category=ToolCategory.REPORT,
                args={"master_json": context["master_json"]},
                priority=1,
                reason="Fallback: Generate report from master_json",
            ))
        
        # Plan alerts if not already done
        if "alert_plan" not in context and "master_json" in context:
            actions.append(ToolAction(
                tool_name="plan_alerts",
                category=ToolCategory.ALERT,
                args={"master_json": context["master_json"]},
                priority=2,
                reason="Fallback: Plan alerts from verification results",
            ))
        
        # Score risk if we have ml_input_json
        if "ml_input_json" in context:
            actions.append(ToolAction(
                tool_name="score_online",
                category=ToolCategory.RISK,
                args={"user": context["ml_input_json"]},
                priority=3,
                reason="Fallback: Score risk from ML input",
            ))
        
        return actions


def decide_tools_sync(
    context: Dict[str, Any],
    available_tools: Optional[List[str]] = None,
    api_key: Optional[str] = None,
) -> List[ToolAction]:
    """Synchronous wrapper for decide_tools."""
    import asyncio
    
    selector = LLMToolSelector(api_key=api_key)
    return asyncio.run(selector.decide_tools(context, available_tools))


# ============================================================================
# Rule-based Tool Selector (Alternative to LLM)
# ============================================================================

class RuleBasedToolSelector:
    """
    Rule-based tool selector as an alternative to LLM.
    Uses deterministic rules based on context to decide tools.
    """
    
    def decide_tools(
        self,
        context: Dict[str, Any],
        options: Optional[Dict[str, bool]] = None,
    ) -> List[ToolAction]:
        """
        Decide tools based on rules.
        
        Args:
            context: Dictionary with master_json, ml_input_json, etc.
            options: Dict with flags like run_kycv, run_risk_score, etc.
        """
        options = options or {}
        actions = []
        priority = 1
        
        master_json = context.get("master_json")
        ml_input = context.get("ml_input_json")
        
        # 1. Generate report if requested and we have master_json
        if options.get("generate_report", True) and master_json:
            actions.append(ToolAction(
                tool_name="generate_report",
                category=ToolCategory.REPORT,
                args={"master_json": master_json},
                priority=priority,
                reason="Generate KYC verification report",
            ))
            priority += 1
        
        # 2. Plan alerts if requested
        if options.get("plan_alerts", True) and master_json:
            # Check if there are verification issues
            verification_status = master_json.get("verification_status", {})
            has_issues = (
                not verification_status.get("overall_status", True) or
                verification_status.get("summary", {}).get("total_mismatches", 0) > 0 or
                verification_status.get("summary", {}).get("total_warnings", 0) > 0
            )
            
            actions.append(ToolAction(
                tool_name="plan_alerts",
                category=ToolCategory.ALERT,
                args={"master_json": master_json},
                priority=priority,
                reason="Plan alerts based on verification status",
            ))
            priority += 1
            
            # If critical issues, dispatch ops alert
            if has_issues and options.get("dispatch_alerts", True):
                existing_plan = master_json.get("alerting", {}).get("plan", {})
                if existing_plan.get("ops_targets"):
                    actions.append(ToolAction(
                        tool_name="dispatch_ops_alert",
                        category=ToolCategory.ALERT,
                        args={
                            "alert_plan": existing_plan,
                            "channel": "",
                            "context": {"source": "orchestrator"},
                        },
                        priority=priority,
                        reason="Dispatch ops alert for verification issues",
                    ))
                    priority += 1
        
        # 3. Score risk if requested and we have ml_input
        if options.get("run_risk_score", True) and ml_input:
            actions.append(ToolAction(
                tool_name="score_online",
                category=ToolCategory.RISK,
                args={"user": ml_input, "update": False},
                priority=priority,
                reason="Calculate investor risk score",
            ))
            priority += 1
        
        return actions


# ============================================================================
# Utility functions
# ============================================================================

def validate_tool_action(action: ToolAction) -> tuple[bool, str]:
    """
    Validate a tool action against the registry.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    normalized_name = _normalize_tool_name(action.tool_name, action.args)
    if not is_tool_allowed(normalized_name, action.args):
        return False, f"Tool '{action.tool_name}' is not in the allowlist (normalized: '{normalized_name}')"
    
    # Update tool_name with normalized version
    if normalized_name != action.tool_name:
        action.tool_name = normalized_name
    
    tool_info = get_tool_info(action.tool_name, action.args)
    required_args = tool_info.get("required_args", [])
    
    for arg in required_args:
        if arg not in action.args:
            return False, f"Tool '{action.tool_name}' missing required argument: {arg}"
    
    return True, ""


def filter_valid_actions(actions: List[ToolAction]) -> List[ToolAction]:
    """Filter out invalid tool actions."""
    valid_actions = []
    for action in actions:
        is_valid, error = validate_tool_action(action)
        if is_valid:
            valid_actions.append(action)
        else:
            logger.warning("Skipping invalid action: %s - %s", action.tool_name, error)
    return valid_actions