from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError

try:  
    from openai import OpenAI
except ImportError:
    OpenAI = None 

from kyc_alerts import (
    AlertDispatchTarget,
    AlertPlan,
    AlertSeverity,
    AlertSignal,
    plan_alert_from_signal,
)
from kyc_observability import accumulate_cost, increment, track_latency

LOGGER = logging.getLogger(__name__)
PLANNER_DEFAULT_MODEL = "gpt-4o-mini"


class PlannerTarget(BaseModel):
    audience: str = Field(..., min_length=2, max_length=64)
    channel: str = Field(..., min_length=2, max_length=32)
    instructions: str = Field(..., min_length=3, max_length=512)


class PlannerResponse(BaseModel):
    severity: AlertSeverity
    user_targets: List[PlannerTarget] = Field(default_factory=list)
    ops_targets: List[PlannerTarget] = Field(default_factory=list)
    requires_human_review: bool = False
    rationale: List[str] = Field(default_factory=list)


_PLANNER_PROMPT = """You are an experienced KYC operations planner. Given a JSON alert signal,
produce a JSON response with the schema:
{
    "severity": one of ["info","minor","major","critical"],
    "user_targets": [ {"audience": str, "channel": str, "instructions": str } ],
    "ops_targets":   [ {"audience": str, "channel": str, "instructions": str } ],
    "requires_human_review": bool,
    "rationale": [str]
}
Apply these deterministic guardrails:
- Severity bands: critical if mismatches ≥4 or video decision is "reject"/"reject_failed_liveness"; major if mismatches ≥2 or missing fields ≥2; minor if exactly one mismatch, any warnings, or one missing field; info otherwise.
- User follow-up: only skip when mismatches, warnings, *and* missing fields are zero. Otherwise instruct the applicant to upload the relevant documents again.
- Ops escalation: include an ops target when severity is major/critical or the video decision starts with "reject". Use monitored channels (pagerduty/slack/sms) for ops.
- Human review: required for critical plans or when severity is major and mismatches ≥3.
- When severity is info and you added no user target yet, add a single user email target confirming verification completion.
- Supporting documents are not part of the response; if you need uploads, describe them inside user target instructions.
- Always justify severity/targets inside the rationale array.
- Never mention internal system names or expose raw PII; speak generically.
- Respond with JSON only, no prose.
"""


def _build_prompt(signal: AlertSignal) -> str:
    return f"{_PLANNER_PROMPT}\nSignal:\n{json.dumps(signal.to_dict(), indent=2)}"


def _call_openai(prompt: str, model: str) -> Optional[str]:
    if OpenAI is None:
        LOGGER.warning("OpenAI SDK not installed; falling back to deterministic plan")
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        LOGGER.warning("OPENAI_API_KEY not configured; falling back to deterministic plan")
        return None
    client = OpenAI(api_key=api_key)
    with track_latency("planner.llm_call", model=model):
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": [{"type": "text", "text": _PLANNER_PROMPT}]},
                {"role": "user", "content": [{"type": "text", "text": prompt}]},
            ],
            temperature=0.2,
            max_output_tokens=600,
            response_format={"type": "json_object"},
        )
    usage = getattr(response, "usage", None)
    if usage:
        try:
            total_tokens = getattr(usage, "total_tokens", 0) or 0
            cost_per_k = float(os.getenv("KYC_ALERT_PLANNER_COST_PER_1K_TOKEN", "0"))
            if cost_per_k > 0 and total_tokens:
                accumulate_cost(
                    "planner.tokens",
                    (total_tokens / 1000.0) * cost_per_k,
                    currency="USD",
                    model=model,
                )
            increment("planner.llm_invocations", model=model, tokens=total_tokens)
        except Exception:  # pragma: no cover - defensive metrics handling
            LOGGER.debug("Unable to record LLM usage metrics", exc_info=True)
    return response.output[0].content[0].text if response.output else None


def _planner_response_to_plan(payload: PlannerResponse) -> AlertPlan:
    user_targets = [
        AlertDispatchTarget(
            audience=target.audience,
            channel=target.channel,
            instructions=target.instructions,
        )
        for target in payload.user_targets
    ]
    ops_targets = [
        AlertDispatchTarget(
            audience=target.audience,
            channel=target.channel,
            instructions=target.instructions,
        )
        for target in payload.ops_targets
    ]
    return AlertPlan(
        severity=payload.severity,
        user_targets=user_targets,
        ops_targets=ops_targets,
        supporting_documents=[],
        requires_human_review=payload.requires_human_review,
        rationale=payload.rationale,
    )


def generate_alert_plan(signal: AlertSignal) -> AlertPlan:
    """Run the LLM-based planner when configured, otherwise fallback."""

    default_plan = plan_alert_from_signal(signal)
    model = os.getenv("KYC_ALERT_PLANNER_MODEL") or ""
    if not model:
        return default_plan

    prompt = _build_prompt(signal)
    try:
        raw_response = _call_openai(prompt, model)
        if not raw_response:
            return default_plan
        parsed = PlannerResponse.model_validate_json(raw_response)
        return _planner_response_to_plan(parsed)
    except (ValidationError, json.JSONDecodeError) as exc:
        LOGGER.warning("Planner response invalid; using deterministic fallback: %s", exc)
        return default_plan
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.exception("Planner invocation failed; using deterministic fallback")
        return default_plan