"""
FinRAG: Financial Retrieval-Augmented Generation System
Based on RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval)
"""

from .finrag import FinRAG
from .config import FinRAGConfig
from .scoring import EnsembleScorer, ScoringConfig, ScoringResult
from .vectorstore import PathwayVectorStore, PathwayConfig
from .observability import (
    trace_query,
    trace_document_parsing,
    langfuse_context,
    flush_langfuse
)

# Lazy import for evaluation (optional dependency)
def get_evaluator():
    """Get RAGASEvaluator (lazy import)."""
    from .evaluation import RAGASEvaluator, EvaluationConfig
    return RAGASEvaluator, EvaluationConfig

__version__ = "1.0.0"
__all__ = [
    "FinRAG",
    "FinRAGConfig",
    "EnsembleScorer",
    "ScoringConfig",
    "ScoringResult",
    "PathwayVectorStore",
    "PathwayConfig",
    "trace_query",
    "trace_document_parsing",
    "langfuse_context",
    "flush_langfuse",
    "get_evaluator"
]
