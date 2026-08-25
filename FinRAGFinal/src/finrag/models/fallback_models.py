"""Fallback models used when an OpenAI API key is not available."""
from typing import List, Dict, Any
import logging
import numpy as np
import warnings

from ..core.base_models import BaseEmbeddingModel, BaseSummarizationModel, BaseQAModel


logger = logging.getLogger(__name__)


class SentenceTransformerEmbeddingModel(BaseEmbeddingModel):
    """Free embedding model using sentence-transformers."""
    
    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        """
        Initialize with a free sentence-transformer model.
        Default: all-MiniLM-L6-v2 (lightweight, good quality, 384 dimensions)
        """
        self.model_name = model
        self.model = None
        logger.info("Using fallback embedding model: %s", model)
    
    def _ensure_model_loaded(self):
        """Lazy load the model on first use."""
        if self.model is None:
            try:
                logger.info("Loading sentence-transformer model '%s'", self.model_name)
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(self.model_name)
                logger.debug("Sentence-transformer model loaded")
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for fallback embeddings. "
                    "Install with: pip install sentence-transformers"
                )
    
    def create_embedding(self, text: str) -> np.ndarray:
        """Create embedding for given text."""
        self._ensure_model_loaded()
        
        if not text or not text.strip():
            raise ValueError("Cannot create embedding for empty text")
        
        try:
            embedding = self.model.encode(text.strip(), convert_to_numpy=True)
            return embedding
        except Exception as e:
            logger.exception("Failed to create fallback embedding")
            raise
    
    def create_embeddings(self, texts: List[str]) -> np.ndarray:
        """Create embeddings for multiple texts."""
        self._ensure_model_loaded()
        
        valid_texts = [text.strip() for text in texts if text and text.strip()]
        
        if not valid_texts:
            raise ValueError("Cannot create embeddings for empty text list")
        
        if len(valid_texts) != len(texts):
            logger.warning("Filtered out %d empty texts", len(texts) - len(valid_texts))
        
        try:
            embeddings = self.model.encode(valid_texts, convert_to_numpy=True)
            return embeddings
        except Exception as e:
            logger.exception("Failed to create fallback embeddings")
            raise


class FlanT5SummarizationModel(BaseSummarizationModel):
    """FLAN-T5-small summarization model (free, open-source)."""
    
    def __init__(self, model_name: str = "google/flan-t5-small"):
        """
        Initialize with FLAN-T5-small model.
        This is a free, open-source model that provides actual AI summarization.
        """
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        logger.info("Using fallback summarization model: %s", model_name)
    
    def _ensure_model_loaded(self):
        """Lazy load the model on first use."""
        if self.model is None:
            try:
                logger.info("Loading FLAN-T5 model '%s'", self.model_name)
                from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
                
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
                logger.debug("FLAN-T5 model loaded")
            except ImportError:
                raise ImportError(
                    "transformers is required for FLAN-T5 models. "
                    "Install with: pip install transformers torch"
                )
    
    def summarize(self, texts: List[str], max_tokens: int = 200) -> str:
        """
        Summarize using FLAN-T5 model.
        This provides actual AI summarization with understanding.
        """
        self._ensure_model_loaded()
        
        combined_text = "\n\n".join(texts)
        
        # Truncate if too long (FLAN-T5-small has 512 token limit)
        if len(combined_text) > 2000:
            combined_text = combined_text[:2000]
        
        # Create summarization prompt
        prompt = f"Summarize the following financial text concisely:\n\n{combined_text}"
        
        try:
            # Tokenize
            inputs = self.tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True)
            
            # Generate summary
            outputs = self.model.generate(
                inputs.input_ids,
                max_length=max_tokens,
                min_length=30,
                length_penalty=2.0,
                num_beams=4,
                early_stopping=True
            )
            
            # Decode
            summary = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            return summary
            
        except Exception as e:
            logger.exception("FLAN-T5 summarization failed")
            # Fallback to simple extraction
            sentences = combined_text.split('.')[:3]
            return ". ".join(s.strip() for s in sentences if s.strip()) + "."


class FlanT5QAModel(BaseQAModel):
    """FLAN-T5-small QA model (free, open-source)."""
    
    def __init__(self, model_name: str = "google/flan-t5-small"):
        """
        Initialize with FLAN-T5-small model.
        This is a free, open-source model that provides actual AI question answering.
        """
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        logger.info("Using fallback QA model: %s", model_name)
    
    def _ensure_model_loaded(self):
        """Lazy load the model on first use."""
        if self.model is None:
            try:
                logger.info("Loading FLAN-T5 model '%s'", self.model_name)
                from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
                
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
                logger.debug("FLAN-T5 model loaded")
            except ImportError:
                raise ImportError(
                    "transformers is required for FLAN-T5 models. "
                    "Install with: pip install transformers torch"
                )
    
    def answer_question(self, context: str, question: str) -> Dict[str, Any]:
        """
        Answer question using FLAN-T5 model.
        This provides actual AI reasoning with understanding.
        """
        self._ensure_model_loaded()
        
        if not context or not context.strip():
            return {
                "answer": "No context provided.",
                "confidence": 0.0
            }
        
        # Truncate context if too long (FLAN-T5-small has 512 token limit)
        if len(context) > 2000:
            context = context[:2000]
        
        # Create QA prompt
        prompt = f"Answer the question based on the context.\n\nContext: {context}\n\nQuestion: {question}\n\nAnswer:"
        
        try:
            # Tokenize
            inputs = self.tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True)
            
            # Generate answer
            outputs = self.model.generate(
                inputs.input_ids,
                max_length=150,
                min_length=10,
                length_penalty=1.0,
                num_beams=4,
                early_stopping=True,
                temperature=0.7
            )
            
            # Decode
            answer = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            
            # Estimate confidence based on answer length and content
            confidence = 0.6 if len(answer) > 10 else 0.3
            
            return {
                "answer": answer,
                "confidence": confidence
            }
            
        except Exception as e:
            logger.exception("FLAN-T5 QA failed")
            # Fallback to simple extraction
            sentences = context.split('.')[:3]
            answer = ". ".join(s.strip() for s in sentences if s.strip()) + "."
            return {
                "answer": answer,
                "confidence": 0.2
            }


def check_openai_key_valid(api_key: str) -> bool:
    """Check if OpenAI API key is valid by making a test call."""
    if not api_key or not api_key.strip():
        return False
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        # Try a minimal request
        client.models.list()
        return True
    except Exception as e:
        logger.warning("OpenAI API key validation failed: %s", str(e)[:100])
        return False
