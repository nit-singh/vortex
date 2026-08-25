"""Observability module with Langfuse integration for LLM cost tracking.

This module provides:
1. Local metrics (counters, latency, cost)
2. Langfuse integration for OpenAI API observability
3. Decorators for automatic tracing

Setup:
    1. Create account at https://cloud.langfuse.com
    2. Create a project and get API keys
    3. Set environment variables:
       - LANGFUSE_PUBLIC_KEY=pk-lf-...
       - LANGFUSE_SECRET_KEY=sk-lf-...
       - LANGFUSE_HOST=https://cloud.langfuse.com (optional, default)

Usage:
    from kyc_observability import observe_llm, get_langfuse, track_generation
    
    # Decorator approach
    @observe_llm(name="generate_report")
    def generate_kyc_report(master_json):
        response = openai.chat.completions.create(...)
        return response
    
    # Manual tracking
    with track_generation("risk_analysis") as gen:
        response = openai.chat.completions.create(...)
        gen.end(output=response, usage=response.usage)

View metrics at: https://cloud.langfuse.com/project/<your-project-id>
"""

from __future__ import annotations

import functools
import json
import logging
import os
import threading
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Optional, TypeVar, Union

LOGGER = logging.getLogger(__name__)

# ============================================================================
# Local Metrics (unchanged)
# ============================================================================

_METRIC_LOCK = threading.Lock()
_COUNTERS: Counter[str] = Counter()
_LATENCY: Dict[str, list[float]] = defaultdict(list)
_COST_ACCUM: Dict[str, float] = defaultdict(float)


def increment(metric: str, value: int = 1, **labels: Any) -> None:
    with _METRIC_LOCK:
        _COUNTERS[metric] += value
    LOGGER.debug("metric_increment", extra={"metric": metric, "value": value, "labels": labels})


def observe_latency(metric: str, duration_ms: float, **labels: Any) -> None:
    with _METRIC_LOCK:
        _LATENCY[metric].append(duration_ms)
    LOGGER.debug(
        "metric_latency",
        extra={"metric": metric, "duration_ms": round(duration_ms, 3), "labels": labels},
    )


def accumulate_cost(metric: str, cost: float, currency: str = "USD", **labels: Any) -> None:
    with _METRIC_LOCK:
        _COST_ACCUM[f"{metric}:{currency}"] += cost
    LOGGER.debug(
        "metric_cost",
        extra={"metric": metric, "cost": cost, "currency": currency, "labels": labels},
    )


@contextmanager
def track_latency(metric: str, **labels: Any):
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        observe_latency(metric, duration_ms, **labels)


def snapshot_metrics() -> Dict[str, Any]:
    with _METRIC_LOCK:
        return {
            "counters": dict(_COUNTERS),
            "latency": {k: list(v) for k, v in _LATENCY.items()},
            "cost": dict(_COST_ACCUM),
        }


def export_metrics(path: str | None = None) -> Dict[str, Any]:
    snapshot = snapshot_metrics()
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2)
    return snapshot


def enable_verbose_logging() -> None:
    if os.getenv("KYC_VERBOSE_METRICS"):
        LOGGER.setLevel(logging.DEBUG)


# ============================================================================
# Langfuse Integration
# ============================================================================

# Try to import Langfuse
try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    Langfuse = None
    LOGGER.warning(
        "Langfuse not installed. Run: pip install langfuse\n"
        "LLM observability will be disabled."
    )

# Singleton Langfuse client
_langfuse_client: Optional["Langfuse"] = None
_langfuse_lock = threading.Lock()


def get_langfuse() -> Optional["Langfuse"]:
    """Get or create the Langfuse client singleton.
    
    Returns None if Langfuse is not configured or not installed.
    """
    global _langfuse_client
    
    if not LANGFUSE_AVAILABLE:
        return None
    
    with _langfuse_lock:
        if _langfuse_client is None:
            public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
            secret_key = os.getenv("LANGFUSE_SECRET_KEY")
            
            if not public_key or not secret_key:
                LOGGER.warning(
                    "Langfuse API keys not set. Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.\n"
                    "Get keys at: https://cloud.langfuse.com"
                )
                return None
            
            host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
            
            try:
                _langfuse_client = Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    host=host,
                )
                LOGGER.info("Langfuse client initialized (host=%s)", host)
            except Exception as e:
                LOGGER.error("Failed to initialize Langfuse: %s", e)
                return None
    
    return _langfuse_client


def shutdown_langfuse() -> None:
    """Flush and shutdown Langfuse client."""
    global _langfuse_client
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
            _langfuse_client.shutdown()
            LOGGER.info("Langfuse client shutdown complete")
        except Exception as e:
            LOGGER.error("Error shutting down Langfuse: %s", e)
        finally:
            _langfuse_client = None


# ============================================================================
# OpenAI Cost Calculation
# ============================================================================

# Pricing per 1M tokens (as of Dec 2024)
OPENAI_PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
}


def calculate_openai_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate cost in USD for an OpenAI API call."""
    pricing = OPENAI_PRICING.get(model, OPENAI_PRICING.get("gpt-4o-mini"))
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


# ============================================================================
# Tracing Decorators and Context Managers
# ============================================================================

F = TypeVar("F", bound=Callable[..., Any])


def observe_llm(
    name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    capture_input: bool = True,
    capture_output: bool = True,
) -> Callable[[F], F]:
    """Decorator to observe LLM function calls with Langfuse.
    
    Usage:
        @observe_llm(name="generate_report")
        def generate_kyc_report(master_json):
            response = openai.chat.completions.create(...)
            return response
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            trace_name = name or func.__name__
            
            # Track locally
            start_time = time.perf_counter()
            increment(f"llm_calls:{trace_name}")
            
            # Get Langfuse client
            lf = get_langfuse()
            trace = None
            
            if lf:
                try:
                    trace = lf.start_span(
                        name=trace_name,
                        metadata={
                            **(metadata or {}),
                            "function": func.__name__,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                        input=args if capture_input else None,
                    )
                except Exception as e:
                    LOGGER.warning("Failed to create Langfuse trace: %s", e)
            
            try:
                result = func(*args, **kwargs)
                
                # Record success
                duration_ms = (time.perf_counter() - start_time) * 1000
                observe_latency(f"llm_latency:{trace_name}", duration_ms)
                
                if trace and capture_output:
                    try:
                        trace.update(output=str(result)[:1000])  # Truncate large outputs
                    except Exception:
                        pass
                
                return result
                
            except Exception as e:
                # Record failure
                increment(f"llm_errors:{trace_name}")
                if trace:
                    try:
                        trace.update(
                            level="ERROR",
                            status_message=str(e),
                        )
                    except Exception:
                        pass
                raise
            finally:
                if lf:
                    try:
                        lf.flush()
                    except Exception:
                        pass
        
        return wrapper  # type: ignore
    return decorator


class GenerationTracker:
    """Context manager for tracking LLM generations."""
    
    def __init__(
        self,
        name: str,
        model: Optional[str] = None,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.model = model
        self.trace_id = trace_id
        self.metadata = metadata or {}
        self.start_time = None
        self.generation = None
        self._lf = None
    
    def __enter__(self) -> "GenerationTracker":
        self.start_time = time.perf_counter()
        increment(f"generation_started:{self.name}")
        
        self._lf = get_langfuse()
        if self._lf:
            try:
                self.generation = self._lf.start_observation(
                    name=self.name,
                    as_type='generation',
                    model=self.model,
                    metadata={
                        **self.metadata,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception as e:
                LOGGER.warning("Failed to create Langfuse generation: %s", e)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        observe_latency(f"generation_latency:{self.name}", duration_ms)
        
        if exc_type:
            increment(f"generation_errors:{self.name}")
            if self.generation:
                try:
                    self.generation.update(
                        level="ERROR",
                        status_message=str(exc_val),
                    )
                    self.generation.end()
                except Exception:
                    pass
        
        if self._lf:
            try:
                self._lf.flush()
            except Exception:
                pass
        
        return False  # Don't suppress exceptions
    
    def end(
        self,
        output: Any = None,
        usage: Optional[Dict[str, int]] = None,
        model: Optional[str] = None,
    ) -> None:
        """End the generation with output and usage info.
        
        Args:
            output: The LLM response
            usage: Dict with prompt_tokens, completion_tokens, total_tokens
            model: Model name (if not set in constructor)
        """
        model = model or self.model
        
        # Calculate and record cost
        if usage and model:
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            cost = calculate_openai_cost(model, input_tokens, output_tokens)
            accumulate_cost(f"openai:{self.name}", cost)
            
            # Log for visibility
            LOGGER.info(
                "LLM generation: name=%s model=%s tokens=%d cost=$%.6f",
                self.name, model, usage.get("total_tokens", 0), cost
            )
        
        if self.generation:
            try:
                # Update generation with output, model, and usage details
                update_kwargs = {}
                if output is not None:
                    update_kwargs["output"] = str(output)[:2000] if len(str(output)) > 2000 else str(output)
                if model:
                    update_kwargs["model"] = model
                if usage:
                    update_kwargs["usage_details"] = {
                        "input": usage.get("prompt_tokens", 0),
                        "output": usage.get("completion_tokens", 0),
                        "total": usage.get("total_tokens", 0),
                    }
                
                if update_kwargs:
                    self.generation.update(**update_kwargs)
                
                # End the generation
                self.generation.end()
            except Exception as e:
                LOGGER.warning("Failed to end Langfuse generation: %s", e)


@contextmanager
def track_generation(
    name: str,
    model: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Context manager for tracking LLM generations.
    
    Usage:
        with track_generation("kyc_report", model="gpt-4o-mini") as gen:
            response = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[...],
            )
            gen.end(
                output=response.choices[0].message.content,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            )
    """
    tracker = GenerationTracker(name=name, model=model, metadata=metadata)
    with tracker:
        yield tracker


def track_llm_generation(
    name: str,
    model: str,
    input_messages: Any,
    output: str,
    input_tokens: int,
    output_tokens: int,
    cost: float,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Track a completed LLM generation (non-context-manager version).
    
    Use this when you want to track after the fact, not wrap the call.
    
    Args:
        name: Name of the generation (e.g., "tool_selection")
        model: Model name (e.g., "gpt-4o-mini")
        input_messages: The input messages sent to the LLM
        output: The LLM response
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cost: Calculated cost in USD
        metadata: Optional additional metadata
    """
    # Track locally
    increment(f"generation_completed:{name}")
    
    # Log for visibility
    LOGGER.info(
        "LLM generation: name=%s model=%s input_tokens=%d output_tokens=%d cost=$%.6f",
        name, model, input_tokens, output_tokens, cost
    )
    
    # Track in Langfuse
    lf = get_langfuse()
    if lf:
        try:
            gen = lf.start_observation(
                name=name,
                as_type='generation',
                model=model,
                metadata={
                    **(metadata or {}),
                    "timestamp": datetime.utcnow().isoformat(),
                },
                input=input_messages,
                output=output[:2000] if len(output) > 2000 else output,  # Truncate large outputs
                usage_details={
                    "input": input_tokens,
                    "output": output_tokens,
                    "total": input_tokens + output_tokens,
                },
                cost_details={
                    "cost_usd": cost,
                },
            )
            gen.end()
            lf.flush()
        except Exception as e:
            LOGGER.warning("Failed to track generation in Langfuse: %s", e)


# ============================================================================
# Trace Context for Multi-Step Operations
# ============================================================================

class TraceContext:
    """Context for multi-step operations (e.g., full KYC flow)."""
    
    def __init__(
        self,
        name: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.user_id = user_id
        self.metadata = metadata or {}
        self.trace = None
        self.start_time = None
        self._lf = None
    
    def __enter__(self) -> "TraceContext":
        self.start_time = time.perf_counter()
        increment(f"trace_started:{self.name}")
        
        self._lf = get_langfuse()
        if self._lf:
            try:
                # Include user_id in metadata if provided
                trace_metadata = {
                    **self.metadata,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                if self.user_id:
                    trace_metadata["user_id"] = self.user_id
                
                self.trace = self._lf.start_span(
                    name=self.name,
                    metadata=trace_metadata,
                )
            except Exception as e:
                LOGGER.warning("Failed to create Langfuse trace: %s", e)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        observe_latency(f"trace_latency:{self.name}", duration_ms)
        
        if exc_type:
            increment(f"trace_errors:{self.name}")
        else:
            increment(f"trace_completed:{self.name}")
        
        if self._lf:
            try:
                self._lf.flush()
            except Exception:
                pass
        
        return False
    
    def span(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Create a span within this trace."""
        if self.trace and self._lf:
            try:
                return self.trace.start_span(name=name, metadata=metadata)
            except Exception as e:
                LOGGER.warning("Failed to create span: %s", e)
        return None
    
    def generation(
        self,
        name: str,
        model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Create a generation within this trace."""
        if self.trace and self._lf:
            try:
                return self.trace.start_observation(name=name, as_type='generation', model=model, metadata=metadata)
            except Exception as e:
                LOGGER.warning("Failed to create generation: %s", e)
        return None
    
    def event(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log an event within this trace."""
        if self.trace:
            try:
                self.trace.create_event(name=name, metadata=metadata)
            except Exception as e:
                LOGGER.warning("Failed to log event: %s", e)


@contextmanager
def trace_kyc_flow(
    user_id: str,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Context manager for tracing full KYC flow.
    
    Usage:
        with trace_kyc_flow(user_id="USER123") as ctx:
            # Document processing
            ctx.event("documents_uploaded")
            
            # Report generation (nested generation)
            gen = ctx.generation("report", model="gpt-4o-mini")
            response = openai.chat.completions.create(...)
            gen.end(output=response, usage=response.usage)
            
            # Risk scoring
            ctx.event("risk_scored", metadata={"score": 60.4})
    """
    ctx = TraceContext(name="kyc_flow", user_id=user_id, metadata=metadata)
    with ctx:
        yield ctx


# ==========================================================================
# Tool Invocation Tracing Helpers
# ==========================================================================

@contextmanager
def track_tool_invocation(
    tool_name: str,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Trace a non-LLM tool invocation in Langfuse.

    Creates a short-lived trace with start/completion events so every MCP
    tool execution is visible alongside LLM generations.
    """

    lf = get_langfuse()
    trace = None
    merged_meta = {"tool": tool_name, **(metadata or {})}
    start = time.perf_counter()

    if lf:
        try:
            # Include user_id in metadata if provided
            tool_metadata = merged_meta.copy()
            if user_id:
                tool_metadata["user_id"] = user_id
            
            trace = lf.start_span(
                name=f"tool:{tool_name}",
                metadata=tool_metadata,
            )
            trace.create_event(name="tool_started", metadata=merged_meta)
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.warning("Failed to start Langfuse trace for %s: %s", tool_name, exc)
            trace = None

    try:
        yield trace
        duration_ms = (time.perf_counter() - start) * 1000
        if trace:
            trace.create_event(
                name="tool_completed",
                metadata={**merged_meta, "duration_ms": round(duration_ms, 3)},
            )
    except Exception as exc:
        if trace:
            trace.create_event(
                name="tool_failed",
                metadata={**merged_meta, "error": str(exc)},
            )
        raise
    finally:
        if lf:
            try:
                lf.flush()
            except Exception:
                pass


# ============================================================================
# Utility Functions
# ============================================================================

# ============================================================================
# LLM Cost Accumulator (Enhanced for Detailed Tracking)
# ============================================================================

_LLM_COSTS: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "cost": 0.0,
})
_LLM_COST_LOCK = threading.Lock()


def accumulate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost: float,
) -> None:
    """Accumulate cost for a specific model."""
    with _LLM_COST_LOCK:
        _LLM_COSTS[model]["calls"] += 1
        _LLM_COSTS[model]["input_tokens"] += input_tokens
        _LLM_COSTS[model]["output_tokens"] += output_tokens
        _LLM_COSTS[model]["cost"] += cost


def get_cost_summary() -> Dict[str, Any]:
    """Get a structured cost summary."""
    with _LLM_COST_LOCK:
        total_cost = sum(m["cost"] for m in _LLM_COSTS.values())
        total_input = sum(m["input_tokens"] for m in _LLM_COSTS.values())
        total_output = sum(m["output_tokens"] for m in _LLM_COSTS.values())
        
        return {
            "total_cost": total_cost,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "by_model": dict(_LLM_COSTS),
        }


def print_cost_summary() -> None:
    """Print cost summary to console."""
    summary = get_cost_summary()
    print("\n=== OpenAI API Cost Summary ===")
    print(f"Total Cost: ${summary['total_cost']:.6f}")
    print(f"Total Input Tokens: {summary['total_input_tokens']}")
    print(f"Total Output Tokens: {summary['total_output_tokens']}")
    if summary['by_model']:
        print("\nBy Model:")
        for model, stats in summary['by_model'].items():
            print(f"  {model}:")
            print(f"    Calls: {stats['calls']}")
            print(f"    Input: {stats['input_tokens']} tokens")
            print(f"    Output: {stats['output_tokens']} tokens")
            print(f"    Cost: ${stats['cost']:.6f}")


# ============================================================================
# Integration with OpenAI Client (Optional Wrapper)
# ============================================================================

def wrap_openai_client(client):
    """Wrap OpenAI client to automatically track all calls.
    
    Usage:
        from openai import OpenAI
        client = OpenAI()
        client = wrap_openai_client(client)
        
        # Now all calls are automatically tracked
        response = client.chat.completions.create(...)
    """
    if not LANGFUSE_AVAILABLE:
        LOGGER.warning("Langfuse not available, returning unwrapped client")
        return client
    
    try:
        from langfuse.openai import OpenAI as LangfuseOpenAI
        
        # Create new client with same API key
        return LangfuseOpenAI(api_key=client.api_key)
    except ImportError:
        LOGGER.warning("langfuse.openai not available, returning unwrapped client")
        return client


# ============================================================================
# Auto-initialize on import (if env vars set)
# ============================================================================

def _auto_init():
    """Auto-initialize Langfuse if environment variables are set."""
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        get_langfuse()  # Initialize the client

_auto_init()