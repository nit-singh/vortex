"""
FinRAG Orchestrator - LLM-driven tool selection and execution.

This module provides an intelligent agent layer that:
1. Analyzes user queries using an LLM
2. Decides which tool(s) to call and with what parameters
3. Executes tools and synthesizes responses
"""

from .orchestrator import FinRAGOrchestrator, OrchestratorConfig
from .tools import ToolRegistry, Tool, ToolResult

__all__ = [
    "FinRAGOrchestrator",
    "OrchestratorConfig", 
    "ToolRegistry",
    "Tool",
    "ToolResult"
]
