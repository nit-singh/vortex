"""
Base models for FinRAG components following RAPTOR's extensible design.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
import numpy as np


class BaseEmbeddingModel(ABC):
    """Base class for embedding models."""
    
    @abstractmethod
    def create_embedding(self, text: str) -> np.ndarray:
        """Create embedding for given text."""
        pass
    
    @abstractmethod
    def create_embeddings(self, texts: List[str]) -> np.ndarray:
        """Create embeddings for multiple texts."""
        pass


class BaseSummarizationModel(ABC):
    """Base class for summarization models."""
    
    @abstractmethod
    def summarize(self, texts: List[str], max_tokens: int = 200) -> str:
        """Summarize a list of text chunks."""
        pass


class BaseQAModel(ABC):
    """Base class for QA models."""
    
    @abstractmethod
    def answer_question(self, context: str, question: str) -> Dict[str, Any]:
        """Answer a question given context."""
        pass


class BaseChunker(ABC):
    """Base class for text chunking."""
    
    @abstractmethod
    def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """Chunk text into smaller pieces."""
        pass
