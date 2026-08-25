"""
FinRAG Observability Module - Langfuse Integration

This module provides comprehensive tracing for:
1. User query against portfolio (chat/query flow)
2. Single document parsing

Usage:
    from finrag.observability import langfuse_context, trace_query, trace_document_parsing
"""

from .langfuse_integration import (
    LangfuseObservability,
    langfuse_context,
    trace_query,
    trace_document_parsing,
    trace_llm_call,
    get_langfuse,
    flush_langfuse
)

__all__ = [
    "LangfuseObservability",
    "langfuse_context",
    "trace_query",
    "trace_document_parsing",
    "trace_llm_call",
    "get_langfuse",
    "flush_langfuse"
]
