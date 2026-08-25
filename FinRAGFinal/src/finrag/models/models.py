"""OpenAI model implementations."""
from typing import List, Dict, Any
import logging
import numpy as np
from openai import OpenAI
import tiktoken
from tenacity import retry, stop_after_attempt, wait_exponential
import re

from ..core.base_models import BaseEmbeddingModel, BaseSummarizationModel, BaseQAModel, BaseChunker


logger = logging.getLogger(__name__)


class OpenAIEmbeddingModel(BaseEmbeddingModel):
    """OpenAI embedding model."""
    
    def __init__(self, model: str = "text-embedding-3-small", api_key: str = None):
        self.model = model
        self.client = OpenAI(api_key=api_key)
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def create_embedding(self, text: str) -> np.ndarray:
        """Create embedding for given text."""
        if not text or not text.strip():
            raise ValueError("Cannot create embedding for empty text")
        
        try:
            response = self.client.embeddings.create(
                input=text.strip(),
                model=self.model
            )
            return np.array(response.data[0].embedding)
        except Exception as e:
            logger.exception(
                "Failed to create embedding (length=%d, preview=%s)",
                len(text),
                text[:100],
            )
            raise
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def create_embeddings(self, texts: List[str]) -> np.ndarray:
        """Create embeddings for multiple texts."""
        # Filter out empty texts and strip whitespace
        valid_texts = [text.strip() for text in texts if text and text.strip()]
        
        if not valid_texts:
            raise ValueError("Cannot create embeddings for empty text list")
        
        if len(valid_texts) != len(texts):
            logger.warning("Filtered out %d empty texts", len(texts) - len(valid_texts))
        
        try:
            response = self.client.embeddings.create(
                input=valid_texts,
                model=self.model
            )
            embeddings = [np.array(item.embedding) for item in response.data]
            return np.array(embeddings)
        except Exception as e:
            logger.exception(
                "Failed to create embeddings for %d texts", len(valid_texts)
            )
            raise


class OpenAISummarizationModel(BaseSummarizationModel):
    """OpenAI summarization model."""
    
    def __init__(self, model: str = "gpt-4o-mini", api_key: str = None):
        self.model = model
        self.client = OpenAI(api_key=api_key)
        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def summarize(self, texts: List[str], max_tokens: int = 200) -> str:
        """Summarize a list of text chunks with financial context awareness."""
        combined_text = "\n\n".join(texts)
        
        # Check token count and split if necessary
        prompt_template = """You are a financial document summarization expert. 
Summarize the following financial text chunks, preserving key financial information such as:
- Monetary amounts and percentages
- Dates and time periods
- Company names and entities
- Financial metrics and KPIs
- Important trends or changes

Text to summarize:
{text}

Provide a concise summary in {tokens} tokens or less."""
        
        # Reserve tokens for system message and response
        # gpt-4o-mini has 128K context window
        max_context = 120000  # Safe limit for gpt-4o-mini (128K tokens)
        prompt_overhead = self.count_tokens(prompt_template.format(text="", tokens=max_tokens))
        available_tokens = max_context - prompt_overhead - max_tokens - 100  # 100 token safety buffer
        
        text_tokens = self.count_tokens(combined_text)
        
        if text_tokens > available_tokens:
            logger.warning(f"Cluster too large ({text_tokens} tokens), splitting into chunks")
            # Split texts into smaller batches
            summaries = []
            current_batch = []
            current_tokens = 0
            
            for text in texts:
                text_token_count = self.count_tokens(text)
                if current_tokens + text_token_count > available_tokens:
                    # Summarize current batch
                    if current_batch:
                        batch_text = "\n\n".join(current_batch)
                        prompt = prompt_template.format(text=batch_text, tokens=max_tokens)
                        response = self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": "You are a financial document summarization expert."},
                                {"role": "user", "content": prompt}
                            ],
                            max_tokens=max_tokens,
                            temperature=0.3
                        )
                        summaries.append(response.choices[0].message.content)
                    current_batch = [text]
                    current_tokens = text_token_count
                else:
                    current_batch.append(text)
                    current_tokens += text_token_count
            
            # Summarize last batch
            if current_batch:
                batch_text = "\n\n".join(current_batch)
                prompt = prompt_template.format(text=batch_text, tokens=max_tokens)
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a financial document summarization expert."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=max_tokens,
                    temperature=0.3
                )
                summaries.append(response.choices[0].message.content)
            
            # If multiple summaries, combine them
            if len(summaries) > 1:
                logger.info(f"Created {len(summaries)} sub-summaries, combining...")
                combined_text = "\n\n".join(summaries)
        
        # Final summarization
        prompt = prompt_template.format(text=combined_text, tokens=max_tokens)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a financial document summarization expert."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            temperature=0.3
        )
        
        return response.choices[0].message.content


class OpenAIQAModel(BaseQAModel):
    """OpenAI QA model."""
    
    def __init__(self, model: str = "gpt-4o-mini", api_key: str = None):
        self.model = model
        self.client = OpenAI(api_key=api_key)
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def answer_question(self, context: str, question: str) -> Dict[str, Any]:
        """Answer a financial question given context."""
        system_prompt = """You are a precise financial analyst assistant. Your task is to answer questions using ONLY the information provided in the context. 

Critical Rules:
- ONLY use information explicitly stated in the context
- NEVER add external knowledge or make assumptions
- If the context doesn't contain the answer, respond with "Based on the provided context, I cannot find information to answer this question."
- Quote specific numbers, dates, and facts directly from the context
- Keep answers focused and factual"""

        prompt = f"""Based STRICTLY on the context below, answer the question. Use only facts from the context.

### CONTEXT ###
{context}

### QUESTION ###
{question}

### INSTRUCTIONS ###
1. Answer using ONLY information from the context above
2. Quote exact figures, percentages, and dates when available
3. If the context lacks sufficient information, clearly state this
4. Be concise and factual - avoid speculation

### ANSWER ###"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500
        )
        
        answer = response.choices[0].message.content
        
        return {
            "answer": answer,
            "context": context,
            "question": question
        }


class FinancialChunker(BaseChunker):
    """Financial document chunker."""
    
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50, model: str = "gpt-4"):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoding = tiktoken.encoding_for_model(model)
    
    def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """Chunk text into smaller pieces."""
        # Tokenize text
        tokens = self.encoding.encode(text)
        chunks = []
        
        # Validate chunk overlap
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(f"chunk_overlap ({self.chunk_overlap}) must be less than chunk_size ({self.chunk_size})")
        
        start = 0
        chunk_id = 0
        
        while start < len(tokens):
            end = min(start + self.chunk_size, len(tokens))
            chunk_tokens = tokens[start:end]
            chunk_text = self.encoding.decode(chunk_tokens)
            
            # Try to break at sentence boundaries
            if end < len(tokens):
                # Look for sentence endings
                for offset in range(min(50, end - start)):
                    if chunk_text[-(offset+1):].strip().endswith(('.', '!', '?', '\n')):
                        chunk_text = chunk_text[:-(offset)]
                        break
            
            chunks.append({
                "text": chunk_text.strip(),
                "chunk_id": chunk_id,
                "start_token": start,
                "end_token": end
            })
            
            chunk_id += 1
            # Ensure we always move forward to prevent infinite loop
            start = max(end - self.chunk_overlap, start + 1)
            
            # Safety check: prevent infinite loop if something goes wrong
            if start >= len(tokens):
                break
        
        return chunks
    
    
    def extract_metadata(self, text: str, chunk_text: str = None) -> Dict[str, Any]:
        """Extract financial metadata (sector, company, year)."""
        if chunk_text is None:
            chunk_text = text
        
        metadata = {
            "sector": None,
            "company": None,
            "year": None
        }
        
        # Extract year - look for 4-digit years (1900-2099)
        year_pattern = r'\b(19\d{2}|20\d{2})\b'
        years = re.findall(year_pattern, text[:2000])  # Check first 2000 chars
        if years:
            # Most common year or most recent
            metadata["year"] = max(set(years), key=years.count)
        
        # Extract company - look for common patterns
        # Pattern 1: "Company Name Inc.", "Company Name Corp", etc.
        company_patterns = [
            r'\b([A-Z][a-zA-Z\s&]+(?:Inc|Corp|Corporation|Ltd|Limited|LLC|Company|Co)\.?)\b',
            r'\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+){1,3})\s+(?:Inc|Corp|Corporation|Ltd|Limited|LLC)',
        ]
        
        for pattern in company_patterns:
            companies = re.findall(pattern, text[:1000])
            if companies:
                # Take the most common or first occurrence
                metadata["company"] = companies[0] if isinstance(companies[0], str) else companies[0][0]
                break
        
        # Extract sector - look for common financial sectors
        sectors = {
            "technology": ["technology", "software", "tech", "IT", "digital", "cloud"],
            "finance": ["financial", "bank", "insurance", "investment", "securities"],
            "healthcare": ["healthcare", "pharmaceutical", "medical", "biotech", "health"],
            "energy": ["energy", "oil", "gas", "renewable", "utilities"],
            "retail": ["retail", "consumer", "e-commerce", "commerce"],
            "manufacturing": ["manufacturing", "industrial", "automotive", "production"],
            "real estate": ["real estate", "property", "REIT"],
            "telecommunications": ["telecommunications", "telecom", "communications"]
        }
        
        text_lower = text[:5000].lower()  # Check first 5000 chars
        sector_scores = {}
        
        for sector_name, keywords in sectors.items():
            score = sum(text_lower.count(keyword) for keyword in keywords)
            if score > 0:
                sector_scores[sector_name] = score
        
        if sector_scores:
            metadata["sector"] = max(sector_scores, key=sector_scores.get)
        
        return metadata
    
    def chunk_text_with_metadata(
        self,
        text: str,
        extract_metadata: bool = True
    ) -> List[Dict[str, Any]]:
        """Chunk text with metadata extraction."""
        chunks = self.chunk_text(text)
        
        if extract_metadata:
            # Extract document-level metadata once
            doc_metadata = self.extract_metadata(text)
            
            # Add to all chunks
            for chunk in chunks:
                chunk.update(doc_metadata)
        
        return chunks
