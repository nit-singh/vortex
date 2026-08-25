"""Helper functions for running orchestration in Flask (sync context).

This module provides utilities to run async orchestration in Flask's sync context
using background threads.
"""

import asyncio
import threading
import logging
import sys
import os
import calendar
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
import requests

# Add KYC directory to path
kyc_dir = Path(__file__).resolve().parent.parent / "KYC"
if str(kyc_dir) not in sys.path:
    sys.path.insert(0, str(kyc_dir))

# Configure logging for this module with verbose output
logger = logging.getLogger(__name__)

# Ensure unified_orchestrator also logs properly
logging.getLogger("unified_orchestrator").setLevel(logging.INFO)
logging.getLogger("llm_tool_selector").setLevel(logging.INFO)


def select_closest_model_path(risk_score: float, base_checkpoint_dir: Optional[str] = None) -> Tuple[str, float]:
    """
    Select the closest model path based on risk score.
    
    Available models: 0.1, 0.3, 0.5, 0.7, 0.9
    Model path format: checkpoints_risk05/baseline.zip (where 05 = 0.5)
    
    Args:
        risk_score: Risk score value (0-100, will be scaled to 0-1.0)
        base_checkpoint_dir: Base directory for checkpoints. If None, uses SmartFolio/checkpoints
    
    Returns:
        Tuple of (model_path, closest_model_risk_score)
    """
    # Available model risk scores
    available_models = [0.1, 0.3, 0.5, 0.7, 0.9]
    
    # Scale risk score from 0-100 to 0-1.0
    # Handle both 0-100 scale and 0-1.0 scale
    if risk_score > 1.0:
        scaled_risk = risk_score / 100.0
    else:
        scaled_risk = risk_score
    
    # Clamp to 0-1.0 range
    scaled_risk = max(0.0, min(1.0, scaled_risk))
    
    # Find closest model
    closest_model = min(available_models, key=lambda x: abs(x - scaled_risk))
    
    # Convert to model path format (0.5 -> "05", 0.1 -> "01")
    model_tag = str(closest_model).replace('.', '')
    
    # Default to SmartFolio/checkpoints if not provided
    if base_checkpoint_dir is None:
        # Get SmartFolio directory relative to flask_server
        flask_server_dir = Path(__file__).resolve().parent
        project_root = flask_server_dir.parent
        base_checkpoint_dir = str(project_root / "SmartFolio" / "checkpoints")
    
    # Construct model path
    model_dir = f"{base_checkpoint_dir.rstrip('/')}_risk{model_tag}"
    model_path = os.path.join(model_dir, "baseline.zip")
    
    # Convert to absolute path
    model_path = os.path.abspath(model_path)
    
    logger.info(
        f"[PORTFOLIO] Selected model: risk_score={risk_score:.2f} "
        f"(scaled={scaled_risk:.2f}) -> closest={closest_model} -> {model_path}"
    )
    
    return model_path, closest_model


def calculate_sliding_window_dates(reference_date: Optional[datetime] = None) -> Tuple[str, str]:
    """
    Calculate sliding window dates for portfolio allocation.
    
    If reference_date is Jan 7, 2025:
    - end_date = Dec 31, 2024 (last day of previous month)
    - start_date = 6 months before end_date (June 30, 2024)
    
    If reference_date is Feb 1, 2025:
    - end_date = Jan 31, 2025 (last day of previous month)
    - start_date = 6 months before end_date (July 31, 2024)
    
    Args:
        reference_date: Reference date (default: today)
    
    Returns:
        Tuple of (start_date, end_date) as YYYY-MM-DD strings
    """
    if reference_date is None:
        reference_date = datetime.now()
    
    # Get last day of previous month
    if reference_date.month == 1:
        # If January, previous month is December of previous year
        end_year = reference_date.year - 1
        end_month = 12
    else:
        end_year = reference_date.year
        end_month = reference_date.month - 1
    
    # Get last day of that month
    last_day = calendar.monthrange(end_year, end_month)[1]
    end_date = datetime(end_year, end_month, last_day)
    
    # Calculate start date (6 months before end_date)
    if end_month <= 6:
        # Need to go to previous year
        start_year = end_year - 1
        start_month = end_month + 6
    else:
        start_year = end_year
        start_month = end_month - 6
    
    # Get last day of start month
    start_last_day = calendar.monthrange(start_year, start_month)[1]
    start_date = datetime(start_year, start_month, start_last_day)
    
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def trigger_portfolio_allocation(
    risk_score: float,
    user_id: str,
    api_url: str = "http://localhost:8000",
    reference_date: Optional[datetime] = None,
    test_start_date: Optional[str] = None,
    test_end_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Trigger portfolio allocation API call after KYC approval.
    
    Args:
        risk_score: Risk score value (will be used to select model and pass to API)
        user_id: User ID for logging/tracking
        api_url: Base URL for the portfolio allocation API (default: http://localhost:8000)
        reference_date: Reference date for sliding window calculation (default: today)
        test_start_date: Start date for inference (YYYY-MM-DD). If None, calculated from reference_date.
        test_end_date: End date for inference (YYYY-MM-DD). If None, calculated from reference_date.
    
    Returns:
        API response dict if successful, None otherwise
    """
    try:
        # Select closest model path and get the model's risk score
        model_path, model_risk_score = select_closest_model_path(risk_score)
        
        # Check if model exists
        if not os.path.exists(model_path):
            logger.warning(
                f"[PORTFOLIO] Model path does not exist: {model_path}. "
                "Skipping portfolio allocation."
            )
            return None
        
        # Hardcoded dates for first 6 months of 2024
        if not test_start_date or not test_end_date:
            test_start_date = "2024-01-31"  # End of January 2024
            test_end_date = "2024-06-30"    # End of June 2024
        
        # Prepare inference request
        inference_url = f"{api_url.rstrip('/')}/inference"
        request_payload = {
            "model_path": model_path,
            "market": "custom",
            "horizon": "1",
            "relation_type": "hy",
            "test_start_date": test_start_date,
            "test_end_date": test_end_date,
            "deterministic": False,
            "ind_yn": True,
            "pos_yn": True,
            "neg_yn": True,
            "lookback": 30,
            "input_dim": 0,
            "risk_score": model_risk_score,  # Use the model's risk score (0.1, 0.3, 0.5, 0.7, 0.9)
            "output_dir": "./logs/api",
        }
        
        logger.info(
            f"[PORTFOLIO] Calling portfolio allocation API for user_id={user_id} "
            f"with model_risk_score={model_risk_score}, model={model_path}, "
            f"dates={test_start_date} to {test_end_date}"
        )
        
        # Make API call
        response = requests.post(
            inference_url,
            json=request_payload,
            timeout=300,  # 5 minute timeout for inference
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(
                f"[PORTFOLIO] Portfolio allocation successful for user_id={user_id}. "
                f"Final portfolio value: {result.get('final_portfolio_value')}"
            )
            return result
        else:
            logger.error(
                f"[PORTFOLIO] Portfolio allocation API returned error: "
                f"status={response.status_code}, response={response.text}"
            )
            return None
            
    except requests.exceptions.ConnectionError:
        logger.warning(
            f"[PORTFOLIO] Could not connect to portfolio allocation API at {api_url}. "
            "Make sure the SmartFolio API server is running."
        )
        return None
    except Exception as e:
        logger.error(
            f"[PORTFOLIO] Failed to trigger portfolio allocation for user_id={user_id}: {e}",
            exc_info=True
        )
        return None


def get_user_risk_score_from_payload(user_id: str, payload_store_instance: Any) -> Optional[float]:
    """
    Get user risk score from payload store.
    
    Args:
        user_id: User ID
        payload_store_instance: PayloadStore instance
    
    Returns:
        Risk score value if found, None otherwise
    """
    try:
        if payload_store_instance is None:
            logger.warning("[PORTFOLIO] Payload store not available")
            return None
        
        payload = payload_store_instance.get(user_id)
        if payload is None:
            logger.warning(f"[PORTFOLIO] No payload found for user_id={user_id}")
            return None
        
        # Extract risk score from orchestration result
        orchestration_result = payload.metadata.get("orchestration_result", {})
        risk_score_dict = orchestration_result.get("risk_score")
        
        if risk_score_dict is None:
            logger.warning(f"[PORTFOLIO] No risk score found in payload for user_id={user_id}")
            return None
        
        risk_score_value = risk_score_dict.get("risk_score")
        if risk_score_value is None:
            logger.warning(f"[PORTFOLIO] Risk score dict missing 'risk_score' key for user_id={user_id}")
            return None
        
        return float(risk_score_value)
    
    except Exception as e:
        logger.error(f"[PORTFOLIO] Failed to get risk score for user_id={user_id}: {e}", exc_info=True)
        return None


def get_orchestrator_config_from_env() -> Any:
    """
    Create OrchestratorConfig from environment variables.
    
    Environment variables (with defaults):
        KYCV_MCP_URL: Full URL or constructed from KYCV_MCP_PORT
        RISK_MCP_URL: Full URL or constructed from RISK_MCP_PORT
        KYCV_MCP_PORT: 8123 (used if KYCV_MCP_URL not set)
        RISK_MCP_PORT: 8124 (used if RISK_MCP_URL not set)
        RISK_ARTIFACT_DIR: ./risk_artifacts
        USE_LLM_SELECTOR: true
        OPENAI_API_KEY: (none)
    
    Returns:
        OrchestratorConfig instance
    """
    from unified_orchestrator import OrchestratorConfig
    
    # Build URLs from ports if full URLs not provided
    kycv_port = os.environ.get("KYCV_MCP_PORT", "8123")
    risk_port = os.environ.get("RISK_MCP_PORT", "8124")
    
    kycv_url = os.environ.get("KYCV_MCP_URL", f"http://127.0.0.1:{kycv_port}/mcp")
    risk_url = os.environ.get("RISK_MCP_URL", f"http://127.0.0.1:{risk_port}/mcp")
    # Remove trailing slash if present to avoid redirect issues
    kycv_url = kycv_url.rstrip('/')
    risk_url = risk_url.rstrip('/')
    
    # Get artifact dir - check both KYC folder and relative
    risk_artifact_dir = os.environ.get("RISK_ARTIFACT_DIR")
    if not risk_artifact_dir:
        # Default to KYC/risk_artifacts
        risk_artifact_dir = str(kyc_dir / "risk_artifacts")
    
    config = OrchestratorConfig(
        kycv_mcp_url=kycv_url,
        risk_mcp_url=risk_url,
        risk_artifact_dir=risk_artifact_dir,
        use_llm_selector=os.environ.get("USE_LLM_SELECTOR", "true").lower() == "true",
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
    )
    
    logger.info(
        "[CONFIG] Orchestrator config: kycv_url=%s, risk_url=%s, artifacts=%s",
        config.kycv_mcp_url, config.risk_mcp_url, config.risk_artifact_dir
    )
    
    return config


def run_orchestration_in_thread(
    user_id: str,
    task_id: Optional[str] = None,
    run_kycv: bool = True,
    run_risk_score: bool = True,
    generate_report: bool = True,
    plan_alerts: bool = True,
    config: Optional[Any] = None,
    payload_store_instance: Optional[Any] = None,
    users_collection_instance: Optional[Any] = None,
) -> threading.Thread:
    """
    Run orchestration in a background thread (for Flask).
    
    This function creates a new event loop in a thread and runs the async
    orchestration. It's designed to be called from Flask's sync context.
    
    Args:
        user_id: User ID to orchestrate
        task_id: Optional task ID (generated if not provided)
        run_kycv: Whether to run KYCV MCP server
        run_risk_score: Whether to run RiskScore MCP server
        generate_report: Whether to generate report
        plan_alerts: Whether to plan alerts
        config: Optional orchestrator config
        payload_store_instance: Optional PayloadStore instance (MongoDB)
    
    Returns:
        The thread object running the orchestration
    """
    # Capture variables in closure (avoid shadowing issues)
    _user_id = user_id
    _task_id = task_id or f"orch-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    _run_kycv = run_kycv
    _run_risk_score = run_risk_score
    _generate_report = generate_report
    _plan_alerts = plan_alerts
    _config = config
    _payload_store_instance = payload_store_instance
    _users_collection_instance = users_collection_instance
    
    def _run_in_thread():
        """Run orchestration in thread-local event loop."""
        loop = None
        try:
            logger.info(
                "[ORCH-THREAD] Starting orchestration for user_id=%s, task_id=%s",
                _user_id, _task_id
            )
            logger.info(
                "[ORCH-THREAD] Options: kycv=%s, risk=%s, report=%s, alerts=%s",
                _run_kycv, _run_risk_score, _generate_report, _plan_alerts
            )
            
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Import here to avoid circular imports
            logger.info("[ORCH-THREAD] Importing UnifiedOrchestrator...")
            from unified_orchestrator import UnifiedOrchestrator, OrchestratorConfig
            
            # Create config if not provided (use env vars)
            orch_config = _config
            if orch_config is None:
                logger.info("[ORCH-THREAD] Creating config from environment variables...")
                orch_config = get_orchestrator_config_from_env()
                
                # Log MCP server URLs
                logger.info(
                    "[ORCH-THREAD] MCP URLs: KYCV=%s, Risk=%s",
                    orch_config.kycv_mcp_url, orch_config.risk_mcp_url
                )
            
            # Create orchestrator
            logger.info("[ORCH-THREAD] Creating UnifiedOrchestrator instance...")
            orchestrator = UnifiedOrchestrator(orch_config)
            
            # Override payload store if MongoDB instance provided
            if _payload_store_instance is not None:
                logger.info("[ORCH-THREAD] Using provided MongoDB payload store")
                orchestrator._store = _payload_store_instance
            else:
                logger.info("[ORCH-THREAD] Using default SQLite payload store")
            
            # Run orchestration
            logger.info("[ORCH-THREAD] Starting orchestrator.run()...")
            result = loop.run_until_complete(
                orchestrator.run(
                    user_id=_user_id,
                    task_id=_task_id,
                    run_kycv=_run_kycv,
                    run_risk_score=_run_risk_score,
                    generate_report=_generate_report,
                    plan_alerts=_plan_alerts,
                )
            )
            
            # Log detailed results
            logger.info(
                "[ORCH-THREAD] Orchestration completed for user_id=%s: status=%s",
                _user_id, result.status
            )
            logger.info(
                "[ORCH-THREAD] Actions executed: %s",
                [a.get("tool") for a in result.actions_executed]
            )
            if result.errors:
                logger.warning("[ORCH-THREAD] Errors: %s", result.errors)
            if result.kycv_report:
                logger.info("[ORCH-THREAD] KYCV report generated: %d chars", len(result.kycv_report))
            if result.risk_score:
                logger.info("[ORCH-THREAD] Risk score: %s", result.risk_score)
            
            if result.alert_plan:
                logger.info("[ORCH-THREAD] Alert plan: %s", list(result.alert_plan.keys()) if isinstance(result.alert_plan, dict) else "present")
            
            # Update user's kycApprovalStatus to "review" after orchestration completes
            # This requires manual admin review before approval
            # Note: validationStatus is separate and should be set based on image/video verification
            if result.status in ["success", "partial"] and _users_collection_instance is not None:
                try:
                    from bson import ObjectId
                    user_object_id = ObjectId(_user_id)
                    _users_collection_instance.update_one(
                        {"_id": user_object_id},
                        {
                            "$set": {
                                "kycApprovalStatus": "review",  # Admin review status
                                "updatedAt": datetime.utcnow()
                            }
                        }
                    )
                    logger.info(f"[ORCH-THREAD] Updated user kycApprovalStatus to 'review' for user_id={_user_id}")
                except Exception as update_error:
                    logger.warning(f"[ORCH-THREAD] Failed to update user kycApprovalStatus: {update_error}")
            
        except ImportError as e:
            logger.error(
                "[ORCH-THREAD] Import error for user_id=%s: %s",
                _user_id, e, exc_info=True
            )
        except ConnectionError as e:
            logger.error(
                "[ORCH-THREAD] Connection error (MCP servers may be down) for user_id=%s: %s",
                _user_id, e, exc_info=True
            )
        except Exception as e:
            logger.error(
                "[ORCH-THREAD] Orchestration failed for user_id=%s: %s",
                _user_id, e, exc_info=True
            )
        finally:
            # Clean up event loop
            if loop is not None:
                try:
                    # Cancel any pending tasks
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.close()
                    logger.info("[ORCH-THREAD] Event loop closed for user_id=%s", _user_id)
                except Exception as cleanup_error:
                    logger.warning("[ORCH-THREAD] Event loop cleanup error: %s", cleanup_error)
    
    # Start thread (non-daemon so it completes even if main thread ends)
    thread = threading.Thread(
        target=_run_in_thread,
        name=f"orchestration-{_user_id}-{_task_id}",
        daemon=False  # Let orchestration complete even if Flask exits
    )
    thread.start()
    logger.info(
        "[ORCH-MAIN] Started orchestration thread '%s' for user_id=%s",
        thread.name, user_id
    )
    return thread


def run_orchestration_sync(
    user_id: str,
    task_id: Optional[str] = None,
    run_kycv: bool = True,
    run_risk_score: bool = True,
    generate_report: bool = True,
    plan_alerts: bool = True,
    config: Optional[Any] = None,
    payload_store_instance: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Run orchestration synchronously (blocking).
    
    This is useful for debugging and testing. For production use,
    prefer run_orchestration_in_thread() for non-blocking execution.
    
    Args:
        user_id: User ID to orchestrate
        task_id: Optional task ID (generated if not provided)
        run_kycv: Whether to run KYCV MCP server
        run_risk_score: Whether to run RiskScore MCP server
        generate_report: Whether to generate report
        plan_alerts: Whether to plan alerts
        config: Optional orchestrator config
        payload_store_instance: Optional PayloadStore instance (MongoDB)
    
    Returns:
        OrchestrationResult as dict
    """
    _task_id = task_id or f"orch-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    
    try:
        logger.info(
            "[ORCH-SYNC] Starting orchestration for user_id=%s, task_id=%s",
            user_id, _task_id
        )
        
        # Create new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Import here to avoid circular imports
            from unified_orchestrator import UnifiedOrchestrator, OrchestratorConfig
            
            # Create config if not provided (use env vars)
            orch_config = config
            if orch_config is None:
                orch_config = get_orchestrator_config_from_env()
                logger.info(
                    "[ORCH-SYNC] MCP URLs: KYCV=%s, Risk=%s",
                    orch_config.kycv_mcp_url, orch_config.risk_mcp_url
                )
            
            # Create orchestrator
            orchestrator = UnifiedOrchestrator(orch_config)
            
            # Override payload store if MongoDB instance provided
            if payload_store_instance is not None:
                orchestrator._store = payload_store_instance
            
            # Run orchestration
            result = loop.run_until_complete(
                orchestrator.run(
                    user_id=user_id,
                    task_id=_task_id,
                    run_kycv=run_kycv,
                    run_risk_score=run_risk_score,
                    generate_report=generate_report,
                    plan_alerts=plan_alerts,
                )
            )
            
            logger.info(
                "[ORCH-SYNC] Completed for user_id=%s: status=%s, actions=%s",
                user_id, result.status, [a.get("tool") for a in result.actions_executed]
            )
            
            return result.to_dict()
            
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(
            "[ORCH-SYNC] Failed for user_id=%s: %s",
            user_id, e, exc_info=True
        )
        return {
            "user_id": user_id,
            "task_id": _task_id,
            "status": "failed",
            "errors": [str(e)],
        }