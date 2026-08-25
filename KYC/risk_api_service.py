"""FastAPI service exposing investor risk scoring endpoints.

Provides:
- Public user endpoint returning online River score (default path for front-end)
- Admin controls for toggling offline centroids + online learning updates
- MCP endpoints so downstream agent orchestrators can fetch/display scores
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from investor_risk_scorer import (
    OnlineRiskScorer,
    load_deployment_pipeline,
    run_offline_inference,
)


class ScoreRequest(BaseModel):
    """Incoming payload for running the scorer."""

    features: Dict[str, Any] = Field(..., description="Raw investor feature map")
    trace_id: Optional[str] = Field(None, description="Optional client supplied trace identifier")
    online_update: Optional[bool] = Field(
        None,
        description="Override service-level online update toggle for this request",
    )


class SettingsRequest(BaseModel):
    """Admin configuration adjustments."""

    use_offline_centroids: Optional[bool] = Field(None, description="Reinitialize scorer with offline centroids")
    allow_online_updates: Optional[bool] = Field(None, description="Enable training updates during inference")


class StoredResult(BaseModel):
    trace_id: str
    source: str
    features: Dict[str, Any]
    online_result: Dict[str, Any]
    offline_result: Optional[Dict[str, Any]] = None


class ServiceState:
    """Encapsulates scorer artifacts and mutable toggles."""

    def __init__(self, artifact_dir: str):
        self.artifact_dir = artifact_dir
        self.use_offline_centroids = True
        self.allow_online_updates = True
        self._lock = Lock()
        self._load_models()

    def _load_models(self):
        self.scorer, self.offline_model, self.cluster_context = load_deployment_pipeline(
            self.artifact_dir,
            use_offline_centroids=self.use_offline_centroids,
        )

    def reload(self):
        with self._lock:
            self._load_models()

    def online_score(self, features: Dict[str, Any], online_update_override: Optional[bool] = None) -> Dict[str, Any]:
        try:
            update_flag = self.allow_online_updates if online_update_override is None else online_update_override
            return self.scorer.predict_and_update(features, update=update_flag)
        except Exception as exc:  # pragma: no cover - FastAPI handles raising
            raise HTTPException(status_code=400, detail=f"Online scoring failed: {exc}") from exc

    def offline_score(self, features: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return run_offline_inference(features, self.scorer, self.offline_model, self.cluster_context)
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=400, detail=f"Offline scoring failed: {exc}") from exc

    def update_settings(self, *, use_offline_centroids: Optional[bool], allow_online_updates: Optional[bool]):
        reload_needed = False
        if use_offline_centroids is not None and use_offline_centroids != self.use_offline_centroids:
            self.use_offline_centroids = use_offline_centroids
            reload_needed = True
        if allow_online_updates is not None:
            self.allow_online_updates = allow_online_updates
        if reload_needed:
            self.reload()


ARTIFACT_DIR = os.getenv(
    "RISK_ARTIFACT_DIR",
    str((Path(__file__).resolve().parent / "risk_artifacts").absolute()),
)
state = ServiceState(ARTIFACT_DIR)
store_lock = Lock()
session_store: Dict[str, StoredResult] = {}
app = FastAPI(title="Investor Risk API", version="0.1.0")


def _persist_result(trace_id: str, record: StoredResult) -> None:
    with store_lock:
        session_store[trace_id] = record


def _resolve_trace_id(candidate: Optional[str]) -> str:
    return candidate or uuid4().hex


@app.get("/health")
def healthcheck():
    return {
        "status": "ok",
        "artifact_dir": ARTIFACT_DIR,
        "use_offline_centroids": state.use_offline_centroids,
        "allow_online_updates": state.allow_online_updates,
    }


@app.post("/api/v1/risk-score")
def post_user_risk_score(request: ScoreRequest):
    trace_id = _resolve_trace_id(request.trace_id)
    online_result = state.online_score(request.features, request.online_update)
    record = StoredResult(
        trace_id=trace_id,
        source="user",
        features=request.features,
        online_result=online_result,
    )
    _persist_result(trace_id, record)
    return {"trace_id": trace_id, "online_result": online_result}


@app.get("/api/v1/admin/settings")
def get_settings():
    return {
        "artifact_dir": ARTIFACT_DIR,
        "use_offline_centroids": state.use_offline_centroids,
        "allow_online_updates": state.allow_online_updates,
    }


@app.patch("/api/v1/admin/settings")
def patch_settings(request: SettingsRequest):
    if request.use_offline_centroids is None and request.allow_online_updates is None:
        raise HTTPException(status_code=400, detail="No settings provided")
    state.update_settings(
        use_offline_centroids=request.use_offline_centroids,
        allow_online_updates=request.allow_online_updates,
    )
    return get_settings()


@app.post("/api/v1/admin/offline-score")
def post_offline_score(request: ScoreRequest):
    trace_id = _resolve_trace_id(request.trace_id)
    offline_result = state.offline_score(request.features)
    online_result = state.online_score(request.features, request.online_update)
    record = StoredResult(
        trace_id=trace_id,
        source="admin",
        features=request.features,
        online_result=online_result,
        offline_result=offline_result,
    )
    _persist_result(trace_id, record)
    return {
        "trace_id": trace_id,
        "online_result": online_result,
        "offline_result": offline_result,
    }


@app.get("/api/v1/mcp/risk-score/{trace_id}")
def get_mcp_score(trace_id: str):
    with store_lock:
        record = session_store.get(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Trace ID not found")
    return record


@app.post("/api/v1/mcp/risk-score")
def post_mcp_score(request: ScoreRequest):
    trace_id = _resolve_trace_id(request.trace_id)
    online_result = state.online_score(request.features, request.online_update)
    record = StoredResult(
        trace_id=trace_id,
        source="mcp",
        features=request.features,
        online_result=online_result,
    )
    _persist_result(trace_id, record)
    return {"trace_id": trace_id, "online_result": online_result}


@app.post("/api/v1/admin/reload")
def reload_service_artifacts():
    state.reload()
    return get_settings()
