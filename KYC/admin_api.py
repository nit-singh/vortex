"""Admin API for Risk Scoring Model Management.

This API provides frontend/dashboard endpoints to:
1. View current model settings
2. Toggle offline/online centroids
3. Enable/disable online learning
4. Reload model to original state
5. View model drift statistics

Usage:
    uvicorn admin_api:app --host 0.0.0.0 --port 8080

Frontend can call these REST endpoints directly.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Risk Model Admin API",
    description="Dashboard controls for risk scoring model",
    version="1.0.0",
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for your frontend domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MCP Server URL
RISK_MCP_URL = os.getenv("RISK_MCP_URL", "http://127.0.0.1:8124/mcp/")


# ============================================================================
# Models
# ============================================================================

class AdminSettings(BaseModel):
    use_offline_centroids: bool = Field(
        True, 
        description="Use fixed offline centroids (recommended for production)"
    )
    allow_online_updates: bool = Field(
        True, 
        description="Allow model to learn from new data points"
    )


class ReloadRequest(BaseModel):
    reset_to_original: bool = Field(
        True, 
        description="Reset all settings to default when reloading"
    )


class SettingsResponse(BaseModel):
    use_offline_centroids: bool
    allow_online_updates: bool
    artifact_dir: Optional[str]
    model_loaded: bool
    online_update_count: int
    drift_status: str


# ============================================================================
# Helper: Call MCP Tool
# ============================================================================

async def call_mcp_tool(tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
    """Call a tool on the Risk MCP server."""
    arguments = arguments or {}
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(RISK_MCP_URL, json=payload)
            response.raise_for_status()
            
            result = response.json()
            
            # Extract the result from MCP response
            if "result" in result and "content" in result["result"]:
                content = result["result"]["content"]
                if content and len(content) > 0:
                    return json.loads(content[0].get("text", "{}"))
            
            if "error" in result:
                raise HTTPException(status_code=500, detail=result["error"])
            
            return result
            
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503, 
            detail=f"Risk MCP server not available at {RISK_MCP_URL}"
        )
    except Exception as e:
        logger.error("MCP call failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Check if admin API and MCP server are healthy."""
    try:
        mcp_status = await call_mcp_tool("get_status", {"sentinel": 0})
        return {
            "admin_api": "ok",
            "mcp_server": "ok",
            "model_loaded": mcp_status.get("loaded", False),
        }
    except HTTPException as e:
        return {
            "admin_api": "ok",
            "mcp_server": "unavailable",
            "error": e.detail,
        }


@app.get("/api/admin/settings", response_model=SettingsResponse)
async def get_settings():
    """Get current model settings for dashboard display."""
    result = await call_mcp_tool("get_admin_settings", {"sentinel": 0})
    return SettingsResponse(**result)


@app.patch("/api/admin/settings")
async def update_settings(settings: AdminSettings):
    """
    Update model settings from dashboard.
    
    Toggle between:
    - **Offline centroids (stable)**: Fixed predictions, no drift
    - **Online centroids (adaptive)**: Model learns from new data
    
    Example:
    ```json
    {
        "use_offline_centroids": false,
        "allow_online_updates": true
    }
    ```
    """
    result = await call_mcp_tool("update_admin_settings", {
        "use_offline_centroids": settings.use_offline_centroids,
        "allow_online_updates": settings.allow_online_updates,
    })
    return result


@app.post("/api/admin/reload")
async def reload_model(request: ReloadRequest = ReloadRequest()):
    """
    Reload model to original trained state.
    
    Use this when:
    - Model has drifted too far
    - Need to reset after experimentation
    - Starting fresh for a new period
    
    Set `reset_to_original=true` to also reset settings to defaults.
    """
    result = await call_mcp_tool("reload_model", {
        "reset_to_original": request.reset_to_original,
    })
    return result


@app.get("/api/admin/status")
async def get_model_status():
    """Get detailed model status including drift indicators."""
    status = await call_mcp_tool("get_status", {"sentinel": 0})
    settings = await call_mcp_tool("get_admin_settings", {"sentinel": 0})
    
    # Determine health status
    update_count = status.get("online_update_count", 0)
    using_offline = settings.get("use_offline_centroids", True)
    
    if using_offline:
        health = "stable"
        health_message = "Using fixed offline centroids - predictions are consistent"
    elif update_count > 1000:
        health = "warning"
        health_message = f"Model has {update_count} online updates - consider reloading"
    elif update_count > 100:
        health = "info"
        health_message = f"Model has {update_count} online updates - monitor for drift"
    else:
        health = "ok"
        health_message = "Model is healthy"
    
    return {
        "health": health,
        "health_message": health_message,
        "model_loaded": status.get("loaded", False),
        "artifact_dir": status.get("artifact_dir"),
        "num_clusters": status.get("num_clusters"),
        "cluster_labels": status.get("cluster_to_label"),
        "online_update_count": update_count,
        "settings": {
            "use_offline_centroids": using_offline,
            "allow_online_updates": settings.get("allow_online_updates", True),
        },
        "recommendations": _get_recommendations(using_offline, update_count),
    }


def _get_recommendations(using_offline: bool, update_count: int) -> list:
    """Generate recommendations based on current state."""
    recs = []
    
    if not using_offline and update_count > 500:
        recs.append({
            "priority": "high",
            "action": "Consider reloading model or switching to offline centroids",
            "reason": f"Model has drifted with {update_count} updates",
        })
    
    if not using_offline:
        recs.append({
            "priority": "info",
            "action": "Monitor prediction consistency",
            "reason": "Online learning is enabled - centroids may drift",
        })
    
    if using_offline:
        recs.append({
            "priority": "info", 
            "action": "No action needed",
            "reason": "Using stable offline centroids",
        })
    
    return recs


@app.get("/api/admin/cluster-info")
async def get_cluster_info():
    """Get cluster context and risk ranges for dashboard visualization."""
    context = await call_mcp_tool("get_cluster_context", {"sentinel": 0})
    ranges = await call_mcp_tool("get_risk_ranges", {"sentinel": 0})
    
    return {
        "clusters": context.get("cluster_to_label"),
        "distance_stats": context.get("cluster_distance_stats"),
        "risk_ranges": ranges,
    }


# ============================================================================
# Drift Monitoring Endpoints (for Graphs/Charts)
# ============================================================================

@app.get("/api/admin/drift/metrics")
async def get_drift_metrics():
    """
    Get current drift metrics for dashboard gauges.
    
    Returns:
    - Per-cluster centroid drift from original
    - Overall drift health status
    - Recent drift alert rate
    """
    result = await call_mcp_tool("get_drift_metrics", {"sentinel": 0})
    return result


@app.get("/api/admin/drift/history")
async def get_drift_history(limit: int = 100):
    """
    Get drift history for time-series charts.
    
    Returns chart-ready data:
    - timestamps
    - total_drift over time
    - per_cluster_drift over time
    - avg_scores over time
    
    Use with Chart.js, Recharts, or similar.
    """
    result = await call_mcp_tool("get_drift_history", {"limit": limit})
    return result


@app.get("/api/admin/drift/predictions")
async def get_prediction_distribution(limit: int = 100):
    """
    Get prediction distribution for pie/bar charts.
    
    Returns:
    - Cluster distribution (pie chart)
    - Score histogram (bar chart)
    - Score statistics
    """
    result = await call_mcp_tool("get_prediction_distribution", {"limit": limit})
    return result


@app.get("/api/admin/drift/dashboard")
async def get_drift_dashboard():
    """
    Get all drift data in one call for dashboard.
    
    Combines metrics, history, and distribution for full dashboard render.
    """
    metrics = await call_mcp_tool("get_drift_metrics", {"sentinel": 0})
    history = await call_mcp_tool("get_drift_history", {"limit": 50})
    distribution = await call_mcp_tool("get_prediction_distribution", {"limit": 100})
    settings = await call_mcp_tool("get_admin_settings", {"sentinel": 0})
    
    # Determine overall health
    health = "stable"
    alerts = []
    
    if not settings.get("use_offline_centroids"):
        total_drift = metrics.get("total_centroid_drift", 0)
        if total_drift > 1.0:
            health = "critical"
            alerts.append("High centroid drift detected - consider reloading model")
        elif total_drift > 0.5:
            health = "warning"
            alerts.append("Moderate centroid drift - monitor closely")
        elif total_drift > 0.1:
            health = "info"
            alerts.append("Low drift detected - model is adapting")
    
    drift_rate = metrics.get("drift_alert_rate", 0)
    if drift_rate > 0.1:
        alerts.append(f"High reconstruction error rate: {drift_rate:.1%}")
    
    return {
        "health": health,
        "alerts": alerts,
        "settings": {
            "mode": "stable" if settings.get("use_offline_centroids") else "adaptive",
            "online_updates": settings.get("allow_online_updates"),
            "update_count": metrics.get("total_updates", 0),
        },
        "metrics": metrics,
        "history": history.get("chart_data", {}),
        "distribution": distribution,
    }


# ============================================================================
# Frontend-Friendly Endpoints
# ============================================================================

@app.post("/api/admin/switch-to-offline")
async def switch_to_offline_mode():
    """Quick action: Switch to stable offline mode."""
    result = await call_mcp_tool("update_admin_settings", {
        "use_offline_centroids": True,
        "allow_online_updates": False,
    })
    return {
        "action": "switched_to_offline",
        "message": "Model now uses fixed offline centroids. Predictions will be consistent.",
        "details": result,
    }


@app.post("/api/admin/switch-to-online")
async def switch_to_online_mode():
    """Quick action: Switch to adaptive online mode."""
    result = await call_mcp_tool("update_admin_settings", {
        "use_offline_centroids": False,
        "allow_online_updates": True,
    })
    return {
        "action": "switched_to_online",
        "message": "Model now uses online learning. Centroids will adapt to new data.",
        "warning": "Monitor for drift. Reload model if predictions become inconsistent.",
        "details": result,
    }


@app.post("/api/admin/emergency-reset")
async def emergency_reset():
    """Emergency action: Reset everything to original state."""
    result = await call_mcp_tool("reload_model", {
        "reset_to_original": True,
    })
    return {
        "action": "emergency_reset",
        "message": "Model reset to original trained state with default settings.",
        "details": result,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
