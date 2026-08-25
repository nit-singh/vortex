"""
Evaluation Dataset Management for FinRAG

Provides tools for:
- Creating and managing evaluation datasets
- Loading/saving datasets in JSONL format
- Generating synthetic datasets from documents using RAGAS
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class EvalSample:
    """A single evaluation sample with question, ground truth, and optional predictions."""
    
    # Input
    question: str
    ground_truth: str
    
    # Optional metadata
    source_document: Optional[str] = None
    category: Optional[str] = None  # e.g., "financial_metrics", "portfolio", "comparison"
    difficulty: Optional[str] = None  # e.g., "easy", "medium", "hard"
    
    # Predictions (filled during evaluation)
    predicted_answer: Optional[str] = None
    retrieved_contexts: List[str] = field(default_factory=list)
    
    # Scores (filled after evaluation)
    scores: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvalSample":
        """Create from dictionary."""
        return cls(
            question=data["question"],
            ground_truth=data["ground_truth"],
            source_document=data.get("source_document"),
            category=data.get("category"),
            difficulty=data.get("difficulty"),
            predicted_answer=data.get("predicted_answer"),
            retrieved_contexts=data.get("retrieved_contexts", []),
            scores=data.get("scores", {})
        )


@dataclass
class EvalDataset:
    """Collection of evaluation samples."""
    
    name: str
    samples: List[EvalSample]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __len__(self) -> int:
        return len(self.samples)
    
    def __iter__(self):
        return iter(self.samples)
    
    def __getitem__(self, idx: int) -> EvalSample:
        return self.samples[idx]
    
    def add_sample(self, sample: EvalSample):
        """Add a sample to the dataset."""
        self.samples.append(sample)
    
    def get_by_category(self, category: str) -> List[EvalSample]:
        """Get samples by category."""
        return [s for s in self.samples if s.category == category]
    
    def get_categories(self) -> List[str]:
        """Get unique categories."""
        return list(set(s.category for s in self.samples if s.category))
    
    def summary(self) -> Dict[str, Any]:
        """Get dataset summary statistics."""
        categories = {}
        for sample in self.samples:
            cat = sample.category or "uncategorized"
            categories[cat] = categories.get(cat, 0) + 1
        
        scored_samples = [s for s in self.samples if s.scores]
        avg_scores = {}
        if scored_samples:
            all_metrics = set()
            for s in scored_samples:
                all_metrics.update(s.scores.keys())
            
            for metric in all_metrics:
                values = [s.scores[metric] for s in scored_samples if metric in s.scores]
                if values:
                    avg_scores[metric] = sum(values) / len(values)
        
        return {
            "name": self.name,
            "total_samples": len(self.samples),
            "categories": categories,
            "samples_with_predictions": len([s for s in self.samples if s.predicted_answer]),
            "samples_with_scores": len(scored_samples),
            "average_scores": avg_scores
        }


def save_eval_dataset(dataset: EvalDataset, path: str) -> None:
    """Save evaluation dataset to JSONL file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        # Write metadata as first line
        metadata = {
            "_metadata": True,
            "name": dataset.name,
            **dataset.metadata
        }
        f.write(json.dumps(metadata) + '\n')
        
        # Write samples
        for sample in dataset.samples:
            f.write(json.dumps(sample.to_dict()) + '\n')
    
    logger.info(f"Saved {len(dataset)} samples to {path}")


def load_eval_dataset(path: str) -> EvalDataset:
    """Load evaluation dataset from JSONL file."""
    path = Path(path)
    
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    
    samples = []
    metadata = {}
    name = path.stem
    
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line.strip())
            
            if data.get("_metadata"):
                name = data.get("name", name)
                metadata = {k: v for k, v in data.items() if k not in ["_metadata", "name"]}
            else:
                samples.append(EvalSample.from_dict(data))
    
    logger.info(f"Loaded {len(samples)} samples from {path}")
    return EvalDataset(name=name, samples=samples, metadata=metadata)


def create_synthetic_dataset(
    documents_dir: str,
    output_path: str,
    num_samples: int = 20,
    model: str = "gpt-4o-mini",
    categories: Optional[List[str]] = None
) -> EvalDataset:
    """
    Generate a synthetic evaluation dataset from documents using RAGAS.
    
    Args:
        documents_dir: Directory containing documents to generate questions from
        output_path: Path to save the generated dataset
        num_samples: Number of samples to generate
        model: OpenAI model for generation
        categories: Optional list of categories to focus on
        
    Returns:
        Generated EvalDataset
    """
    try:
        from ragas.testset import TestsetGenerator
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from langchain_community.document_loaders import DirectoryLoader, TextLoader
    except ImportError as e:
        logger.error(f"Missing dependencies for synthetic dataset generation: {e}")
        logger.error("Install with: pip install ragas langchain-openai langchain-community")
        raise
    
    import os
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY environment variable required for synthetic dataset generation")
    
    logger.info(f"Generating synthetic dataset from {documents_dir}")
    
    # Load documents
    loader = DirectoryLoader(
        documents_dir,
        glob="**/*.md",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"}
    )
    docs = loader.load()
    
    if not docs:
        # Try loading text files
        loader = DirectoryLoader(
            documents_dir,
            glob="**/*.txt",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"}
        )
        docs = loader.load()
    
    if not docs:
        raise ValueError(f"No documents found in {documents_dir}")
    
    logger.info(f"Loaded {len(docs)} documents")
    
    # Configure RAGAS generator
    # Use a different model for generation to reduce bias
    generator_llm = LangchainLLMWrapper(
        ChatOpenAI(model=model, temperature=0.3)
    )
    generator_embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings()
    )
    
    generator = TestsetGenerator(
        llm=generator_llm,
        embedding_model=generator_embeddings
    )
    
    # Generate testset
    logger.info(f"Generating {num_samples} synthetic samples...")
    ragas_dataset = generator.generate_with_langchain_docs(
        docs,
        testset_size=num_samples
    )
    
    # Convert to our format
    samples = []
    for item in ragas_dataset:
        sample = EvalSample(
            question=item.user_input,
            ground_truth=item.reference,
            source_document=item.reference_contexts[0] if item.reference_contexts else None,
            category=_infer_category(item.user_input) if categories is None else None
        )
        samples.append(sample)
    
    dataset = EvalDataset(
        name=Path(output_path).stem,
        samples=samples,
        metadata={
            "generated_with": "ragas",
            "model": model,
            "source_dir": documents_dir,
            "num_source_docs": len(docs)
        }
    )
    
    # Save
    save_eval_dataset(dataset, output_path)
    
    logger.info(f"Generated {len(samples)} synthetic samples")
    return dataset


def _infer_category(question: str) -> str:
    """Infer category from question text."""
    question_lower = question.lower()
    
    if any(word in question_lower for word in ["revenue", "profit", "margin", "earnings", "eps", "ebitda"]):
        return "financial_metrics"
    elif any(word in question_lower for word in ["portfolio", "allocation", "holdings", "invested"]):
        return "portfolio"
    elif any(word in question_lower for word in ["compare", "versus", "vs", "difference", "better"]):
        return "comparison"
    elif any(word in question_lower for word in ["risk", "volatility", "beta", "drawdown"]):
        return "risk_analysis"
    elif any(word in question_lower for word in ["growth", "trend", "forecast", "future"]):
        return "growth_outlook"
    else:
        return "general"


def create_manual_dataset(
    name: str,
    questions_and_answers: List[Dict[str, str]],
    output_path: Optional[str] = None
) -> EvalDataset:
    """
    Create a manual evaluation dataset from a list of Q&A pairs.
    
    Args:
        name: Dataset name
        questions_and_answers: List of dicts with 'question', 'answer', and optional 'category'
        output_path: Optional path to save the dataset
        
    Returns:
        EvalDataset
    """
    samples = []
    for qa in questions_and_answers:
        sample = EvalSample(
            question=qa["question"],
            ground_truth=qa["answer"],
            category=qa.get("category"),
            difficulty=qa.get("difficulty")
        )
        samples.append(sample)
    
    dataset = EvalDataset(name=name, samples=samples)
    
    if output_path:
        save_eval_dataset(dataset, output_path)
    
    return dataset


# Pre-built financial evaluation questions for FinRAG
FINRAG_EVAL_QUESTIONS = [
    {
        "question": "What is the total revenue of Infosys for FY2024-25?",
        "answer": "Infosys reported revenue of ₹1,62,990 crore for fiscal year 2024-25.",
        "category": "financial_metrics"
    },
    {
        "question": "What is the profit margin of TCS?",
        "answer": "TCS has a profit margin of approximately 19%.",
        "category": "financial_metrics"
    },
    {
        "question": "Which companies are in my portfolio?",
        "answer": "Your portfolio contains TCS, Infosys, HDFC Bank, Reliance, and other stocks based on your portfolio configuration.",
        "category": "portfolio"
    },
    {
        "question": "What is the free cash flow of Infosys?",
        "answer": "Infosys generated free cash flow of ₹34,549 crore for fiscal 2025.",
        "category": "financial_metrics"
    },
    {
        "question": "Compare the revenue growth of TCS and Infosys.",
        "answer": "Both TCS and Infosys showed single-digit revenue growth. Infosys had 6.1% YoY revenue growth.",
        "category": "comparison"
    },
    {
        "question": "What is the dividend yield of HDFC Bank?",
        "answer": "HDFC Bank offers a dividend yield that varies based on current market price and dividend payouts.",
        "category": "financial_metrics"
    },
    {
        "question": "What is the allocation of Infosys in my portfolio?",
        "answer": "Infosys constitutes 12% of your portfolio with an allocation of ₹1,200,000.",
        "category": "portfolio"
    },
    {
        "question": "What are the key risk factors for Reliance Industries?",
        "answer": "Key risk factors include oil price volatility, regulatory changes, and competition in telecom and retail sectors.",
        "category": "risk_analysis"
    },
    {
        "question": "What is the market capitalization of Infosys?",
        "answer": "Infosys has a market capitalization of approximately ₹6.5 lakh crore.",
        "category": "financial_metrics"
    },
    {
        "question": "What is the return on equity (ROE) of Infosys?",
        "answer": "Infosys has an ROE of approximately 29%.",
        "category": "financial_metrics"
    }
]


def create_finrag_eval_dataset(output_path: Optional[str] = None) -> EvalDataset:
    """Create a default evaluation dataset for FinRAG testing."""
    return create_manual_dataset(
        name="finrag_eval",
        questions_and_answers=FINRAG_EVAL_QUESTIONS,
        output_path=output_path
    )


class TestsetGenerator:
    """
    Generate synthetic evaluation datasets from parsed documents.
    
    Wrapper around RAGAS TestsetGenerator that works with FinRAG's
    parsed document format (pickle files from cache/parsed_docs).
    """
    
    def __init__(self, model: str = "gpt-4o-mini"):
        """
        Initialize the testset generator.
        
        Args:
            model: OpenAI model for question/answer generation
        """
        self.model = model
        
    def generate_from_parsed_docs(
        self,
        doc_paths: List[str],
        size: int = 10,
        output_path: Optional[str] = None
    ) -> EvalDataset:
        """
        Generate synthetic Q&A pairs from parsed documents.
        
        Args:
            doc_paths: List of paths to parsed document pickle files
            size: Number of Q&A samples to generate
            output_path: Optional path to save the dataset
            
        Returns:
            EvalDataset with generated samples
        """
        import pickle
        import os
        
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY required for testset generation")
        
        try:
            from langchain_openai import ChatOpenAI, OpenAIEmbeddings
            from langchain.schema import Document
        except ImportError as e:
            logger.error(f"Missing langchain dependencies: {e}")
            logger.error("Install with: pip install langchain-openai langchain")
            raise
        
        # Load documents from pickle or text files
        logger.info(f"Loading {len(doc_paths)} parsed documents...")
        documents = []
        
        for doc_path in doc_paths:
            try:
                # Handle text files
                if doc_path.endswith('.txt'):
                    with open(doc_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    if len(text.strip()) > 100:
                        # Split into chunks of ~2000 chars for better Q&A generation
                        chunk_size = 2000
                        for i in range(0, len(text), chunk_size):
                            chunk_text = text[i:i + chunk_size]
                            if len(chunk_text.strip()) > 100:
                                doc = Document(
                                    page_content=chunk_text,
                                    metadata={'source': Path(doc_path).name}
                                )
                                documents.append(doc)
                    continue
                
                # Handle pickle files
                with open(doc_path, 'rb') as f:
                    parsed = pickle.load(f)
                
                # Extract text chunks from parsed documents
                if isinstance(parsed, dict):
                    chunks = parsed.get('chunks', [])
                    if not chunks and 'text' in parsed:
                        # Single text document
                        chunks = [{'text': parsed['text'], 'metadata': parsed.get('metadata', {})}]
                    
                    for chunk in chunks:
                        if isinstance(chunk, dict) and 'text' in chunk:
                            text = chunk['text']
                            if len(text.strip()) > 100:  # Skip very short chunks
                                doc = Document(
                                    page_content=text,
                                    metadata=chunk.get('metadata', {'source': doc_path})
                                )
                                documents.append(doc)
                elif isinstance(parsed, str):
                    if len(parsed.strip()) > 100:
                        documents.append(Document(
                            page_content=parsed,
                            metadata={'source': doc_path}
                        ))
            except Exception as e:
                logger.warning(f"Failed to load {doc_path}: {e}")
                continue
        
        if not documents:
            raise ValueError("No valid documents found in parsed files")
        
        logger.info(f"Loaded {len(documents)} document chunks")
        
        # Try to use RAGAS TestsetGenerator if available
        try:
            from ragas.testset import TestsetGenerator as RagasTestsetGenerator
            from ragas.llms import LangchainLLMWrapper
            from ragas.embeddings import LangchainEmbeddingsWrapper
            
            logger.info("Using RAGAS TestsetGenerator...")
            
            generator_llm = LangchainLLMWrapper(
                ChatOpenAI(model=self.model, temperature=0.3)
            )
            generator_embeddings = LangchainEmbeddingsWrapper(
                OpenAIEmbeddings(model="text-embedding-3-small")
            )
            
            generator = RagasTestsetGenerator(
                llm=generator_llm,
                embedding_model=generator_embeddings
            )
            
            ragas_dataset = generator.generate_with_langchain_docs(
                documents[:50],  # Limit docs to avoid token limits
                testset_size=size
            )
            
            # Convert to our format - handle different RAGAS versions
            samples = []
            for i, item in enumerate(ragas_dataset):
                # Debug: log available attributes for first item
                if i == 0:
                    logger.info(f"TestsetSample attributes: {dir(item)}")
                    logger.info(f"TestsetSample dict: {item.__dict__ if hasattr(item, '__dict__') else 'no __dict__'}")
                
                # RAGAS returns TestsetSample with eval_sample (SingleTurnSample) inside
                eval_sample = getattr(item, 'eval_sample', None)
                
                if eval_sample is not None:
                    # Extract from SingleTurnSample object
                    question = getattr(eval_sample, 'user_input', None)
                    ground_truth = getattr(eval_sample, 'reference', None)
                    contexts = getattr(eval_sample, 'reference_contexts', None) or []
                else:
                    # Fallback for older RAGAS versions
                    question = getattr(item, 'question', None) or getattr(item, 'user_input', None)
                    ground_truth = getattr(item, 'answer', None) or getattr(item, 'reference', None)
                    contexts = getattr(item, 'contexts', None) or getattr(item, 'reference_contexts', None) or []
                
                source_doc = contexts[0] if contexts else None
                
                if question:  # Only add if we got a question
                    sample = EvalSample(
                        question=str(question),
                        ground_truth=str(ground_truth) if ground_truth else "",
                        source_document=str(source_doc)[:500] if source_doc else None,
                        category=_infer_category(str(question))
                    )
                    samples.append(sample)
            
            logger.info(f"Generated {len(samples)} samples from RAGAS")
                
        except ImportError:
            logger.warning("RAGAS not available, using simple LLM-based generation...")
            samples = self._generate_with_llm(documents, size)
        except Exception as e:
            logger.warning(f"RAGAS generation failed: {e}, falling back to LLM generation...")
            samples = self._generate_with_llm(documents, size)
        
        # Ensure we have at least some samples
        if not samples:
            logger.warning("No samples generated, creating fallback samples...")
            samples = self._generate_with_llm(documents, min(size, 5))
        
        dataset = EvalDataset(
            name="synthetic_testset",
            samples=samples,
            metadata={
                "generated_with": "TestsetGenerator",
                "model": self.model,
                "num_source_docs": len(doc_paths),
                "num_chunks": len(documents)
            }
        )
        
        if output_path:
            save_eval_dataset(dataset, output_path)
            
        return dataset
    
    def _generate_with_llm(self, documents: List, size: int) -> List[EvalSample]:
        """
        Fallback: Generate Q&A pairs using direct LLM calls.
        """
        from langchain_openai import ChatOpenAI
        import random
        
        llm = ChatOpenAI(model=self.model, temperature=0.7)
        samples = []
        
        # Sample random documents
        sampled_docs = random.sample(documents, min(size * 2, len(documents)))
        
        for doc in sampled_docs[:size]:
            try:
                # Generate question
                q_prompt = f"""Based on the following text, generate ONE specific factual question that can be answered using this text.

Text:
{doc.page_content[:2000]}

Generate only the question, nothing else:"""
                
                question = llm.invoke(q_prompt).content.strip()
                
                # Generate answer
                a_prompt = f"""Based on the following text, answer this question concisely.

Text:
{doc.page_content[:2000]}

Question: {question}

Answer:"""
                
                answer = llm.invoke(a_prompt).content.strip()
                
                sample = EvalSample(
                    question=question,
                    ground_truth=answer,
                    source_document=doc.page_content[:500],
                    category=_infer_category(question)
                )
                samples.append(sample)
                
            except Exception as e:
                logger.warning(f"Failed to generate Q&A: {e}")
                continue
        
        return samples
