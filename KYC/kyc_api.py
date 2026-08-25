"""FastAPI service that exposes the KYC verification pipeline as HTTP endpoints.

Two personas are supported:
- End users submit Aadhaar, PAN, ITR, and selfie video assets and immediately
  receive the automated decision plus guidance.
- Company reviewers get alerted whenever an automated rejection is too close
  to the configured thresholds; they can download the evidence bundle and
  push a manual approval/rejection.
"""

from __future__ import annotations

import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from kyc_verifier import (
    VERIF_COSINE_THRESH_ID,
    VERIF_COSINE_THRESH_VIDEO,
    run_pipeline,
)

UPLOAD_ROOT = Path(__file__).resolve().parent / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

REVIEW_MARGIN = 0.07  # how close (absolute distance) to threshold triggers HITL
RISK_SCORE_CAP = 1.0

DocName = str


class SubmissionResponse(BaseModel):
    submission_id: str
    status: str
    final_decision: str
    risk_score: float
    user_message: str
    manual_review_id: Optional[str] = None


class SubmissionStatusResponse(SubmissionResponse):
    created_at: datetime
    decision_source: str


class ReviewDecision(BaseModel):
    decision: str  # "approved" or "rejected"
    notes: Optional[str] = None


class SubmissionStore:
    """Thread-safe in-memory storage for submissions and pending reviews."""

    def __init__(self) -> None:
        self._submissions: Dict[str, Dict[str, object]] = {}
        self._reviews: Dict[str, Dict[str, object]] = {}
        self._lock = threading.Lock()

    def save_submission(self, record: Dict[str, object]) -> None:
        submission_id = record["submission_id"]
        with self._lock:
            self._submissions[submission_id] = record
            review_id = record.get("manual_review_id")
            if review_id:
                review_entry = {
                    "review_id": review_id,
                    "submission_id": submission_id,
                    "user_id": record.get("user_id"),
                    "manual_reason": record.get("manual_reason"),
                    "risk_score": record.get("risk_score"),
                    "status": "pending",
                    "created_at": record.get("created_at"),
                    "files": record.get("files", {}),
                    "result": record.get("result"),
                }
                self._reviews[review_id] = review_entry

    def get_submission(self, submission_id: str) -> Dict[str, object]:
        with self._lock:
            if submission_id not in self._submissions:
                raise KeyError(submission_id)
            return self._submissions[submission_id]

    def list_pending_reviews(self) -> Dict[str, Dict[str, object]]:
        with self._lock:
            return {rid: data for rid, data in self._reviews.items() if data["status"] == "pending"}

    def get_review(self, review_id: str) -> Dict[str, object]:
        with self._lock:
            if review_id not in self._reviews:
                raise KeyError(review_id)
            return self._reviews[review_id]

    def complete_review(self, review_id: str, decision: str, notes: Optional[str]) -> Dict[str, object]:
        decision = decision.lower()
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be either 'approved' or 'rejected'")
        with self._lock:
            if review_id not in self._reviews:
                raise KeyError(review_id)
            review = self._reviews[review_id]
            if review["status"] != "pending":
                raise ValueError("review already completed")
            review["status"] = decision
            review["notes"] = notes
            submission_id = review["submission_id"]
            submission = self._submissions[submission_id]
            submission["status"] = "accepted_manual" if decision == "approved" else "rejected_manual"
            submission["decision_source"] = "manual"
            submission["result"]["final_decision"] = (
                "accept_manual" if decision == "approved" else "reject_manual"
            )
            submission["user_message"] = build_user_message(
                submission["status"], submission["result"], submission.get("manual_reason"), notes
            )
            submission["manual_notes"] = notes
            return review


store = SubmissionStore()
app = FastAPI(title="KYC Verification API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


def _persist_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    upload.file.seek(0)
    with destination.open("wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)


async def save_upload(doc_name: DocName, upload: UploadFile, dest_dir: Path) -> Path:
    suffix = Path(upload.filename or "").suffix or ".bin"
    safe_suffix = suffix.lower()
    destination = dest_dir / f"{doc_name}{safe_suffix}"
    await run_in_threadpool(_persist_upload, upload, destination)
    return destination


def compute_risk_score(result: Dict[str, object]) -> float:
    distances = result.get("detailed_scores", {})
    aadhaar_pan = float(distances.get("aadhaar_pan_distance", 1.0))
    pan_video = float(distances.get("pan_video_distance", 1.0))
    blink_count = int(distances.get("blink_count", 0))
    head_move = float(distances.get("head_movement", 0.0))

    score = 0.0
    if not result.get("aadhaar_pan_match", False):
        score = max(score, min(RISK_SCORE_CAP, (aadhaar_pan - VERIF_COSINE_THRESH_ID + 1.0) / 1.5))
    if not result.get("pan_video_match", False):
        score = max(score, min(RISK_SCORE_CAP, (pan_video - VERIF_COSINE_THRESH_VIDEO + 1.0)))
    if not result.get("liveness_pass", False):
        penalty = 0.4
        if blink_count < 1:
            penalty += 0.3
        if head_move < 0.15:
            penalty += 0.2
        score = max(score, min(RISK_SCORE_CAP, penalty))
    return round(min(score, RISK_SCORE_CAP), 3)


def needs_manual_review(result: Dict[str, object]) -> Tuple[bool, Optional[str]]:
    distances = result.get("detailed_scores", {})
    aadhaar_pan = distances.get("aadhaar_pan_distance")
    pan_video = distances.get("pan_video_distance")

    if not result.get("aadhaar_pan_match", False) and isinstance(aadhaar_pan, (float, int)):
        if 0 <= aadhaar_pan - VERIF_COSINE_THRESH_ID <= REVIEW_MARGIN:
            return True, "Aadhaar↔PAN score near threshold"
    if not result.get("pan_video_match", False) and isinstance(pan_video, (float, int)):
        if 0 <= pan_video - VERIF_COSINE_THRESH_VIDEO <= REVIEW_MARGIN:
            return True, "PAN↔Video score near threshold"
    if not result.get("liveness_pass", False):
        if result.get("detailed_scores", {}).get("head_movement", 0.0) > 0.1:
            return True, "Liveness borderline"
    return False, None


def build_user_message(
    status: str,
    result: Dict[str, object],
    manual_reason: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    status = status.lower()
    if status == "accepted_manual":
        return "Manual reviewer approved your submission."
    if status.startswith("accepted"):
        return "Verification successful. You may continue to the next step."
    if status == "manual_review_pending":
        base = "Your documents are under manual review due to borderline automated scores."
        if manual_reason:
            base += f" Reason: {manual_reason}."
        return base
    if status in {"rejected", "rejected_manual", "rejected_hard"}:
        reason = notes or ", ".join(result.get("notes", [])) or "Documents did not pass verification."
        return f"Verification failed: {reason}"
    return "Processing completed."


@app.post("/api/v1/kyc/submit", response_model=SubmissionResponse)
async def submit_kyc(
    aadhaar: UploadFile = File(...),
    pan: UploadFile = File(...),
    itr: UploadFile = File(...),
    selfie_video: UploadFile = File(...),
    user_id: str = Form(...),
) -> SubmissionResponse:
    submission_id = str(uuid.uuid4())
    storage_dir = UPLOAD_ROOT / submission_id
    storage_dir.mkdir(parents=True, exist_ok=True)

    files = {}
    try:
        files["aadhaar"] = await save_upload("aadhaar", aadhaar, storage_dir)
        files["pan"] = await save_upload("pan", pan, storage_dir)
        files["itr"] = await save_upload("itr", itr, storage_dir)
        files["selfie_video"] = await save_upload("selfie", selfie_video, storage_dir)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Failed to persist uploads: {exc}") from exc

    result = await run_in_threadpool(
        run_pipeline,
        str(files["aadhaar"]),
        str(files["pan"]),
        str(files["selfie_video"]),
    )
 
    risk_score = compute_risk_score(result)
    manual_needed, manual_reason = needs_manual_review(result)

    if result.get("final_decision") == "accept":
        status = "accepted"
        manual_review_id = None
    elif manual_needed:
        status = "manual_review_pending"
        manual_review_id = str(uuid.uuid4())
    else:
        status = "rejected" if risk_score < 0.85 else "rejected_hard"
        manual_review_id = None

    user_message = build_user_message(status, result, manual_reason)
    record = {
        "submission_id": submission_id,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc),
        "files": {name: str(path) for name, path in files.items()},
        "result": result,
        "risk_score": risk_score,
        "status": status,
        "decision_source": "automated",
        "manual_review_id": manual_review_id,
        "manual_reason": manual_reason,
        "user_message": user_message,
    }
    store.save_submission(record)

    return SubmissionResponse(
        submission_id=submission_id,
        status=status,
        final_decision=result.get("final_decision", "unknown"),
        risk_score=risk_score,
        user_message=user_message,
        manual_review_id=manual_review_id,
    )


@app.get("/api/v1/kyc/status/{submission_id}", response_model=SubmissionStatusResponse)
async def submission_status(submission_id: str) -> SubmissionStatusResponse:
    try:
        record = store.get_submission(submission_id)
    except KeyError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=404, detail="Submission not found") from exc

    return SubmissionStatusResponse(
        submission_id=submission_id,
        status=record["status"],
        final_decision=record["result"].get("final_decision", "unknown"),
        risk_score=record["risk_score"],
        user_message=record["user_message"],
        manual_review_id=record.get("manual_review_id"),
        created_at=record["created_at"],
        decision_source=record.get("decision_source", "automated"),
    )


@app.get("/api/v1/kyc/review/pending")
async def pending_reviews() -> Dict[str, Dict[str, object]]:
    return store.list_pending_reviews()


@app.get("/api/v1/kyc/review/{review_id}")
async def review_detail(review_id: str) -> Dict[str, object]:
    try:
        return store.get_review(review_id)
    except KeyError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=404, detail="Review not found") from exc


@app.get("/api/v1/kyc/review/{review_id}/artifact/{artifact_name}")
async def download_artifact(review_id: str, artifact_name: str) -> FileResponse:
    try:
        review = store.get_review(review_id)
    except KeyError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=404, detail="Review not found") from exc

    artifact_path = review.get("files", {}).get(artifact_name)
    if not artifact_path:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path_obj = Path(artifact_path)
    if not path_obj.exists():
        raise HTTPException(status_code=404, detail="Artifact missing on disk")
    return FileResponse(path_obj)


@app.post("/api/v1/kyc/review/{review_id}/decision")
async def review_decision(review_id: str, payload: ReviewDecision) -> Dict[str, object]:
    try:
        review = store.complete_review(review_id, payload.decision, payload.notes)
    except KeyError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=404, detail="Review not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return review


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "kyc_api:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        reload=bool(os.getenv("UVICORN_RELOAD")),
    )
