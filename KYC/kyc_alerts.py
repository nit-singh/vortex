"""Alert planning utilities for the KYC pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

_MIN_CONFIDENCE = 0.0
_MAX_CONFIDENCE = 1.0


class AlertSeverity(str, Enum):
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


@dataclass
class AlertDispatchTarget:
    audience: str
    channel: str
    instructions: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AlertSignal:
    master_json_id: Optional[str]
    mismatch_count: int
    warning_count: int
    missing_field_count: int
    video_decision: Optional[str]
    video_confidence: Optional[float]
    liveness_passed: Optional[bool]
    head_movement: Optional[float]
    blink_count: Optional[int]
    notes: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mismatch_count < 0:
            raise ValueError("mismatch_count cannot be negative")
        if self.warning_count < 0:
            raise ValueError("warning_count cannot be negative")
        if self.missing_field_count < 0:
            raise ValueError("missing_field_count cannot be negative")
        if self.video_confidence is not None and not (_MIN_CONFIDENCE <= self.video_confidence <= _MAX_CONFIDENCE):
            raise ValueError("video_confidence must be between 0 and 1 inclusive")
        if self.head_movement is not None and self.head_movement < 0:
            raise ValueError("head_movement cannot be negative")
        if self.blink_count is not None and self.blink_count < 0:
            raise ValueError("blink_count cannot be negative")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_payload(payload: Any) -> "AlertSignal":
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise TypeError("AlertSignal expects a mapping payload")
        return AlertSignal(
            master_json_id=payload.get("master_json_id"),
            mismatch_count=int(payload.get("mismatch_count", 0)),
            warning_count=int(payload.get("warning_count", 0)),
            missing_field_count=int(payload.get("missing_field_count", 0)),
            video_decision=payload.get("video_decision"),
            video_confidence=payload.get("video_confidence"),
            liveness_passed=payload.get("liveness_passed"),
            head_movement=payload.get("head_movement"),
            blink_count=payload.get("blink_count"),
            notes=list(payload.get("notes", [])),
            evidence=dict(payload.get("evidence", {})),
        )


def _derive_severity(signal: AlertSignal) -> AlertSeverity:
    if (
        signal.mismatch_count >= 4
        or signal.video_decision == "reject"
        or (
            signal.liveness_passed is False
            and signal.video_decision == "reject_failed_liveness"
        )
    ):
        return AlertSeverity.CRITICAL
    if signal.mismatch_count >= 2 or signal.missing_field_count >= 2:
        return AlertSeverity.MAJOR
    if signal.mismatch_count == 1 or signal.warning_count > 0 or signal.missing_field_count == 1:
        return AlertSeverity.MINOR
    return AlertSeverity.INFO


def _requires_user_follow_up(signal: AlertSignal) -> bool:
    if signal.mismatch_count == 0 and signal.missing_field_count == 0 and signal.warning_count == 0:
        return False
    if signal.video_decision and signal.video_decision.startswith("reject"):
        return True
    return True


def _supporting_doc_request(signal: AlertSignal) -> List[str]:
    doc_types: List[str] = []
    if signal.mismatch_count >= 1:
        doc_types.extend(["Voter ID", "Passport"])
    if signal.missing_field_count > 0:
        doc_types.append("Utility Bill")
    if signal.video_decision and "video" in signal.video_decision:
        doc_types.append("Selfie Video Retry")
    # Deduplicate while preserving order
    seen = set()
    result: List[str] = []
    for doc in doc_types:
        if doc not in seen:
            seen.add(doc)
            result.append(doc)
    return result


@dataclass
class AlertPlan:
    severity: AlertSeverity
    user_targets: List[AlertDispatchTarget] = field(default_factory=list)
    ops_targets: List[AlertDispatchTarget] = field(default_factory=list)
    supporting_documents: List[str] = field(default_factory=list)
    requires_human_review: bool = False
    rationale: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        return payload

    @staticmethod
    def from_payload(payload: Any) -> "AlertPlan":
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise TypeError("AlertPlan expects a dict payload")
        severity = AlertSeverity(payload.get("severity", AlertSeverity.INFO))
        user_targets = [AlertDispatchTarget(**target) for target in payload.get("user_targets", [])]
        ops_targets = [AlertDispatchTarget(**target) for target in payload.get("ops_targets", [])]
        return AlertPlan(
            severity=severity,
            user_targets=user_targets,
            ops_targets=ops_targets,
            supporting_documents=list(payload.get("supporting_documents", [])),
            requires_human_review=bool(payload.get("requires_human_review", False)),
            rationale=list(payload.get("rationale", [])),
        )


def build_alert_signal(
    master_json_id: Optional[str],
    document_verification: Dict[str, Any],
    video_verification: Optional[Dict[str, Any]] = None,
) -> AlertSignal:
    document_verification = document_verification or {}
    video_verification = video_verification or {}

    mismatches = len(document_verification.get("mismatches", []))
    warnings = len(document_verification.get("warnings", []))
    missing_fields = len(document_verification.get("missing_fields", []))
    video_decision = video_verification.get("final_decision")
    liveness = video_verification.get("liveness_check", {})
    notes = video_verification.get("notes", [])
    
    # Extract video_confidence from pan_video_distance
    # If it's out of valid range [0, 1], fail the verification
    pan_video_distance = video_verification.get("detailed_scores", {}).get("pan_video_distance")
    video_confidence: Optional[float] = None
    
    if pan_video_distance is not None:
        try:
            confidence_value = float(pan_video_distance)
            # Validate that confidence is in valid range [0, 1]
            if not (_MIN_CONFIDENCE <= confidence_value <= _MAX_CONFIDENCE):
                raise ValueError(
                    f"KYC verification failed: video_confidence value {confidence_value} is out of valid range [0, 1]. "
                    f"This indicates invalid or corrupted video verification data."
                )
            video_confidence = confidence_value
        except (ValueError, TypeError) as e:
            # If it's a range validation error, re-raise it
            if "video_confidence value" in str(e):
                raise
            # Otherwise, it's a type conversion error - treat as invalid data
            raise ValueError(
                f"KYC verification failed: invalid video_confidence value '{pan_video_distance}' "
                f"(expected float in range [0, 1]). This indicates corrupted video verification data."
            ) from e

    return AlertSignal(
        master_json_id=master_json_id,
        mismatch_count=mismatches,
        warning_count=warnings,
        missing_field_count=missing_fields,
        video_decision=video_decision,
        video_confidence=video_confidence,
        liveness_passed=liveness.get("passed"),
        head_movement=liveness.get("head_movement"),
        blink_count=liveness.get("blink_count"),
        notes=notes if isinstance(notes, list) else [str(notes)],
        evidence={
            "document_verification": document_verification,
            "video_verification": video_verification,
        },
    )


def plan_alert_from_signal(signal: AlertSignal) -> AlertPlan:
    severity = _derive_severity(signal)
    rationale: List[str] = []
    if signal.mismatch_count:
        rationale.append(f"Detected {signal.mismatch_count} mismatched fields")
    if signal.missing_field_count:
        rationale.append(f"Missing {signal.missing_field_count} critical fields")
    if signal.warning_count:
        rationale.append(f"Warnings reported: {signal.warning_count}")
    if signal.video_decision and signal.video_decision != "accept":
        rationale.append(f"Video verification result: {signal.video_decision}")

    supporting_docs = _supporting_doc_request(signal) if severity != AlertSeverity.INFO else []

    user_targets: List[AlertDispatchTarget] = []
    ops_targets: List[AlertDispatchTarget] = []

    if _requires_user_follow_up(signal):
        user_targets.append(
            AlertDispatchTarget(
                audience="user",
                channel="in_app",
                instructions="Notify applicant to upload supporting documents via secure portal.",
            )
        )

    if severity in {AlertSeverity.MAJOR, AlertSeverity.CRITICAL} or signal.video_decision and signal.video_decision.startswith("reject"):
        ops_targets.append(
            AlertDispatchTarget(
                audience="compliance_ops",
                channel="pagerduty",
                instructions="Create incident ticket for manual review.",
            )
        )

    requires_human = severity == AlertSeverity.CRITICAL or (
        severity == AlertSeverity.MAJOR and signal.mismatch_count >= 3
    )

    if severity == AlertSeverity.INFO and not user_targets:
        user_targets.append(
            AlertDispatchTarget(
                audience="user",
                channel="email",
                instructions="Share verification completion confirmation.",
            )
        )

    return AlertPlan(
        severity=severity,
        user_targets=user_targets,
        ops_targets=ops_targets,
        supporting_documents=supporting_docs,
        requires_human_review=requires_human,
        rationale=rationale or ["No discrepancies detected"],
    )


def build_verification_event_payload(
    master_json_id: Optional[str],
    document_verification: Dict[str, Any],
    video_verification: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    signal = build_alert_signal(master_json_id, document_verification, video_verification)
    plan = plan_alert_from_signal(signal)
    return {
        "master_json_id": master_json_id,
        "signal": signal.to_dict(),
        "plan": plan.to_dict(),
    }
