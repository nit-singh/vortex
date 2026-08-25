"""Pathway-powered Investor Risk Scorer MCP server.

This module exposes the investor risk scorer via Pathway's MCP server so that
LLM agents can call the existing load/score/status routines, but through the
official Pathway transport (streamable HTTP or stdio).

Usage:
    python MCP_Server_RiskScore.py --artifact-dir ./risk_artifacts \
        --host 127.0.0.1 --port 8123

The resulting server exposes the following tools:
    • load_artifacts
    • score_online
    • score_offline
    • get_status
    • get_cluster_context (replacement for the previous resource)
    • get_risk_ranges (replacement for the previous resource)

Pair this server with `fastmcp` or any other MCP-compatible client.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from contextlib import contextmanager
from typing import Any, Dict, Optional

import pathway as pw
from pathway.xpacks.llm.mcp_server import McpServable, McpServer, PathwayMcp

import pathway as pw
pw.set_license_key(os.getenv("PW_LIKEY"))

from investor_risk_scorer import (  # Import from local module
    OnlineRiskScorer,
    load_deployment_pipeline,
    run_offline_inference,
)

try:
    from kyc_observability import track_tool_invocation
except ImportError:  # pragma: no cover - optional dependency
    @contextmanager
    def track_tool_invocation(*_args, **_kwargs):
        yield None


# Configure logging once for the module
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class InvestorRiskScorerServable(McpServable):
    """Pathway McpServable wiring investor risk scorer business logic."""

    class LoadArtifactsSchema(pw.Schema):
        artifact_dir: str
        use_offline_centroids: bool = pw.column_definition(default_value=True)

    class ScoreOnlineSchema(pw.Schema):
        user: pw.Json
        update: bool = pw.column_definition(default_value=False)

    class ScoreOfflineSchema(pw.Schema):
        user: pw.Json

    class EmptyRequestSchema(pw.Schema):
        sentinel: int = pw.column_definition(default_value=0)

    class AdminSettingsSchema(pw.Schema):
        use_offline_centroids: bool = pw.column_definition(default_value=True)
        allow_online_updates: bool = pw.column_definition(default_value=True)

    class ReloadSchema(pw.Schema):
        reset_to_original: bool = pw.column_definition(default_value=True)

    class DriftHistorySchema(pw.Schema):
        limit: int = pw.column_definition(default_value=100)

    def __init__(self, artifact_dir: Optional[str] = None):
        self.artifact_dir: Optional[str] = None
        self._scorer: Optional[OnlineRiskScorer] = None
        self._offline_model: Optional[Any] = None
        self._cluster_context: Optional[Dict[str, Any]] = None
        
        # Admin settings
        self._use_offline_centroids: bool = True
        self._allow_online_updates: bool = True
        self._original_artifact_dir: Optional[str] = artifact_dir
        
        # Drift tracking
        self._drift_history: list = []  # Store drift measurements over time
        self._prediction_history: list = []  # Store recent predictions for analysis
        self._original_centroids: Optional[Any] = None  # Store original centroids for comparison

        if artifact_dir:
            self._load_artifacts(artifact_dir, use_offline_centroids=True)

    # ------------------------------------------------------------------
    # McpServable plumbing
    # ------------------------------------------------------------------
    def register_mcp(self, server: McpServer) -> None:
        """Expose investor risk scoring tools via Pathway MCP server."""

        server.tool(
            "load_artifacts",
            request_handler=self._tool_load_artifacts,
            schema=self.LoadArtifactsSchema,
            title="Load investor risk artifacts",
        )
        server.tool(
            "score_online",
            request_handler=self._tool_score_online,
            schema=self.ScoreOnlineSchema,
            title="Score investor risk online",
        )
        server.tool(
            "score_offline",
            request_handler=self._tool_score_offline,
            schema=self.ScoreOfflineSchema,
            title="Score investor risk offline",
        )
        server.tool(
            "get_status",
            request_handler=self._tool_get_status,
            schema=self.EmptyRequestSchema,
            title="Investor risk server status",
            annotations={"readOnlyHint": True, "idempotentHint": True},
        )
        server.tool(
            "get_cluster_context",
            request_handler=self._tool_get_cluster_context,
            schema=self.EmptyRequestSchema,
            title="Cluster label mapping",
            annotations={"readOnlyHint": True, "idempotentHint": True},
        )
        server.tool(
            "get_risk_ranges",
            request_handler=self._tool_get_risk_ranges,
            schema=self.EmptyRequestSchema,
            title="Risk label ranges",
            annotations={"readOnlyHint": True, "idempotentHint": True},
        )
        
        # Admin tools for dashboard control
        server.tool(
            "get_admin_settings",
            request_handler=self._tool_get_admin_settings,
            schema=self.EmptyRequestSchema,
            title="Get current admin settings",
            annotations={"readOnlyHint": True, "idempotentHint": True},
        )
        server.tool(
            "update_admin_settings",
            request_handler=self._tool_update_admin_settings,
            schema=self.AdminSettingsSchema,
            title="Update admin settings (offline centroids, online updates)",
        )
        server.tool(
            "reload_model",
            request_handler=self._tool_reload_model,
            schema=self.ReloadSchema,
            title="Reload model to original state",
        )
        server.tool(
            "get_drift_metrics",
            request_handler=self._tool_get_drift_metrics,
            schema=self.EmptyRequestSchema,
            title="Get current drift metrics",
            annotations={"readOnlyHint": True, "idempotentHint": True},
        )
        server.tool(
            "get_drift_history",
            request_handler=self._tool_get_drift_history,
            schema=self.DriftHistorySchema,
            title="Get drift history for visualization",
            annotations={"readOnlyHint": True, "idempotentHint": True},
        )
        server.tool(
            "get_prediction_distribution",
            request_handler=self._tool_get_prediction_distribution,
            schema=self.DriftHistorySchema,
            title="Get prediction distribution stats",
            annotations={"readOnlyHint": True, "idempotentHint": True},
        )

    # ------------------------------------------------------------------
    # Core business operations reused across tools
    # ------------------------------------------------------------------
    def _load_artifacts(self, artifact_dir: str, use_offline_centroids: bool = True) -> None:
        artifact_path = os.path.abspath(artifact_dir)
        if not os.path.isdir(artifact_path):
            raise FileNotFoundError(f"Artifact directory not found: {artifact_path}")

        logger.info("Loading artifacts from %s (offline centroids=%s)", artifact_path, use_offline_centroids)
        scorer, offline_model, cluster_context = load_deployment_pipeline(
            artifact_path, use_offline_centroids=use_offline_centroids
        )
        self._scorer = scorer
        self._offline_model = offline_model
        self._cluster_context = cluster_context
        self.artifact_dir = artifact_path
        
        # Store original centroids for drift comparison
        if self._original_centroids is None and cluster_context:
            import numpy as np
            centroids = cluster_context.get("centroids")
            if centroids is not None:
                self._original_centroids = np.array(centroids).copy()
        
        logger.info("Artifacts loaded successfully")

    def _ensure_loaded(self) -> None:
        if self._scorer is None:
            raise RuntimeError("Artifacts not loaded. Call load_artifacts first.")

    @staticmethod
    def _format_response(payload: Dict[str, Any]) -> str:
        return json.dumps(payload, indent=2, sort_keys=True)

    @staticmethod
    def _json_to_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, pw.Json):
            return value.value  # type: ignore[return-value]
        if isinstance(value, dict):
            return value
        raise TypeError("User payload must be a JSON object")

    # ------------------------------------------------------------------
    # Tool adapters (each returns a pw.Table with a `result` column)
    # ------------------------------------------------------------------
    def _tool_load_artifacts(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _load(artifact_dir: str, use_offline: bool) -> str:
            meta = {
                "artifact_dir": artifact_dir,
                "use_offline_centroids": bool(use_offline),
            }
            with track_tool_invocation("risk.load_artifacts", metadata=meta):
                self._load_artifacts(artifact_dir, bool(use_offline))
                cluster_to_label = (self._cluster_context or {}).get("cluster_to_label", {})
                return self._format_response(
                    {
                        "status": "ok",
                        "artifact_dir": self.artifact_dir,
                        "num_clusters": len(cluster_to_label),
                    }
                )

        return rows.select(
            result=_load(pw.this.artifact_dir, pw.this.use_offline_centroids)
        )

    def _tool_score_online(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _score(user_payload: Any, update_flag: bool) -> str:
            user = self._json_to_dict(user_payload)
            meta = {
                "fields": sorted(user.keys()),
                "update_requested": bool(update_flag),
            }
            with track_tool_invocation("risk.score_online", metadata=meta):
                # Check if artifacts are loaded, return error if not
                if self._scorer is None:
                    error_response = {
                        "error": "Artifacts not loaded",
                        "message": "Call load_artifacts first before scoring",
                        "artifact_dir": self.artifact_dir or "not set",
                    }
                    return self._format_response(error_response)
                
                # Respect admin setting: only allow updates if admin permits
                actual_update = bool(update_flag) and self._allow_online_updates
                result = self._scorer.predict_and_update(user, update=actual_update)
                result["online_update_applied"] = actual_update
                result["admin_allows_updates"] = self._allow_online_updates
                
                # Track prediction for drift analysis
                self._track_prediction(result)
                
                return self._format_response(result)

        return rows.select(result=_score(pw.this.user, pw.this.update))
    
    def _track_prediction(self, result: Dict[str, Any]) -> None:
        """Track prediction for drift analysis."""
        import time
        
        prediction_record = {
            "timestamp": time.time(),
            "cluster_id": result.get("cluster_id"),
            "risk_label": result.get("risk_label"),
            "risk_score": result.get("risk_score"),
            "distance": result.get("distance"),
            "reconstruction_error": result.get("reconstruction_error"),
            "drift_detected": result.get("drift_detected", False),
        }
        
        self._prediction_history.append(prediction_record)
        
        # Keep only last 1000 predictions
        if len(self._prediction_history) > 1000:
            self._prediction_history = self._prediction_history[-1000:]
        
        # Record drift snapshot every 10 predictions
        if len(self._prediction_history) % 10 == 0:
            self._record_drift_snapshot()

    def _tool_score_offline(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _score(user_payload: Any) -> str:
            user = self._json_to_dict(user_payload)
            meta = {"fields": sorted(user.keys())}
            with track_tool_invocation("risk.score_offline", metadata=meta):
                if self._scorer is None:
                    error_response = {
                        "error": "Artifacts not loaded",
                        "message": "Call load_artifacts first before scoring",
                        "artifact_dir": self.artifact_dir or "not set",
                    }
                    return self._format_response(error_response)
                
                result = run_offline_inference(
                    user,
                    self._scorer,
                    self._offline_model,
                    self._cluster_context,
                )
                return self._format_response(result)

        return rows.select(result=_score(pw.this.user))

    def _tool_get_status(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _status(_sentinel: int) -> str:
            status: Dict[str, Any] = {
                "loaded": self._scorer is not None,
                "artifact_dir": self.artifact_dir,
            }
            if self._scorer is not None:
                cluster_labels = (self._cluster_context or {}).get("cluster_to_label", {})
                status.update(
                    {
                        "num_clusters": len(cluster_labels),
                        "cluster_to_label": cluster_labels,
                        "online_update_count": self._scorer.update_cnt,
                    }
                )
            
            with track_tool_invocation("risk.get_status", metadata={"artifact_dir": self.artifact_dir}):
                return self._format_response(status)

        return rows.select(result=_status(pw.this.sentinel))

    def _tool_get_cluster_context(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _context(_sentinel: int) -> str:
            with track_tool_invocation("risk.get_cluster_context"):
                if self._scorer is None:
                    error_response = {
                        "error": "Artifacts not loaded",
                        "message": "Call load_artifacts first to get cluster context",
                        "artifact_dir": self.artifact_dir or "not set",
                    }
                    return self._format_response(error_response)
                
                context = self._cluster_context or {}
                payload = {
                    "cluster_to_label": context.get("cluster_to_label"),
                    "cluster_distance_stats": context.get("cluster_distance_stats"),
                }
                return self._format_response(payload)

        return rows.select(result=_context(pw.this.sentinel))

    def _tool_get_risk_ranges(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _risk_ranges(_sentinel: int) -> str:
            with track_tool_invocation("risk.get_risk_ranges"):
                if self._scorer is None:
                    error_response = {
                        "error": "Artifacts not loaded",
                        "message": "Call load_artifacts first to get risk ranges",
                        "artifact_dir": self.artifact_dir or "not set",
                    }
                    return self._format_response(error_response)
                
                return self._format_response(self._scorer.risk_ranges)

        return rows.select(result=_risk_ranges(pw.this.sentinel))

    # ------------------------------------------------------------------
    # Admin Tools for Dashboard/Frontend Control
    # ------------------------------------------------------------------
    def _tool_get_admin_settings(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _get_settings(_sentinel: int) -> str:
            with track_tool_invocation("risk.get_admin_settings"):
                return self._format_response({
                    "use_offline_centroids": self._use_offline_centroids,
                    "allow_online_updates": self._allow_online_updates,
                    "artifact_dir": self.artifact_dir,
                    "original_artifact_dir": self._original_artifact_dir,
                    "model_loaded": self._scorer is not None,
                    "online_update_count": self._scorer.update_cnt if self._scorer else 0,
                    "drift_status": "stable" if self._use_offline_centroids else "may_drift",
                })
        return rows.select(result=_get_settings(pw.this.sentinel))

    def _tool_update_admin_settings(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _update_settings(use_offline: bool, allow_updates: bool) -> str:
                meta = {
                    "use_offline_centroids": bool(use_offline),
                    "allow_online_updates": bool(allow_updates),
                }
                with track_tool_invocation("risk.update_admin_settings", metadata=meta):
                    old_offline = self._use_offline_centroids
                    self._use_offline_centroids = bool(use_offline)
                    self._allow_online_updates = bool(allow_updates)
                
                    # Reload model if offline centroids setting changed
                    reload_needed = old_offline != self._use_offline_centroids
                    if reload_needed and self.artifact_dir:
                        logger.info("Reloading model with use_offline_centroids=%s", self._use_offline_centroids)
                        self._load_artifacts(self.artifact_dir, use_offline_centroids=self._use_offline_centroids)
                
                    return self._format_response({
                        "status": "ok",
                        "use_offline_centroids": self._use_offline_centroids,
                        "allow_online_updates": self._allow_online_updates,
                        "model_reloaded": reload_needed,
                        "message": "Settings updated successfully" + (" (model reloaded)" if reload_needed else ""),
                    })
        return rows.select(result=_update_settings(pw.this.use_offline_centroids, pw.this.allow_online_updates))

    def _tool_reload_model(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _reload(reset_to_original: bool) -> str:
            meta = {"reset_to_original": bool(reset_to_original)}
            with track_tool_invocation("risk.reload_model", metadata=meta):
                if not self._original_artifact_dir:
                    return self._format_response({
                        "status": "error",
                        "message": "No original artifact directory configured",
                    })
                
                # Reset settings if requested
                if reset_to_original:
                    self._use_offline_centroids = True
                    self._allow_online_updates = True
                
                # Reload from original artifacts
                logger.info("Reloading model from %s (reset=%s)", self._original_artifact_dir, reset_to_original)
                self._load_artifacts(self._original_artifact_dir, use_offline_centroids=self._use_offline_centroids)
                
                # Clear drift history on reset
                if reset_to_original:
                    self._drift_history = []
                    self._prediction_history = []
                
                return self._format_response({
                    "status": "ok",
                    "message": "Model reloaded to original state" if reset_to_original else "Model reloaded with current settings",
                    "artifact_dir": self.artifact_dir,
                    "use_offline_centroids": self._use_offline_centroids,
                    "allow_online_updates": self._allow_online_updates,
                    "online_update_count": self._scorer.update_cnt,
                })
        return rows.select(result=_reload(pw.this.reset_to_original))

    # ------------------------------------------------------------------
    # Drift Tracking and Visualization Tools
    # ------------------------------------------------------------------
    
    def _record_drift_snapshot(self) -> None:
        """Record current drift metrics for history."""
        import time
        import numpy as np
        
        if self._scorer is None or self._original_centroids is None:
            return
        
        # Calculate centroid drift from original
        current_centroids = self._get_current_centroids()
        if current_centroids is None:
            return
        
        centroid_drifts = []
        for i, (orig, curr) in enumerate(zip(self._original_centroids, current_centroids)):
            drift = float(np.linalg.norm(np.array(curr) - np.array(orig)))
            centroid_drifts.append(drift)
        
        # Calculate prediction distribution from recent predictions
        recent = self._prediction_history[-100:] if self._prediction_history else []
        cluster_counts = {0: 0, 1: 0, 2: 0}
        scores = []
        recon_errors = []
        
        for p in recent:
            cid = p.get("cluster_id")
            if cid in cluster_counts:
                cluster_counts[cid] += 1
            if p.get("risk_score") is not None:
                scores.append(p["risk_score"])
            if p.get("reconstruction_error") is not None:
                recon_errors.append(p["reconstruction_error"])
        
        snapshot = {
            "timestamp": time.time(),
            "update_count": self._scorer.update_cnt,
            "centroid_drifts": centroid_drifts,
            "total_drift": sum(centroid_drifts),
            "avg_drift": sum(centroid_drifts) / len(centroid_drifts) if centroid_drifts else 0,
            "cluster_distribution": cluster_counts,
            "avg_score": sum(scores) / len(scores) if scores else None,
            "avg_recon_error": sum(recon_errors) / len(recon_errors) if recon_errors else None,
            "predictions_tracked": len(recent),
        }
        
        self._drift_history.append(snapshot)
        
        # Keep last 500 snapshots
        if len(self._drift_history) > 500:
            self._drift_history = self._drift_history[-500:]
    
    def _get_current_centroids(self):
        """Get current centroids from scorer."""
        import numpy as np
        
        if self._scorer is None:
            return None
        
        # If using offline centroids, they don't drift
        if self._use_offline_centroids and self._scorer.offline_centroids is not None:
            return self._scorer.offline_centroids.tolist()
        
        # Get from River KMeans
        if hasattr(self._scorer, 'kmeans') and hasattr(self._scorer.kmeans, 'centers'):
            centers = self._scorer.kmeans.centers
            if centers:
                latent_dim = self._cluster_context.get("latent_dim", 4)
                centroids = []
                for cid in sorted(centers.keys()):
                    center = centers[cid]
                    centroid = [center.get(f"f{i}", 0.0) for i in range(latent_dim)]
                    centroids.append(centroid)
                return centroids
        
        return None
    
    def _tool_get_drift_metrics(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _get_metrics(_sentinel: int) -> str:
            import numpy as np
            
            with track_tool_invocation("risk.get_drift_metrics"):
                if self._scorer is None:
                    error_response = {
                        "error": "Artifacts not loaded",
                        "message": "Call load_artifacts first to get drift metrics",
                        "artifact_dir": self.artifact_dir or "not set",
                    }
                    return self._format_response(error_response)
                
                # Use the scorer's built-in drift calculation
                scorer_drift = self._scorer.get_centroid_drift()
                
                # Legacy: also calculate from stored original centroids
                current_centroids = self._get_current_centroids()
                centroid_drift = []
                if self._original_centroids is not None and current_centroids is not None:
                    for i, (orig, curr) in enumerate(zip(self._original_centroids, current_centroids)):
                        drift = float(np.linalg.norm(np.array(curr) - np.array(orig)))
                        label = (self._cluster_context or {}).get("cluster_to_label", {}).get(i, f"Cluster {i}")
                        centroid_drift.append({
                            "cluster_id": i,
                            "cluster_label": label,
                            "drift_distance": drift,
                            "drift_level": "none" if drift < 0.01 else "low" if drift < 0.1 else "medium" if drift < 0.5 else "high",
                        })
                
                # Recent prediction stats
                recent = self._prediction_history[-100:] if self._prediction_history else []
                drift_alerts = sum(1 for p in recent if p.get("drift_detected"))
                
                return self._format_response({
                    "using_offline_centroids": self._use_offline_centroids,
                    "online_updates_enabled": self._allow_online_updates,
                    "total_updates": self._scorer.update_cnt,
                    "total_predictions_tracked": len(self._prediction_history),
                    "centroid_drift": centroid_drift,
                    "scorer_drift_metrics": scorer_drift,  # New: detailed from scorer
                    "total_centroid_drift": sum(c["drift_distance"] for c in centroid_drift),
                    "drift_alerts_recent": drift_alerts,
                    "drift_alert_rate": drift_alerts / len(recent) if recent else 0,
                    "health": "stable" if self._use_offline_centroids else (
                        "drifting" if any(c["drift_level"] in ["medium", "high"] for c in centroid_drift) else "ok"
                    ),
                })
        
        return rows.select(result=_get_metrics(pw.this.sentinel))
    
    def _tool_get_drift_history(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _get_history(limit: int) -> str:
            # Return drift history for graphing
            history = self._drift_history[-limit:] if self._drift_history else []
            
            # Format for frontend charting
            chart_data = {
                "timestamps": [h["timestamp"] for h in history],
                "total_drift": [h["total_drift"] for h in history],
                "avg_drift": [h["avg_drift"] for h in history],
                "update_counts": [h["update_count"] for h in history],
                "avg_scores": [h["avg_score"] for h in history],
                "avg_recon_errors": [h["avg_recon_error"] for h in history],
                "cluster_distributions": [h["cluster_distribution"] for h in history],
                "per_cluster_drift": {
                    f"cluster_{i}": [h["centroid_drifts"][i] if i < len(h["centroid_drifts"]) else 0 for h in history]
                    for i in range(3)
                },
            }
            
            with track_tool_invocation("risk.get_drift_history", metadata={"limit": limit}):
                return self._format_response({
                    "history_length": len(history),
                    "chart_data": chart_data,
                    "raw_history": history,
                })
        
        return rows.select(result=_get_history(pw.this.limit))
    
    def _tool_get_prediction_distribution(self, rows: pw.Table) -> pw.Table:
        @pw.udf
        def _get_distribution(limit: int) -> str:
            import numpy as np
            
            recent = self._prediction_history[-limit:] if self._prediction_history else []
            
            if not recent:
                return self._format_response({
                    "message": "No predictions tracked yet",
                    "predictions_count": 0,
                })
            
            # Cluster distribution
            cluster_counts = {}
            label_counts = {}
            scores = []
            distances = []
            recon_errors = []
            
            for p in recent:
                cid = p.get("cluster_id")
                label = p.get("risk_label")
                
                cluster_counts[cid] = cluster_counts.get(cid, 0) + 1
                label_counts[label] = label_counts.get(label, 0) + 1
                
                if p.get("risk_score") is not None:
                    scores.append(p["risk_score"])
                if p.get("distance") is not None:
                    distances.append(p["distance"])
                if p.get("reconstruction_error") is not None:
                    recon_errors.append(p["reconstruction_error"])
            
            # Score histogram buckets
            score_buckets = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
            for s in scores:
                if s < 20: score_buckets["0-20"] += 1
                elif s < 40: score_buckets["20-40"] += 1
                elif s < 60: score_buckets["40-60"] += 1
                elif s < 80: score_buckets["60-80"] += 1
                else: score_buckets["80-100"] += 1
            
                with track_tool_invocation("risk.get_prediction_distribution"):
                    return self._format_response({
                "predictions_count": len(recent),
                "cluster_distribution": cluster_counts,
                "label_distribution": label_counts,
                "score_histogram": score_buckets,
                "score_stats": {
                    "min": min(scores) if scores else None,
                    "max": max(scores) if scores else None,
                    "mean": float(np.mean(scores)) if scores else None,
                    "std": float(np.std(scores)) if scores else None,
                },
                "distance_stats": {
                    "min": min(distances) if distances else None,
                    "max": max(distances) if distances else None,
                    "mean": float(np.mean(distances)) if distances else None,
                },
                "reconstruction_error_stats": {
                    "min": min(recon_errors) if recon_errors else None,
                    "max": max(recon_errors) if recon_errors else None,
                    "mean": float(np.mean(recon_errors)) if recon_errors else None,
                },
            })
        
        return rows.select(result=_get_distribution(pw.this.limit))


# ------------------------------------------------------------------
# CLI wiring
# ------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the investor risk scorer via Pathway MCP server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--artifact-dir",
        type=str,
        default=None,
        help="Optional artifact directory to eagerly load on startup",
    )
    parser.add_argument(
        "--transport",
        choices=["streamable-http", "stdio"],
        default="streamable-http",
        help="Transport the MCP server should expose",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for streamable-http transport",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8123,
        help="Port for streamable-http transport",
    )
    parser.add_argument(
        "--server-name",
        type=str,
        default="investor-risk-scorer-mcp",
        help="Logical MCP server name (also used by clients)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    servable = InvestorRiskScorerServable(artifact_dir=args.artifact_dir)
    host = args.host if args.transport == "streamable-http" else None
    port = args.port if args.transport == "streamable-http" else None

    # Instantiating PathwayMcp registers the servable and spins up the FastMCP layer.
    PathwayMcp(
        name=args.server_name,
        transport=args.transport, 
        host=host,
        port=port,
        serve=[servable],
    )

    logger.info(
        "Starting Pathway MCP server '%s' using transport=%s", args.server_name, args.transport
    )
    if servable.artifact_dir:
        logger.info("Artifacts pre-loaded from %s", servable.artifact_dir)
    else:
        logger.info("Artifacts will be loaded on demand via load_artifacts tool")

    pw.run(monitoring_level=pw.MonitoringLevel.NONE, terminate_on_error=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as exc:  # pragma: no cover - defensive logging for CLI entrypoint
        logger.error("Server error: %s", exc, exc_info=True)
        sys.exit(1)
