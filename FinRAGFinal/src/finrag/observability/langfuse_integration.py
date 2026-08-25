"""
Langfuse Integration for FinRAG Observability

Provides comprehensive tracing for:
1. User queries against portfolio (end-to-end chat/query flow)
2. Single document parsing (PDF load -> chunk -> embed flow)

Configuration:
    Set the following environment variables:
    - LANGFUSE_PUBLIC_KEY: Your Langfuse public key
    - LANGFUSE_SECRET_KEY: Your Langfuse secret key
    - LANGFUSE_HOST: (Optional) Self-hosted Langfuse URL, defaults to cloud

Usage:
    # For queries
    with trace_query(question="What is TCS revenue?", user_id="user123") as trace:
        trace.span("routing", input={"question": question})
        # ... do work
        trace.generation("llm_answer", model="gpt-4o-mini", input=prompt, output=answer)
    
    # For document parsing
    with trace_document_parsing(file_path="/path/to/doc.pdf") as trace:
        trace.span("pdf_extraction")
        trace.span("chunking", metadata={"chunk_count": 50})
        trace.span("embedding", metadata={"token_count": 5000})
"""

import os
import time
import logging
import functools
from typing import Optional, Dict, Any, List, Callable, Union
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# Try to import langfuse, gracefully handle if not installed
try:
    from langfuse import Langfuse
    from langfuse.decorators import observe, langfuse_context as lf_context
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    logger.warning(
        "Langfuse not installed. Install with: pip install langfuse. "
        "Observability features will be disabled."
    )


@dataclass
class UsageMetrics:
    """Token usage metrics for LLM calls."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "cost_usd": self.cost_usd
        }


@dataclass 
class SpanData:
    """Data for a span within a trace."""
    name: str
    start_time: float
    end_time: Optional[float] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    level: str = "DEFAULT"  # DEBUG, DEFAULT, WARNING, ERROR
    status_message: Optional[str] = None


@dataclass
class GenerationData:
    """Data for an LLM generation within a trace."""
    name: str
    model: str
    start_time: float
    end_time: Optional[float] = None
    input: Optional[Union[str, Dict, List]] = None
    output: Optional[str] = None
    usage: Optional[UsageMetrics] = None
    metadata: Optional[Dict[str, Any]] = None
    level: str = "DEFAULT"


class LangfuseObservability:
    """Langfuse observability singleton."""
    
    _instance: Optional["LangfuseObservability"] = None
    _langfuse: Optional["Langfuse"] = None
    
    # Cost per 1K tokens for common models (USD)
    MODEL_COSTS = {
        # OpenAI
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "text-embedding-3-small": {"input": 0.00002, "output": 0.0},
        "text-embedding-3-large": {"input": 0.00013, "output": 0.0},
        "text-embedding-ada-002": {"input": 0.0001, "output": 0.0},
        # Anthropic
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
    }
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self._enabled = False
        
        if not LANGFUSE_AVAILABLE:
            logger.info("Langfuse not available, observability disabled")
            return
        
        # Check for required environment variables
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        
        if not public_key or not secret_key:
            logger.info(
                "Langfuse keys not configured. Set LANGFUSE_PUBLIC_KEY and "
                "LANGFUSE_SECRET_KEY environment variables to enable tracing."
            )
            return
        
        try:
            self._langfuse = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host
            )
            self._enabled = True
            logger.info(f"Langfuse observability initialized (host: {host})")
        except Exception as e:
            logger.error(f"Failed to initialize Langfuse: {e}")
            self._langfuse = None
    
    @property
    def enabled(self) -> bool:
        return self._enabled and self._langfuse is not None
    
    @property
    def client(self) -> Optional["Langfuse"]:
        return self._langfuse
    
    def calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost in USD for a model call."""
        costs = self.MODEL_COSTS.get(model, {"input": 0.0, "output": 0.0})
        input_cost = (prompt_tokens / 1000) * costs["input"]
        output_cost = (completion_tokens / 1000) * costs["output"]
        return round(input_cost + output_cost, 6)
    
    def flush(self):
        """Flush any pending traces to Langfuse."""
        if self._langfuse:
            self._langfuse.flush()
    
    def shutdown(self):
        """Shutdown the Langfuse client."""
        if self._langfuse:
            self._langfuse.shutdown()


class TraceContext:
    """Context manager for Langfuse trace."""
    
    def __init__(
        self,
        name: str,
        trace_type: str,  # "query" or "document_parsing"
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None
    ):
        self.name = name
        self.trace_type = trace_type
        self.metadata = metadata or {}
        self.user_id = user_id
        self.session_id = session_id
        self.tags = tags or []
        
        self._obs = LangfuseObservability()
        self._trace = None
        self._current_span = None
        self._spans: List[SpanData] = []
        self._generations: List[GenerationData] = []
        self._start_time = None
        self._trace_id = str(uuid.uuid4())
        
        # Aggregate usage metrics
        self.total_usage = UsageMetrics()
    
    def __enter__(self) -> "TraceContext":
        self._start_time = time.time()
        
        if self._obs.enabled:
            # Create Langfuse trace
            self._trace = self._obs.client.trace(
                name=self.name,
                user_id=self.user_id,
                session_id=self.session_id,
                metadata={
                    **self.metadata,
                    "trace_type": self.trace_type,
                    "project": "FinRAG"
                },
                tags=["finrag", self.trace_type] + self.tags
            )
            self._trace_id = self._trace.id
            logger.debug(f"Started Langfuse trace: {self._trace_id}")
        else:
            logger.debug(f"Started local trace (Langfuse disabled): {self._trace_id}")
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        end_time = time.time()
        duration = end_time - self._start_time
        
        # Finalize trace
        if self._obs.enabled and self._trace:
            # Add final metadata with aggregated usage
            self._trace.update(
                output={
                    "duration_seconds": round(duration, 3),
                    "total_usage": self.total_usage.to_dict(),
                    "span_count": len(self._spans),
                    "generation_count": len(self._generations),
                    "success": exc_type is None
                },
                metadata={
                    **self.metadata,
                    "total_tokens": self.total_usage.total_tokens,
                    "total_cost_usd": self.total_usage.cost_usd
                }
            )
            
            if exc_type:
                self._trace.update(
                    level="ERROR",
                    status_message=str(exc_val)
                )
        
        logger.debug(
            f"Trace {self._trace_id} completed in {duration:.3f}s "
            f"(tokens: {self.total_usage.total_tokens}, cost: ${self.total_usage.cost_usd:.4f})"
        )
        
        return False  # Don't suppress exceptions
    
    @contextmanager
    def span(
        self,
        name: str,
        input: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        level: str = "DEFAULT"
    ):
        """
        Create a span within the trace.
        
        Args:
            name: Span name (e.g., "routing", "retrieval", "chunking")
            input: Input data for the span
            metadata: Additional metadata
            level: Log level (DEBUG, DEFAULT, WARNING, ERROR)
        
        Yields:
            The span object (Langfuse span or None if disabled)
        """
        start_time = time.time()
        span = None
        
        if self._obs.enabled and self._trace:
            span = self._trace.span(
                name=name,
                input=input,
                metadata=metadata,
                level=level
            )
        
        span_data = SpanData(
            name=name,
            start_time=start_time,
            input=input,
            metadata=metadata,
            level=level
        )
        
        try:
            yield span
        except Exception as e:
            span_data.level = "ERROR"
            span_data.status_message = str(e)
            if span:
                span.update(level="ERROR", status_message=str(e))
            raise
        finally:
            end_time = time.time()
            span_data.end_time = end_time
            self._spans.append(span_data)
            
            if span:
                span.end()
            
            logger.debug(f"Span '{name}' completed in {end_time - start_time:.3f}s")
    
    def generation(
        self,
        name: str,
        model: str,
        input: Union[str, Dict, List],
        output: Optional[str] = None,
        usage: Optional[Dict[str, int]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        level: str = "DEFAULT"
    ):
        """
        Record an LLM generation.
        
        Args:
            name: Generation name (e.g., "routing_llm", "answer_generation")
            model: Model name (e.g., "gpt-4o-mini")
            input: Input prompt/messages
            output: Generated output
            usage: Token usage dict with keys: prompt_tokens, completion_tokens, total_tokens
            metadata: Additional metadata
            level: Log level
        """
        start_time = time.time()
        
        # Calculate usage metrics
        usage_metrics = UsageMetrics(model=model)
        if usage:
            usage_metrics.prompt_tokens = usage.get("prompt_tokens", 0)
            usage_metrics.completion_tokens = usage.get("completion_tokens", 0)
            usage_metrics.total_tokens = usage.get("total_tokens", 
                usage_metrics.prompt_tokens + usage_metrics.completion_tokens)
            usage_metrics.cost_usd = self._obs.calculate_cost(
                model,
                usage_metrics.prompt_tokens,
                usage_metrics.completion_tokens
            )
            
            # Update aggregate usage
            self.total_usage.prompt_tokens += usage_metrics.prompt_tokens
            self.total_usage.completion_tokens += usage_metrics.completion_tokens
            self.total_usage.total_tokens += usage_metrics.total_tokens
            self.total_usage.cost_usd += usage_metrics.cost_usd
        
        gen_data = GenerationData(
            name=name,
            model=model,
            start_time=start_time,
            end_time=time.time(),
            input=input,
            output=output,
            usage=usage_metrics,
            metadata=metadata,
            level=level
        )
        self._generations.append(gen_data)
        
        if self._obs.enabled and self._trace:
            self._trace.generation(
                name=name,
                model=model,
                input=input,
                output=output,
                usage={
                    "input": usage_metrics.prompt_tokens,
                    "output": usage_metrics.completion_tokens,
                    "total": usage_metrics.total_tokens,
                    "unit": "TOKENS"
                } if usage else None,
                metadata={
                    **(metadata or {}),
                    "cost_usd": usage_metrics.cost_usd
                },
                level=level
            )
        
        logger.debug(
            f"Generation '{name}' recorded: model={model}, "
            f"tokens={usage_metrics.total_tokens}, cost=${usage_metrics.cost_usd:.4f}"
        )
    
    def event(
        self,
        name: str,
        input: Optional[Dict[str, Any]] = None,
        output: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        level: str = "DEFAULT"
    ):
        """
        Record a discrete event within the trace.
        
        Args:
            name: Event name
            input: Event input data
            output: Event output data
            metadata: Additional metadata
            level: Log level
        """
        if self._obs.enabled and self._trace:
            self._trace.event(
                name=name,
                input=input,
                output=output,
                metadata=metadata,
                level=level
            )
        
        logger.debug(f"Event '{name}' recorded")
    
    def update_metadata(self, **kwargs):
        """Update trace metadata."""
        self.metadata.update(kwargs)
        if self._obs.enabled and self._trace:
            self._trace.update(metadata=self.metadata)
    
    @property
    def trace_id(self) -> str:
        return self._trace_id


@contextmanager
def trace_query(
    question: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    portfolio_id: Optional[str] = None,
    tickers: Optional[List[str]] = None,
    tags: Optional[List[str]] = None
):
    """
    Context manager for tracing a user query against portfolio.
    
    This is the main entry point for query observability.
    
    Args:
        question: The user's question
        user_id: Optional user identifier
        session_id: Optional session identifier
        portfolio_id: Optional portfolio identifier
        tickers: Optional list of tickers mentioned in query
        tags: Optional additional tags
    
    Yields:
        TraceContext for adding spans and generations
    
    Example:
        with trace_query(question="What is TCS revenue?", user_id="user123") as trace:
            with trace.span("routing", input={"question": question}):
                # routing logic
                pass
            
            with trace.span("retrieval", metadata={"method": "collapsed_tree"}):
                # retrieval logic
                pass
            
            trace.generation(
                name="answer_generation",
                model="gpt-4o-mini",
                input=prompt,
                output=answer,
                usage={"prompt_tokens": 500, "completion_tokens": 200}
            )
    """
    metadata = {
        "question": question[:500],  # Truncate for storage
        "question_length": len(question),
        "workflow": "user_query"
    }
    
    if portfolio_id:
        metadata["portfolio_id"] = portfolio_id
    if tickers:
        metadata["tickers"] = tickers
    
    trace = TraceContext(
        name="finrag_query",
        trace_type="query",
        metadata=metadata,
        user_id=user_id,
        session_id=session_id,
        tags=tags or []
    )
    
    with trace:
        yield trace


@contextmanager
def trace_document_parsing(
    file_path: str,
    document_id: Optional[str] = None,
    ticker: Optional[str] = None,
    company_name: Optional[str] = None,
    document_type: Optional[str] = None,
    tags: Optional[List[str]] = None
):
    """
    Context manager for tracing document parsing.
    
    This is the main entry point for document parsing observability.
    
    Args:
        file_path: Path to the document being parsed
        document_id: Optional document identifier
        ticker: Optional ticker symbol associated with document
        company_name: Optional company name
        document_type: Optional document type (e.g., "annual_report", "quarterly")
        tags: Optional additional tags
    
    Yields:
        TraceContext for adding spans and generations
    
    Example:
        with trace_document_parsing(file_path="/path/to/report.pdf", ticker="TCS") as trace:
            with trace.span("pdf_extraction", metadata={"parser": "llamaparse"}):
                text = extract_text(file_path)
            
            with trace.span("chunking", metadata={"chunk_count": len(chunks)}):
                chunks = chunk_text(text)
            
            with trace.span("embedding") as span:
                embeddings = create_embeddings(chunks)
                trace.generation(
                    name="embedding_batch",
                    model="text-embedding-3-small",
                    input={"chunk_count": len(chunks)},
                    usage={"prompt_tokens": token_count, "completion_tokens": 0}
                )
    """
    import os
    file_name = os.path.basename(file_path)
    file_size = 0
    try:
        file_size = os.path.getsize(file_path)
    except:
        pass
    
    metadata = {
        "file_path": file_path,
        "file_name": file_name,
        "file_size_bytes": file_size,
        "workflow": "document_parsing"
    }
    
    if document_id:
        metadata["document_id"] = document_id
    if ticker:
        metadata["ticker"] = ticker
    if company_name:
        metadata["company_name"] = company_name
    if document_type:
        metadata["document_type"] = document_type
    
    trace = TraceContext(
        name="finrag_document_parsing",
        trace_type="document_parsing",
        metadata=metadata,
        tags=tags or []
    )
    
    with trace:
        yield trace


def trace_llm_call(name: str = None):
    """Decorator for tracing LLM calls."""
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Just call the function - actual tracing happens via trace context
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Convenience functions
def get_langfuse() -> Optional["Langfuse"]:
    """Get the Langfuse client instance."""
    obs = LangfuseObservability()
    return obs.client


def flush_langfuse():
    """Flush any pending Langfuse traces."""
    obs = LangfuseObservability()
    obs.flush()


def langfuse_context() -> LangfuseObservability:
    """Get the LangfuseObservability singleton."""
    return LangfuseObservability()
