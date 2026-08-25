"""FastAPI endpoints for KYC payload storage and orchestration.

This module provides REST API endpoints for:
1. Storing overall KYC payloads (master_json + ml_input_json) by user_id
2. Retrieving payloads by user_id
3. Triggering orchestration flows

Run with:
    uvicorn payload_api:app --host 0.0.0.0 --port 8001 --reload
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from payload_store import (
    OverallPayload,
    PayloadStore,
    get_payload_store,
    save_overall_payload,
    get_overall_payload,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI(
    title="KYC Payload Storage API",
    description="Store and retrieve KYC payloads (master_json + ml_input_json) for orchestration",
    version="1.0.0",
)


# ============================================================================
# Pydantic Models for API
# ============================================================================

class MasterJsonInput(BaseModel):
    """Input model for master_json - full KYC verification data."""
    verification_status: Optional[Dict[str, Any]] = None
    personal_details: Optional[Dict[str, Any]] = None
    financial_details: Optional[Dict[str, Any]] = None
    family_details: Optional[Dict[str, Any]] = None
    questionnaire_responses: Optional[Dict[str, Any]] = None
    document_verification_details: Optional[Dict[str, Any]] = None
    video_verification_details: Optional[Dict[str, Any]] = None
    alerting: Optional[Dict[str, Any]] = None
    parsed_documents: Optional[Dict[str, Any]] = None
    
    model_config = {"extra": "allow"}


class MLInputJsonInput(BaseModel):
    """Input model for ml_input_json - simplified features for ML scoring."""
    age: Optional[int] = None
    dependents: Optional[int] = None
    gross_income: Optional[float] = None
    tax_paid: Optional[float] = None
    gender: Optional[str] = None
    main_occupation: Optional[str] = None
    marital_status: Optional[str] = None
    filing_timeliness: Optional[str] = None
    Q1: Optional[str] = None
    Q2: Optional[str] = None
    Q3: Optional[str] = None
    Q4: Optional[str] = None
    Q5: Optional[str] = None
    Q6: Optional[str] = None
    
    model_config = {"extra": "allow"}


class OverallPayloadInput(BaseModel):
    """Input model for storing overall payload."""
    master_json: Dict[str, Any] = Field(..., description="Full KYC verification data for KYCV MCP server")
    ml_input_json: Dict[str, Any] = Field(..., description="Simplified ML features for RiskScore MCP server")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata")


class OverallPayloadResponse(BaseModel):
    """Response model for payload operations."""
    user_id: str
    master_json: Dict[str, Any]
    ml_input_json: Dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    metadata: Dict[str, Any]


class PayloadListResponse(BaseModel):
    """Response model for listing payloads."""
    payloads: List[OverallPayloadResponse]
    total: int


class StatusUpdateInput(BaseModel):
    """Input model for status update."""
    status: str = Field(..., description="New status: pending, processing, completed, failed")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata to merge")


class OrchestrationTriggerInput(BaseModel):
    """Input model for triggering orchestration."""
    user_id: str = Field(..., description="User ID to orchestrate")
    run_kycv: bool = Field(default=True, description="Run KYCV MCP server tools")
    run_risk_score: bool = Field(default=True, description="Run RiskScore MCP server")
    generate_report: bool = Field(default=True, description="Generate KYC report")
    plan_alerts: bool = Field(default=True, description="Plan and dispatch alerts")


class OrchestrationResponse(BaseModel):
    """Response model for orchestration trigger."""
    task_id: str
    user_id: str
    status: str
    message: str


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
async def root():
    """API root - health check and info."""
    return {
        "service": "KYC Payload Storage API",
        "version": "1.0.0",
        "security": "Sensitive fields (Aadhaar, PAN, DOB) are encrypted at rest",
        "endpoints": {
            "store_payload": "POST /payloads/{user_id}",
            "get_payload": "GET /payloads/{user_id} (decrypted)",
            "get_payload_masked": "GET /payloads/{user_id}/masked (for display)",
            "get_payload_encrypted": "GET /payloads/{user_id}/encrypted (raw)",
            "get_master_json": "GET /payloads/{user_id}/master",
            "get_ml_input_json": "GET /payloads/{user_id}/ml",
            "update_status": "PATCH /payloads/{user_id}/status",
            "delete_payload": "DELETE /payloads/{user_id}",
            "list_payloads": "GET /payloads",
            "trigger_orchestration": "POST /orchestrate",
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    store = get_payload_store()
    return {
        "status": "healthy",
        "db_path": store.db_path,
        "payload_count": store.count(),
    }


@app.post("/payloads/{user_id}", response_model=OverallPayloadResponse, status_code=201)
async def store_payload(user_id: str, payload: OverallPayloadInput):
    """
    Store or update an overall KYC payload for a user.
    
    The payload consists of:
    - master_json: Full KYC verification data (sent to KYCV MCP server)
    - ml_input_json: Simplified ML features (sent to RiskScore MCP server)
    
    If a payload already exists for user_id, it will be updated.
    """
    try:
        store = get_payload_store()
        overall = OverallPayload(
            user_id=user_id,
            master_json=payload.master_json,
            ml_input_json=payload.ml_input_json,
            metadata=payload.metadata or {},
        )
        store.save(overall)
        
        logger.info("Stored payload for user_id=%s", user_id)
        
        return OverallPayloadResponse(
            user_id=overall.user_id,
            master_json=overall.master_json,
            ml_input_json=overall.ml_input_json,
            status=overall.status,
            created_at=overall.created_at,
            updated_at=overall.updated_at,
            metadata=overall.metadata,
        )
    except Exception as e:
        logger.error("Failed to store payload for user_id=%s: %s", user_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/payloads/{user_id}", response_model=OverallPayloadResponse)
async def get_payload(user_id: str):
    """Retrieve the full payload for a user (with sensitive fields decrypted)."""
    store = get_payload_store()
    payload = store.get(user_id)
    
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Payload not found for user_id: {user_id}")
    
    return OverallPayloadResponse(
        user_id=payload.user_id,
        master_json=payload.master_json,
        ml_input_json=payload.ml_input_json,
        status=payload.status,
        created_at=payload.created_at,
        updated_at=payload.updated_at,
        metadata=payload.metadata,
    )


@app.get("/payloads/{user_id}/masked", response_model=OverallPayloadResponse)
async def get_payload_masked(user_id: str):
    """
    Retrieve payload with sensitive fields MASKED (for display/logging).
    
    Sensitive data like Aadhaar, PAN are replaced with masked values:
    - Aadhaar: "XXXX XXXX 1234"
    - PAN: "XXXXXX63A"
    - DOB: "XX/XX/2005"
    
    Use this endpoint when you need to display or log user data without
    exposing sensitive PII.
    """
    store = get_payload_store()
    payload = store.get_masked(user_id)
    
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Payload not found for user_id: {user_id}")
    
    return OverallPayloadResponse(
        user_id=payload.user_id,
        master_json=payload.master_json,
        ml_input_json=payload.ml_input_json,
        status=payload.status,
        created_at=payload.created_at,
        updated_at=payload.updated_at,
        metadata=payload.metadata,
    )


@app.get("/payloads/{user_id}/encrypted")
async def get_payload_encrypted(user_id: str):
    """
    Retrieve payload with sensitive fields in ENCRYPTED form.
    
    Use this for backup/export purposes where you need the raw encrypted data.
    """
    store = get_payload_store()
    payload = store.get_encrypted(user_id)
    
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Payload not found for user_id: {user_id}")
    
    return {
        "user_id": payload.user_id,
        "master_json": payload.master_json,
        "ml_input_json": payload.ml_input_json,
        "status": payload.status,
        "created_at": payload.created_at,
        "updated_at": payload.updated_at,
        "metadata": payload.metadata,
        "_note": "Sensitive fields are encrypted (prefixed with 'ENC:')"
    }


@app.get("/payloads/{user_id}/master")
async def get_master_json(user_id: str):
    """Retrieve only the master_json for a user (for KYCV MCP server)."""
    store = get_payload_store()
    master = store.get_master_json(user_id)
    
    if master is None:
        raise HTTPException(status_code=404, detail=f"Payload not found for user_id: {user_id}")
    
    return {"user_id": user_id, "master_json": master}


@app.get("/payloads/{user_id}/ml")
async def get_ml_input_json(user_id: str):
    """Retrieve only the ml_input_json for a user (for RiskScore MCP server)."""
    store = get_payload_store()
    ml_input = store.get_ml_input_json(user_id)
    
    if ml_input is None:
        raise HTTPException(status_code=404, detail=f"Payload not found for user_id: {user_id}")
    
    return {"user_id": user_id, "ml_input_json": ml_input}


@app.patch("/payloads/{user_id}/status")
async def update_status(user_id: str, update: StatusUpdateInput):
    """Update the processing status of a payload."""
    store = get_payload_store()
    
    if not store.get(user_id):
        raise HTTPException(status_code=404, detail=f"Payload not found for user_id: {user_id}")
    
    valid_statuses = {"pending", "processing", "completed", "failed"}
    if update.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid_statuses}"
        )
    
    store.update_status(user_id, update.status, update.metadata)
    
    return {"user_id": user_id, "status": update.status, "message": "Status updated"}


@app.delete("/payloads/{user_id}")
async def delete_payload(user_id: str):
    """Delete a payload."""
    store = get_payload_store()
    
    if not store.delete(user_id):
        raise HTTPException(status_code=404, detail=f"Payload not found for user_id: {user_id}")
    
    return {"user_id": user_id, "message": "Payload deleted"}


@app.get("/payloads", response_model=PayloadListResponse)
async def list_payloads(status: Optional[str] = None, limit: int = 100):
    """List all payloads, optionally filtered by status."""
    store = get_payload_store()
    payloads = store.list_all(status=status, limit=limit)
    
    return PayloadListResponse(
        payloads=[
            OverallPayloadResponse(
                user_id=p.user_id,
                master_json=p.master_json,
                ml_input_json=p.ml_input_json,
                status=p.status,
                created_at=p.created_at,
                updated_at=p.updated_at,
                metadata=p.metadata,
            )
            for p in payloads
        ],
        total=store.count(status),
    )


@app.get("/payloads/ids/all")
async def list_user_ids():
    """List all stored user IDs."""
    store = get_payload_store()
    return {"user_ids": store.list_user_ids()}


# ============================================================================
# Orchestration Trigger Endpoint
# ============================================================================

# Import orchestrator (will be created next)
# This endpoint triggers the full orchestration flow

@app.post("/orchestrate", response_model=OrchestrationResponse)
async def trigger_orchestration(
    request: OrchestrationTriggerInput,
    background_tasks: BackgroundTasks
):
    """
    Trigger the KYC orchestration flow for a user.
    
    This endpoint:
    1. Fetches the payload from the database by user_id
    2. Calls KYCV MCP server with master_json (generate report, plan alerts, etc.)
    3. Uses LLM to decide which tools to execute
    4. Calls RiskScore MCP server with ml_input_json
    5. Updates the payload status with results
    
    The orchestration runs in the background and returns immediately with a task_id.
    """
    store = get_payload_store()
    
    # Verify payload exists
    payload = store.get(request.user_id)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"Payload not found for user_id: {request.user_id}. Store payload first using POST /payloads/{{user_id}}"
        )
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Update status to processing
    store.update_status(request.user_id, "processing", {"task_id": task_id})
    
    # Import and run orchestration in background
    try:
        from unified_orchestrator import run_orchestration_background
        background_tasks.add_task(
            run_orchestration_background,
            task_id=task_id,
            user_id=request.user_id,
            run_kycv=request.run_kycv,
            run_risk_score=request.run_risk_score,
            generate_report=request.generate_report,
            plan_alerts=request.plan_alerts,
        )
        
        return OrchestrationResponse(
            task_id=task_id,
            user_id=request.user_id,
            status="processing",
            message="Orchestration started. Check payload status for results.",
        )
    except ImportError:
        # Orchestrator not yet implemented - return info
        store.update_status(request.user_id, "pending", {"task_id": task_id, "error": "orchestrator_not_ready"})
        return OrchestrationResponse(
            task_id=task_id,
            user_id=request.user_id,
            status="pending",
            message="Orchestrator module not yet available. Payload stored and ready for processing.",
        )


# ============================================================================
# Run Application
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
