"""
FinRAG Evaluation Module - RAGAS Integration

Provides tools for evaluating RAG quality using:
- Retrieval metrics: Context Recall, Context Precision
- Generation metrics: Faithfulness, Answer Correctness

Based on Pathway's RAGAS evaluation approach.
"""

from .ragas_evaluator import (
    RAGASEvaluator,
    EvaluationResult,
    EvaluationConfig
)
from .dataset import (
    EvalDataset,
    EvalSample,
    create_synthetic_dataset,
    load_eval_dataset,
    save_eval_dataset,
    create_finrag_eval_dataset,
    create_manual_dataset,
    TestsetGenerator
)

__all__ = [
    "RAGASEvaluator",
    "EvaluationResult", 
    "EvaluationConfig",
    "EvalDataset",
    "EvalSample",
    "create_synthetic_dataset",
    "load_eval_dataset",
    "save_eval_dataset",
    "create_finrag_eval_dataset",
    "create_manual_dataset",
    "TestsetGenerator"
]
