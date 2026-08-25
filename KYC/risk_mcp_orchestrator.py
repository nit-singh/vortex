"""Utility orchestrator for exercising the Pathway MCP risk scorer tools.

The script wraps the MCP client workflow so that you can:

    1. Load exported investor risk artifacts via the `load_artifacts` tool.
    2. Fetch server status, cluster context, or risk range metadata.
    3. Run online or offline scoring against a user profile JSON payload.

Example:
    python risk_mcp_orchestrator.py \
        --mcp-url http://localhost:8123/mcp/ \
        --artifact-dir ./risk_artifacts \
        --user-file sample_user.json \
        --run-offline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from fastmcp import Client
except ImportError as exc:  # pragma: no cover - convenience guard for missing dependency
    raise SystemExit(
        "The fastmcp package is required. Install it with `pip install fastmcp`."
    ) from exc


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class RiskScorerOrchestrator:
    """Async context manager that wraps the FastMCP client for convenience."""

    def __init__(self, mcp_url: str):
        self._client = Client(mcp_url)

    async def __aenter__(self) -> "RiskScorerOrchestrator":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401 - signature mandated by context API
        await self._client.__aexit__(exc_type, exc, tb)

    async def load_artifacts(self, artifact_dir: str, use_offline_centroids: bool = True) -> Any:
        payload = {
            "artifact_dir": artifact_dir,
            "use_offline_centroids": use_offline_centroids,
        }
        return await self._client.call_tool(name="load_artifacts", arguments=payload)

    async def score_online(self, user: Dict[str, Any], update: bool = False) -> Any:
        payload = {"user": user, "update": update}
        return await self._client.call_tool(name="score_online", arguments=payload)

    async def score_offline(self, user: Dict[str, Any]) -> Any:
        payload = {"user": user}
        return await self._client.call_tool(name="score_offline", arguments=payload)

    async def get_status(self) -> Any:
        return await self._client.call_tool(name="get_status", arguments={})

    async def get_cluster_context(self) -> Any:
        return await self._client.call_tool(name="get_cluster_context", arguments={})

    async def get_risk_ranges(self) -> Any:
        return await self._client.call_tool(name="get_risk_ranges", arguments={})

    async def list_tools(self) -> Any:
        return await self._client.list_tools()


def _load_user_profile(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    """Load a user dict either from JSON file or inline string."""

    if args.user_file:
        user_path = Path(args.user_file)
        if not user_path.is_file():
            raise FileNotFoundError(f"User profile file not found: {user_path}")
        return json.loads(user_path.read_text())

    if args.user_json:
        return json.loads(args.user_json)

    return None


def _maybe_parse_response(response: Any) -> Any:
    """Best-effort conversion of MCP tool responses into Python objects."""

    if isinstance(response, str):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return response

    if isinstance(response, list) and len(response) == 1:
        return _maybe_parse_response(response[0])

    if isinstance(response, dict):
        if "result" in response and len(response) == 1:
            return _maybe_parse_response(response["result"])
        if "content" in response:
            return _maybe_parse_response(response["content"])

    return response


def _print_banner(title: str) -> None:
    logger.info("%s", title)


async def orchestrate(args: argparse.Namespace) -> None:
    user_profile = _load_user_profile(args)

    async with RiskScorerOrchestrator(args.mcp_url) as orchestrator:
        tools = await orchestrator.list_tools()
        logger.info("Available MCP tools: %s", tools)

        if args.artifact_dir:
            artifact_dir = str(Path(args.artifact_dir).expanduser().resolve())
            _print_banner("Loading artifacts")
            load_resp = await orchestrator.load_artifacts(
                artifact_dir,
                use_offline_centroids=not args.disable_offline_centroids,
            )
            logger.info(
                "load_artifacts(%s) -> %s",
                artifact_dir,
                _maybe_parse_response(load_resp),
            )

        _print_banner("Server status")
        status = await orchestrator.get_status()
        logger.info("get_status -> %s", _maybe_parse_response(status))

        if args.show_cluster_context:
            _print_banner("Cluster context")
            context = await orchestrator.get_cluster_context()
            logger.info("get_cluster_context -> %s", _maybe_parse_response(context))

        if args.show_risk_ranges:
            _print_banner("Risk ranges")
            ranges = await orchestrator.get_risk_ranges()
            logger.info("get_risk_ranges -> %s", _maybe_parse_response(ranges))

        if user_profile:
            _print_banner("Online risk scoring")
            online = await orchestrator.score_online(
                user_profile,
                update=args.update_online_model,
            )
            logger.info("score_online -> %s", _maybe_parse_response(online))

            if args.run_offline:
                _print_banner("Offline risk scoring")
                offline = await orchestrator.score_offline(user_profile)
                logger.info("score_offline -> %s", _maybe_parse_response(offline))
        else:
            logger.info("No user profile provided; skipping scoring calls")


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Orchestrate Pathway MCP investor risk tools",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mcp-url",
        default="http://127.0.0.1:8123/mcp/",
        help="Base MCP endpoint exposed by the Pathway server",
    )
    parser.add_argument(
        "--artifact-dir",
        help="Optional artifact directory to load via the load_artifacts tool",
    )
    parser.add_argument(
        "--disable-offline-centroids",
        action="store_true",
        help="Disable use_offline_centroids flag when loading artifacts",
    )
    parser.add_argument(
        "--user-file",
        help="Path to a JSON file containing a user profile for scoring",
    )
    parser.add_argument(
        "--user-json",
        help="Inline JSON string representing a user profile",
    )
    parser.add_argument(
        "--update-online-model",
        action="store_true",
        help="Allow the online scorer to update centroids while scoring",
    )
    parser.add_argument(
        "--run-offline",
        action="store_true",
        help="Run the offline scorer (sklearn centroids) after the online call",
    )
    parser.add_argument(
        "--show-cluster-context",
        action="store_true",
        help="Fetch cluster labels via the get_cluster_context tool",
    )
    parser.add_argument(
        "--show-risk-ranges",
        action="store_true",
        help="Fetch label-to-score ranges via the get_risk_ranges tool",
    )
    return parser


def main() -> None:
    parser = _build_cli()
    args = parser.parse_args()
    if args.user_file and args.user_json:
        parser.error("Pass either --user-file or --user-json, not both.")

    asyncio.run(orchestrate(args))


if __name__ == "__main__":
    main()
