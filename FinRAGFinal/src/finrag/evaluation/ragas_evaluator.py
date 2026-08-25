"""RAGAS Evaluator for FinRAG."""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


@dataclass
class EvaluationConfig:
    """Configuration for RAGAS evaluation."""
    
    evaluator_model: str = "gpt-4o-mini"
    temperature: float = 0.0
    correctness_weights: tuple = (1.0, 0.0)
    correctness_beta: float = 1.5
    
    metrics: List[str] = field(default_factory=lambda: [
        "faithfulness",
        "answer_correctness", 
        "context_recall",
        "context_precision"
    ])
    
    max_workers: int = 4
    max_retries: int = 3
    retry_delay: float = 1.0


@dataclass
class EvaluationResult:
    """Results from RAGAS evaluation."""
    
    faithfulness: Optional[float] = None
    answer_correctness: Optional[float] = None
    context_recall: Optional[float] = None
    context_precision: Optional[float] = None
    
    sample_scores: List[Dict[str, float]] = field(default_factory=list)
    num_samples: int = 0
    evaluation_time: float = 0.0
    config: Optional[EvaluationConfig] = None
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "overall_scores": {
                "faithfulness": self.faithfulness,
                "answer_correctness": self.answer_correctness,
                "context_recall": self.context_recall,
                "context_precision": self.context_precision
            },
            "num_samples": self.num_samples,
            "evaluation_time": self.evaluation_time,
            "errors": self.errors
        }
    
    def summary(self) -> str:
        """Get formatted summary string."""
        lines = [
            "=" * 60,
            "RAGAS EVALUATION RESULTS",
            "=" * 60,
            f"Samples evaluated: {self.num_samples}",
            f"Evaluation time: {self.evaluation_time:.2f}s",
            "",
            "SCORES:",
            "-" * 40
        ]
        
        if self.faithfulness is not None:
            lines.append(f"  Faithfulness:       {self.faithfulness:.4f}")
        if self.answer_correctness is not None:
            lines.append(f"  Answer Correctness: {self.answer_correctness:.4f}")
        if self.context_recall is not None:
            lines.append(f"  Context Recall:     {self.context_recall:.4f}")
        if self.context_precision is not None:
            lines.append(f"  Context Precision:  {self.context_precision:.4f}")
        
        if self.errors:
            lines.extend([
                "",
                f"Errors: {len(self.errors)}",
                "-" * 40
            ])
            for err in self.errors[:5]:  # Show first 5 errors
                lines.append(f"  - {err[:100]}")
        
        lines.append("=" * 60)
        return "\n".join(lines)


class RAGASEvaluator:
    """
    RAGAS-based evaluator for FinRAG.
    
    Usage:
        evaluator = RAGASEvaluator(config)
        results = evaluator.evaluate(dataset, predict_fn)
    """
    
    def __init__(self, config: Optional[EvaluationConfig] = None):
        """Initialize evaluator with configuration."""
        self.config = config or EvaluationConfig()
        self._ragas_available = self._check_ragas()
        self._metrics = None
        self._evaluator_llm = None
    
    def _check_ragas(self) -> bool:
        """Check if RAGAS is available."""
        try:
            import ragas
            return True
        except ImportError:
            logger.warning("RAGAS not installed. Install with: pip install ragas")
            return False
    
    def _setup_metrics(self):
        """Initialize RAGAS metrics."""
        if not self._ragas_available:
            raise RuntimeError("RAGAS not available. Install with: pip install ragas")
        
        if self._metrics is not None:
            return  # Already set up
        
        try:
            from ragas.metrics import (
                Faithfulness,
                AnswerCorrectness,
                ContextRecall,
                ContextPrecision
            )
            from ragas.llms import LangchainLLMWrapper
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            raise ImportError(f"Missing dependencies: {e}. Install with: pip install ragas langchain-openai")
        
        # Create evaluator LLM
        self._evaluator_llm = LangchainLLMWrapper(
            ChatOpenAI(
                model=self.config.evaluator_model,
                temperature=self.config.temperature
            )
        )
        
        # Initialize metrics
        self._metrics = {}
        
        if "faithfulness" in self.config.metrics:
            self._metrics["faithfulness"] = Faithfulness(llm=self._evaluator_llm)
        
        if "answer_correctness" in self.config.metrics:
            correctness = AnswerCorrectness(
                llm=self._evaluator_llm,
                weights=self.config.correctness_weights,
                beta=self.config.correctness_beta
            )
            # Optionally modify the prompt for more tolerant evaluation
            self._metrics["answer_correctness"] = correctness
        
        if "context_recall" in self.config.metrics:
            self._metrics["context_recall"] = ContextRecall(llm=self._evaluator_llm)
        
        if "context_precision" in self.config.metrics:
            self._metrics["context_precision"] = ContextPrecision(llm=self._evaluator_llm)
        
        logger.info(f"Initialized RAGAS metrics: {list(self._metrics.keys())}")
    
    def evaluate(
        self,
        dataset: "EvalDataset",
        predict_fn: Callable[[str], Dict[str, Any]],
        show_progress: bool = True
    ) -> EvaluationResult:
        """
        Evaluate a dataset using RAGAS metrics.
        
        Args:
            dataset: EvalDataset with questions and ground truths
            predict_fn: Function that takes a question and returns:
                        {"answer": str, "contexts": List[str]}
            show_progress: Whether to show progress
            
        Returns:
            EvaluationResult with scores
        """
        start_time = time.time()
        
        if not self._ragas_available:
            return self._evaluate_fallback(dataset, predict_fn, start_time)
        
        self._setup_metrics()
        
        # Step 1: Generate predictions for all samples
        logger.info(f"Generating predictions for {len(dataset)} samples...")
        predictions = []
        errors = []
        
        for i, sample in enumerate(dataset):
            if show_progress and (i + 1) % 5 == 0:
                logger.info(f"  Predicted {i + 1}/{len(dataset)}")
            
            try:
                result = predict_fn(sample.question)
                predictions.append({
                    "question": sample.question,
                    "ground_truth": sample.ground_truth,
                    "answer": result.get("answer", ""),
                    "contexts": result.get("contexts", [])
                })
                
                # Update sample with prediction
                sample.predicted_answer = result.get("answer", "")
                sample.retrieved_contexts = result.get("contexts", [])
                
            except Exception as e:
                logger.error(f"Error predicting sample {i}: {e}")
                errors.append(f"Prediction error for '{sample.question[:50]}...': {str(e)}")
                predictions.append(None)
        
        # Filter out failed predictions
        valid_predictions = [p for p in predictions if p is not None]
        
        if not valid_predictions:
            return EvaluationResult(
                num_samples=0,
                evaluation_time=time.time() - start_time,
                errors=errors
            )
        
        # Step 2: Run RAGAS evaluation
        logger.info(f"Running RAGAS evaluation on {len(valid_predictions)} samples...")
        
        try:
            from ragas import evaluate
            from ragas.dataset_schema import SingleTurnSample, EvaluationDataset as RagasDataset
            
            # Convert to RAGAS format
            ragas_samples = []
            for pred in valid_predictions:
                ragas_samples.append(SingleTurnSample(
                    user_input=pred["question"],
                    response=pred["answer"],
                    reference=pred["ground_truth"],
                    retrieved_contexts=pred["contexts"]
                ))
            
            ragas_dataset = RagasDataset(samples=ragas_samples)
            
            # Run evaluation
            ragas_result = evaluate(
                dataset=ragas_dataset,
                metrics=list(self._metrics.values())
            )
            
            # Extract results
            result = EvaluationResult(
                num_samples=len(valid_predictions),
                evaluation_time=time.time() - start_time,
                config=self.config,
                errors=errors
            )
            
            # Get overall scores
            scores_df = ragas_result.to_pandas()
            
            if "faithfulness" in scores_df.columns:
                result.faithfulness = float(scores_df["faithfulness"].mean())
            if "answer_correctness" in scores_df.columns:
                result.answer_correctness = float(scores_df["answer_correctness"].mean())
            if "context_recall" in scores_df.columns:
                result.context_recall = float(scores_df["context_recall"].mean())
            if "context_precision" in scores_df.columns:
                result.context_precision = float(scores_df["context_precision"].mean())
            
            # Store per-sample scores
            for i, row in scores_df.iterrows():
                sample_scores = {}
                for metric in self.config.metrics:
                    if metric in row:
                        sample_scores[metric] = float(row[metric])
                result.sample_scores.append(sample_scores)
                
                # Update dataset samples with scores
                if i < len(dataset.samples):
                    dataset.samples[i].scores = sample_scores
            
            return result
            
        except Exception as e:
            logger.error(f"RAGAS evaluation failed: {e}", exc_info=True)
            errors.append(f"RAGAS evaluation error: {str(e)}")
            
            return EvaluationResult(
                num_samples=len(valid_predictions),
                evaluation_time=time.time() - start_time,
                config=self.config,
                errors=errors
            )
    
    def _evaluate_fallback(
        self,
        dataset: "EvalDataset",
        predict_fn: Callable[[str], Dict[str, Any]],
        start_time: float
    ) -> EvaluationResult:
        """Fallback evaluation without RAGAS using simple heuristics."""
        logger.warning("Using fallback evaluation (RAGAS not available)")
        
        from difflib import SequenceMatcher
        
        predictions = []
        errors = []
        
        for i, sample in enumerate(dataset):
            try:
                result = predict_fn(sample.question)
                answer = result.get("answer", "")
                contexts = result.get("contexts", [])
                
                # Simple similarity score as proxy for correctness
                similarity = SequenceMatcher(
                    None,
                    sample.ground_truth.lower(),
                    answer.lower()
                ).ratio()
                
                # Simple context check
                context_score = 1.0 if contexts else 0.0
                
                predictions.append({
                    "similarity": similarity,
                    "context_score": context_score
                })
                
                sample.predicted_answer = answer
                sample.retrieved_contexts = contexts
                sample.scores = {
                    "answer_similarity": similarity,
                    "has_context": context_score
                }
                
            except Exception as e:
                errors.append(f"Error: {str(e)}")
        
        avg_similarity = sum(p["similarity"] for p in predictions) / len(predictions) if predictions else 0
        avg_context = sum(p["context_score"] for p in predictions) / len(predictions) if predictions else 0
        
        return EvaluationResult(
            answer_correctness=avg_similarity,
            context_recall=avg_context,
            num_samples=len(predictions),
            evaluation_time=time.time() - start_time,
            errors=errors + ["Note: Using fallback evaluation, install RAGAS for full metrics"]
        )
    
    def evaluate_single(
        self,
        question: str,
        ground_truth: str,
        answer: str,
        contexts: List[str]
    ) -> Dict[str, float]:
        """
        Evaluate a single question-answer pair.
        
        Args:
            question: The question asked
            ground_truth: Expected correct answer
            answer: Generated answer to evaluate
            contexts: Retrieved contexts used for answering
            
        Returns:
            Dictionary of metric scores
        """
        if not self._ragas_available:
            from difflib import SequenceMatcher
            similarity = SequenceMatcher(None, ground_truth.lower(), answer.lower()).ratio()
            return {"answer_similarity": similarity, "has_context": 1.0 if contexts else 0.0}
        
        self._setup_metrics()
        
        try:
            from ragas import evaluate
            from ragas.dataset_schema import SingleTurnSample, EvaluationDataset as RagasDataset
            
            sample = SingleTurnSample(
                user_input=question,
                response=answer,
                reference=ground_truth,
                retrieved_contexts=contexts
            )
            
            ragas_dataset = RagasDataset(samples=[sample])
            
            ragas_result = evaluate(
                dataset=ragas_dataset,
                metrics=list(self._metrics.values())
            )
            
            scores_df = ragas_result.to_pandas()
            scores = {}
            
            for metric in self.config.metrics:
                if metric in scores_df.columns:
                    scores[metric] = float(scores_df[metric].iloc[0])
            
            return scores
            
        except Exception as e:
            logger.error(f"Single evaluation failed: {e}")
            return {"error": str(e)}


def quick_evaluate(
    questions: List[str],
    ground_truths: List[str],
    predict_fn: Callable[[str], Dict[str, Any]],
    model: str = "gpt-4o-mini"
) -> EvaluationResult:
    """
    Quick evaluation helper for simple use cases.
    
    Args:
        questions: List of questions
        ground_truths: List of expected answers
        predict_fn: Function that takes question and returns {"answer": str, "contexts": List[str]}
        model: Evaluator model
        
    Returns:
        EvaluationResult
    """
    from .dataset import EvalDataset, EvalSample
    
    samples = [
        EvalSample(question=q, ground_truth=gt)
        for q, gt in zip(questions, ground_truths)
    ]
    
    dataset = EvalDataset(name="quick_eval", samples=samples)
    
    config = EvaluationConfig(evaluator_model=model)
    evaluator = RAGASEvaluator(config)
    
    return evaluator.evaluate(dataset, predict_fn)
