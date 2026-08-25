"""FinRAG Orchestrator - LLM-driven tool selection and execution."""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from openai import OpenAI

from .tools import ToolRegistry, Tool, ToolResult, ToolCategory
from ..observability import trace_query, flush_langfuse

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator."""
    
    routing_model: str = "gpt-4o-mini"
    synthesis_model: str = "gpt-4o-mini"
    max_tools_per_query: int = 3
    allow_parallel_tools: bool = True
    default_tool: str = "query_documents"
    fallback_on_error: bool = True
    verbose_reasoning: bool = False
    include_tool_results: bool = False
    openai_api_key: Optional[str] = None


@dataclass
class RoutingDecision:
    """Result of the routing LLM's decision."""
    tools: List[Dict[str, Any]]
    reasoning: str
    confidence: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tools": self.tools,
            "reasoning": self.reasoning,
            "confidence": self.confidence
        }


@dataclass 
class OrchestratorResult:
    """Final result from the orchestrator."""
    answer: str
    tools_used: List[str]
    tool_results: List[ToolResult]
    routing_decision: RoutingDecision
    total_time: float
    success: bool
    error: Optional[str] = None
    usage_stats: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "tools_used": self.tools_used,
            "tool_results": [tr.to_dict() for tr in self.tool_results],
            "routing": self.routing_decision.to_dict(),
            "total_time": self.total_time,
            "success": self.success,
            "error": self.error,
            "usage_stats": self.usage_stats
        }


class FinRAGOrchestrator:
    """LLM-powered orchestrator for FinRAG tool selection and execution."""
    
    ROUTING_SYSTEM_PROMPT = """You are a financial assistant routing system. Your job is to analyze user queries and decide which tool(s) to call.

## Available Tools

{tool_descriptions}

## Instructions

1. Analyze the user's query carefully
2. Decide which tool(s) are needed to answer it
3. Extract any relevant parameters (tickers, company names, etc.) from the query
4. Return your decision as JSON

## Parameter Extraction Rules

- **Tickers**: Extract stock symbols. Common Indian stocks: TCS, INFY (Infosys), RELIANCE, HDFCBANK, ICICIBANK, WIPRO, BHARTIARTL (Airtel), ITC, SBIN (SBI), HEROMOTOCO
- **Company Names**: Use full names for better matching: "Tata Consultancy Services", "Infosys Limited", "Reliance Industries", etc.
- **For NSE stocks**: Use ticker_suffix ".NS"
- **For BSE stocks**: Use ticker_suffix ".BO"

## Decision Rules

1. **Simple factual questions** → query_documents
2. **Investment advice / ratings / stock analysis** → query_documents (search for relevant financial information)
3. **Comparing two stocks** → compare_stocks
4. **Portfolio questions** → get_portfolio (possibly + analyze_with_context)
5. **Specific metrics** → get_fundamentals
6. **Complex "why" questions about portfolio** → analyze_with_context
7. **Multiple unrelated questions** → Use multiple tools

## Response Format

Return ONLY valid JSON (no markdown, no extra text):
{{
    "tools": [
        {{"name": "tool_name", "params": {{"param1": "value1"}}}},
        ...
    ],
    "reasoning": "Brief explanation of why these tools were chosen",
    "confidence": 0.95
}}

## Examples

Query: "What is TCS's revenue for 2024?"
Response: {{"tools": [{{"name": "query_documents", "params": {{"question": "What is TCS's revenue for 2024?", "filter_company": "Tata Consultancy Services"}}}}], "reasoning": "Factual question about financials, need to search annual reports", "confidence": 0.95}}

Query: "Should I buy Infosys stock?"
Response: {{"tools": [{{"name": "query_documents", "params": {{"question": "What are Infosys's financial performance, growth prospects, and key risks?", "filter_company": "Infosys Limited"}}}}], "reasoning": "Investment question - search for relevant financial data from annual reports", "confidence": 0.9}}

Query: "Compare TCS and Infosys"
Response: {{"tools": [{{"name": "compare_stocks", "params": {{"ticker1": "TCS", "ticker2": "INFY", "company_name1": "Tata Consultancy Services", "company_name2": "Infosys Limited"}}}}], "reasoning": "Direct comparison request", "confidence": 0.95}}

Query: "Why is Hero MotoCorp in my portfolio?"
Response: {{"tools": [{{"name": "analyze_with_context", "params": {{"question": "Why is Hero MotoCorp in my portfolio?", "include_portfolio": true, "include_fundamentals": true}}}}], "reasoning": "Complex question needing portfolio context + document analysis", "confidence": 0.9}}

Query: "What's my portfolio allocation?"
Response: {{"tools": [{{"name": "get_portfolio", "params": {{"include_analysis": true}}}}], "reasoning": "Direct portfolio query", "confidence": 0.95}}
"""
    SYNTHESIS_SYSTEM_PROMPT = """You are a helpful financial assistant. Synthesize the tool results into a clear, informative response for the user.

## Guidelines
1. Be concise but comprehensive
2. Cite specific numbers and facts from the results
3. If results are from multiple tools, integrate them coherently
4. If a tool failed, acknowledge it gracefully
5. Use bullet points for clarity when appropriate
6. For investment-related responses, include appropriate disclaimers

## Format
- Use markdown formatting
- Highlight key metrics in bold
- Use tables for comparisons if appropriate
"""

    def __init__(
        self, 
        pipeline: Any,  # FinRAGPipeline instance
        config: OrchestratorConfig = None,
        memory_size: int = 5
    ):
        """
        Initialize the orchestrator.
        
        Args:
            pipeline: FinRAGPipeline instance with loaded tree
            config: Orchestrator configuration
            memory_size: Number of conversation turns to remember (default: 5)
        """
        self.pipeline = pipeline
        self.config = config or OrchestratorConfig()
        self.tool_registry = ToolRegistry()
        self.memory_size = memory_size
        self.conversation_history: List[Dict[str, str]] = []  # Stores last N turns
        
        # Initialize OpenAI client
        api_key = self.config.openai_api_key
        if not api_key:
            import os
            api_key = os.getenv("OPENAI_API_KEY")
        
        self.client = OpenAI(api_key=api_key)
        
        logger.info(f"Orchestrator initialized with {len(self.tool_registry.list_tools())} tools")
    
    def chat(self, query: str, user_id: str = None, session_id: str = None, use_memory: bool = True) -> OrchestratorResult:
        """
        Main entry point - process a user query.
        
        Args:
            query: User's natural language query
            user_id: Optional user identifier for tracing
            session_id: Optional session identifier for tracing
            use_memory: Whether to use conversation history for context (default: True)
            
        Returns:
            OrchestratorResult with answer and metadata
        """
        start_time = time.time()
        
        # Build context from conversation history
        context_query = query
        if use_memory and self.conversation_history:
            history_context = self._format_conversation_history()
            context_query = f"{history_context}\n\nCurrent question: {query}"
            logger.info(f"Using {len(self.conversation_history)} previous turns for context")
        
        # Create Langfuse trace for the entire query flow
        with trace_query(
            question=query,
            user_id=user_id,
            session_id=session_id,
            tags=["orchestrator", "chat"]
        ) as trace:
            try:
                # Step 1: Route the query (with history context)
                logger.info(f"Processing query: {query[:100]}...")
                
                with trace.span("routing", input={"query": query[:500]}):
                    routing_decision, routing_usage = self._route_query_with_usage(context_query)
                    
                    # Record routing LLM call
                    trace.generation(
                        name="routing_llm",
                        model=self.config.routing_model,
                        input={"query": query, "has_history": len(self.conversation_history) > 0},
                        output=json.dumps(routing_decision.to_dict()),
                        usage=routing_usage,
                        metadata={
                            "tools_selected": [t["name"] for t in routing_decision.tools],
                            "confidence": routing_decision.confidence,
                            "history_turns": len(self.conversation_history)
                        }
                    )
                
                logger.info(f"Routing decision: {[t['name'] for t in routing_decision.tools]}")
                
                # Step 2: Execute tools
                with trace.span(
                    "tool_execution",
                    input={"tools": [t["name"] for t in routing_decision.tools]},
                    metadata={"tool_count": len(routing_decision.tools)}
                ):
                    tool_results = self._execute_tools_traced(routing_decision.tools, trace)
                
                # Step 3: Synthesize response
                with trace.span("synthesis", input={"tool_count": len(tool_results)}):
                    answer, synthesis_usage = self._synthesize_response_with_usage(
                        query, routing_decision, tool_results
                    )
                    
                    # Record synthesis LLM call if it was used
                    if synthesis_usage:
                        trace.generation(
                            name="synthesis_llm",
                            model=self.config.synthesis_model,
                            input={"query": query, "tool_results": len(tool_results)},
                            output=answer[:1000],  # Truncate for storage
                            usage=synthesis_usage,
                            metadata={"tools_used": [t["name"] for t in routing_decision.tools]}
                        )
                
                # Calculate total usage stats (handle None cases)
                routing_usage = routing_usage or {}
                synthesis_usage = synthesis_usage or {}
                total_prompt_tokens = routing_usage.get("prompt_tokens", 0) + synthesis_usage.get("prompt_tokens", 0)
                total_completion_tokens = routing_usage.get("completion_tokens", 0) + synthesis_usage.get("completion_tokens", 0)
                total_tokens = total_prompt_tokens + total_completion_tokens
                
                # Calculate cost (gpt-4o-mini pricing: $0.15/1M input, $0.60/1M output)
                input_cost = (total_prompt_tokens / 1_000_000) * 0.15
                output_cost = (total_completion_tokens / 1_000_000) * 0.60
                total_cost = input_cost + output_cost
                
                usage_stats = {
                    "routing": routing_usage,
                    "synthesis": synthesis_usage,
                    "total": {
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_tokens,
                        "cost_usd": total_cost,
                        "cost_breakdown": {
                            "input_cost": input_cost,
                            "output_cost": output_cost
                        }
                    }
                }
                
                # Update trace with final output
                trace.update_metadata(
                    success=True,
                    tools_used=[t["name"] for t in routing_decision.tools],
                    answer_length=len(answer),
                    total_tokens=total_tokens,
                    total_cost_usd=total_cost
                )
                
                result = OrchestratorResult(
                    answer=answer,
                    tools_used=[t["name"] for t in routing_decision.tools],
                    tool_results=tool_results,
                    routing_decision=routing_decision,
                    total_time=time.time() - start_time,
                    success=True,
                    usage_stats=usage_stats
                )
                
                # Update conversation history
                if use_memory:
                    self._add_to_history(query, answer)
                
                # Flush traces
                flush_langfuse()
                
                return result
                
            except Exception as e:
                logger.error(f"Orchestrator error: {e}", exc_info=True)
                
                trace.event(
                    name="error",
                    input={"query": query},
                    output={"error": str(e)},
                    level="ERROR"
                )
                
                # Fallback: try default tool
                if self.config.fallback_on_error:
                    try:
                        return self._fallback_response(query, str(e), start_time)
                    except Exception as e2:
                        logger.error(f"Fallback also failed: {e2}")
                
                return OrchestratorResult(
                    answer=f"I encountered an error processing your request: {str(e)}",
                    tools_used=[],
                    tool_results=[],
                    routing_decision=RoutingDecision(tools=[], reasoning="Error occurred", confidence=0),
                    total_time=time.time() - start_time,
                    success=False,
                    error=str(e)
                )
    
    def _format_conversation_history(self) -> str:
        """Format conversation history for context."""
        if not self.conversation_history:
            return ""
        
        lines = ["## Recent Conversation History"]
        for i, turn in enumerate(self.conversation_history, 1):
            lines.append(f"\nUser: {turn['user']}")
            # Truncate long answers for context
            answer = turn['assistant']
            if len(answer) > 300:
                answer = answer[:300] + "..."
            lines.append(f"Assistant: {answer}")
        
        return "\n".join(lines)
    
    def _add_to_history(self, user_query: str, assistant_answer: str) -> None:
        """Add a conversation turn to history, maintaining max size."""
        self.conversation_history.append({
            "user": user_query,
            "assistant": assistant_answer
        })
        
        # Keep only the last N turns
        if len(self.conversation_history) > self.memory_size:
            self.conversation_history = self.conversation_history[-self.memory_size:]
    
    def clear_history(self) -> None:
        """Clear conversation history."""
        self.conversation_history = []
        logger.info("Conversation history cleared")
    
    def _route_query_with_usage(self, query: str) -> Tuple[RoutingDecision, Dict[str, int]]:
        """Use LLM to decide which tools to call, returning usage info."""
        
        # Build the routing prompt
        tool_descriptions = self.tool_registry.generate_routing_prompt()
        system_prompt = self.ROUTING_SYSTEM_PROMPT.format(
            tool_descriptions=tool_descriptions
        )
        
        # Call the routing LLM
        response = self.client.chat.completions.create(
            model=self.config.routing_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            temperature=0.1,
            max_tokens=500
        )
        
        # Extract usage
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
        
        # Parse the response
        response_text = response.choices[0].message.content.strip()
        
        # Clean up response (remove markdown if present)
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        response_text = response_text.strip()
        
        try:
            decision_data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse routing response: {response_text}")
            decision_data = {
                "tools": [{"name": self.config.default_tool, "params": {"question": query}}],
                "reasoning": "Fallback due to parse error",
                "confidence": 0.5
            }
        
        # Validate tools exist
        valid_tools = []
        for tool_call in decision_data.get("tools", []):
            tool_name = tool_call.get("name")
            if self.tool_registry.get(tool_name):
                valid_tools.append(tool_call)
            else:
                logger.warning(f"Unknown tool: {tool_name}")
        
        if not valid_tools:
            valid_tools = [{"name": self.config.default_tool, "params": {"question": query}}]
        
        valid_tools = valid_tools[:self.config.max_tools_per_query]
        
        routing_decision = RoutingDecision(
            tools=valid_tools,
            reasoning=decision_data.get("reasoning", ""),
            confidence=decision_data.get("confidence", 0.8)
        )
        
        return routing_decision, usage
    
    def _execute_tools_traced(self, tool_calls: List[Dict[str, Any]], trace) -> List[ToolResult]:
        """Execute the selected tools with tracing."""
        results = []
        
        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            params = tool_call.get("params", {})
            
            start_time = time.time()
            
            with trace.span(
                f"tool_{tool_name}",
                input={"params": params},
                metadata={"tool_name": tool_name}
            ):
                try:
                    result = self._execute_single_tool(tool_name, params)
                    execution_time = time.time() - start_time
                    
                    results.append(ToolResult(
                        tool_name=tool_name,
                        success=True,
                        result=result,
                        execution_time=execution_time
                    ))
                    
                    # Log tool-specific metrics
                    trace.event(
                        name=f"{tool_name}_complete",
                        output={"success": True, "execution_time": execution_time}
                    )
                    
                except Exception as e:
                    execution_time = time.time() - start_time
                    logger.error(f"Tool {tool_name} failed: {e}")
                    
                    results.append(ToolResult(
                        tool_name=tool_name,
                        success=False,
                        result=None,
                        error=str(e),
                        execution_time=execution_time
                    ))
                    
                    trace.event(
                        name=f"{tool_name}_error",
                        output={"error": str(e)},
                        level="ERROR"
                    )
        
        return results
    
    def _execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[ToolResult]:
        """Execute the selected tools."""
        results = []
        
        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            params = tool_call.get("params", {})
            
            start_time = time.time()
            
            try:
                result = self._execute_single_tool(tool_name, params)
                results.append(ToolResult(
                    tool_name=tool_name,
                    success=True,
                    result=result,
                    execution_time=time.time() - start_time
                ))
            except Exception as e:
                logger.error(f"Tool {tool_name} failed: {e}")
                results.append(ToolResult(
                    tool_name=tool_name,
                    success=False,
                    result=None,
                    error=str(e),
                    execution_time=time.time() - start_time
                ))
        
        return results
    
    def _execute_single_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Execute a single tool and return its result."""
        
        logger.info(f"Executing tool: {tool_name} with params: {params}")
        
        if tool_name == "query_documents":
            return self._tool_query_documents(params)
        
        elif tool_name == "score_stock":
            return self._tool_score_stock(params)
        
        elif tool_name == "compare_stocks":
            return self._tool_compare_stocks(params)
        
        elif tool_name == "get_portfolio":
            return self._tool_get_portfolio(params)
        
        elif tool_name == "get_fundamentals":
            return self._tool_get_fundamentals(params)
        
        elif tool_name == "get_statistics":
            return self._tool_get_statistics(params)
        
        elif tool_name == "analyze_with_context":
            return self._tool_analyze_with_context(params)
        
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
    
    # ================== Tool Implementations ==================
    
    def _tool_query_documents(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute query_documents tool."""
        question = params.get("question", "")
        method = params.get("retrieval_method", "tree_traversal")
        top_k = params.get("top_k", 60)  # Use 0 for tree_traversal mode
        filter_company = params.get("filter_company")
        filter_sector = params.get("filter_sector")
        
        # Use the pipeline's query method (quiet=True to avoid duplicate output)
        result = self.pipeline.query(
            question=question,
            method=method,
            top_k=top_k,
            quiet=True
        )
        
        return {
            "answer": result.get("answer", ""),
            "retrieval_method": method,
            "nodes_retrieved": len(result.get("retrieved_nodes", [])),
            "filter_applied": {"company": filter_company, "sector": filter_sector}
        }
    
    def _tool_score_stock(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute score_stock tool."""
        ticker = params.get("ticker", "")
        company_name = params.get("company_name")
        ticker_suffix = params.get("ticker_suffix", ".NS")
        
        result = self.pipeline.score_stock(
            ticker=ticker,
            company_name=company_name,
            ticker_suffix=ticker_suffix,
            save_output=False
        )
        
        if not result:
            return {"error": f"Failed to score {ticker}"}
        
        return {
            "ticker": result.get("ticker"),
            "company_name": result.get("company_name"),
            "score": result.get("score"),
            "direction": result.get("direction"),
            "confidence": result.get("confidence"),
            "recommendation": result.get("recommendation"),
            "component_scores": result.get("component_scores"),
            "key_drivers": result.get("key_drivers", []),
            "risk_factors": result.get("risk_factors", [])
        }
    
    def _tool_compare_stocks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute compare_stocks tool."""
        ticker1 = params.get("ticker1", "")
        ticker2 = params.get("ticker2", "")
        company_name1 = params.get("company_name1")
        company_name2 = params.get("company_name2")
        ticker_suffix = params.get("ticker_suffix", ".NS")
        
        # Score both stocks
        score1 = self.pipeline.score_stock(ticker1, company_name1, ticker_suffix, False)
        score2 = self.pipeline.score_stock(ticker2, company_name2, ticker_suffix, False)
        
        comparison = {
            "stock1": {
                "ticker": ticker1,
                "company_name": score1.get("company_name") if score1 else ticker1,
                "score": score1.get("score") if score1 else None,
                "direction": score1.get("direction") if score1 else None,
                "component_scores": score1.get("component_scores") if score1 else None
            },
            "stock2": {
                "ticker": ticker2,
                "company_name": score2.get("company_name") if score2 else ticker2,
                "score": score2.get("score") if score2 else None,
                "direction": score2.get("direction") if score2 else None,
                "component_scores": score2.get("component_scores") if score2 else None
            }
        }
        
        # Determine winner
        if score1 and score2:
            if score1.get("score", 0) > score2.get("score", 0):
                comparison["recommendation"] = f"{ticker1} appears stronger based on our analysis"
            elif score2.get("score", 0) > score1.get("score", 0):
                comparison["recommendation"] = f"{ticker2} appears stronger based on our analysis"
            else:
                comparison["recommendation"] = "Both stocks are similarly rated"
        
        return comparison
    
    def _tool_get_portfolio(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get_portfolio tool."""
        ticker = params.get("ticker")
        include_analysis = params.get("include_analysis", True)
        
        portfolio_manager = self.pipeline.portfolio_manager
        
        if ticker:
            # Get specific stock info
            allocation = portfolio_manager.get_allocation_by_ticker(ticker)
            if allocation:
                return {
                    "found": True,
                    "ticker": ticker,
                    "allocation": allocation
                }
            else:
                return {
                    "found": False,
                    "ticker": ticker,
                    "message": f"{ticker} is not in your portfolio"
                }
        
        # Get full portfolio
        summary = portfolio_manager.get_portfolio_summary()
        allocations = portfolio_manager.get_allocations()
        
        result = {
            "summary": summary,
            "holdings": allocations
        }
        
        if include_analysis:
            try:
                analyzer = self.pipeline.portfolio_analyzer
                result["analysis"] = {
                    "sector_distribution": analyzer.get_sector_distribution() if hasattr(analyzer, 'get_sector_distribution') else None,
                    "risk_metrics": analyzer.get_risk_metrics() if hasattr(analyzer, 'get_risk_metrics') else None
                }
            except Exception as e:
                logger.warning(f"Portfolio analysis failed: {e}")
        
        return result
    
    def _tool_get_fundamentals(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get_fundamentals tool."""
        ticker = params.get("ticker", "")
        ticker_suffix = params.get("ticker_suffix", ".NS")
        
        full_ticker = f"{ticker}{ticker_suffix}"
        
        # Use the scoring pipeline's data fetcher
        if hasattr(self.pipeline, 'ensemble_scorer') and self.pipeline.ensemble_scorer:
            fetcher = self.pipeline.ensemble_scorer.financial_fetcher
        else:
            from finrag.scoring import FinancialDataFetcher
            fetcher = FinancialDataFetcher()
        
        data = fetcher.get_company_data(full_ticker)
        
        return {
            "ticker": ticker,
            "company_name": data.get("company_name", ticker),
            "metrics": {
                "market_cap": data.get("market_cap"),
                "pe_ratio": data.get("pe_ratio"),
                "pb_ratio": data.get("pb_ratio"),
                "roe": data.get("roe"),
                "debt_to_equity": data.get("debt_to_equity"),
                "revenue": data.get("revenue"),
                "profit_margin": data.get("profit_margin"),
                "dividend_yield": data.get("dividend_yield")
            },
            "price": {
                "current": data.get("current_price"),
                "52w_high": data.get("52w_high"),
                "52w_low": data.get("52w_low")
            },
            "data_completeness": data.get("data_completeness", 0)
        }
    
    def _tool_get_statistics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute get_statistics tool."""
        stats = self.pipeline.finrag.get_statistics()
        return stats
    
    def _tool_analyze_with_context(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute analyze_with_context tool (enhanced query)."""
        question = params.get("question", "")
        include_portfolio = params.get("include_portfolio", True)
        include_fundamentals = params.get("include_fundamentals", True)
        top_k = params.get("top_k", 0)  # Use 0 for tree_traversal mode
        
        # Use the pipeline's enhanced query (quiet=True to avoid duplicate output)
        result = self.pipeline.query_enhanced(
            question=question,
            method="tree_traversal",
            top_k=top_k,
            include_portfolio=include_portfolio,
            include_fundamentals=include_fundamentals,
            quiet=True
        )
        
        return {
            "answer": result.get("answer", ""),
            "intent": result.get("intent"),
            "tickers": result.get("tickers", []),
            "sources_used": result.get("sources_used", [])
        }
    
    # ================== Response Synthesis ==================
    
    def _synthesize_response(
        self, 
        query: str, 
        routing: RoutingDecision, 
        tool_results: List[ToolResult]
    ) -> str:
        """Synthesize tool results into a coherent response."""
        
        # If single tool with direct answer, extract it
        if len(tool_results) == 1 and tool_results[0].success:
            result = tool_results[0].result
            
            # For query tools, the answer is already synthesized
            if tool_results[0].tool_name in ["query_documents", "analyze_with_context"]:
                return result.get("answer", str(result))
        
        # For complex cases or multiple tools, use LLM to synthesize
        results_text = self._format_results_for_synthesis(tool_results)
        
        synthesis_prompt = f"""User Query: {query}

Tool Results:
{results_text}

Please synthesize these results into a clear, helpful response for the user."""
        
        response = self.client.chat.completions.create(
            model=self.config.synthesis_model,
            messages=[
                {"role": "system", "content": self.SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": synthesis_prompt}
            ],
            temperature=0.3,
            max_tokens=1000
        )
        
        return response.choices[0].message.content.strip()
    
    def _synthesize_response_with_usage(
        self, 
        query: str, 
        routing: RoutingDecision, 
        tool_results: List[ToolResult]
    ) -> Tuple[str, Optional[Dict[str, int]]]:
        """Synthesize tool results into a coherent response, returning usage info."""
        
        # If single tool with direct answer, extract it (no LLM call needed)
        if len(tool_results) == 1 and tool_results[0].success:
            result = tool_results[0].result
            
            # For query tools, the answer is already synthesized
            if tool_results[0].tool_name in ["query_documents", "analyze_with_context"]:
                return result.get("answer", str(result)), None
        
        # For complex cases or multiple tools, use LLM to synthesize
        results_text = self._format_results_for_synthesis(tool_results)
        
        synthesis_prompt = f"""User Query: {query}

Tool Results:
{results_text}

Please synthesize these results into a clear, helpful response for the user."""
        
        response = self.client.chat.completions.create(
            model=self.config.synthesis_model,
            messages=[
                {"role": "system", "content": self.SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": synthesis_prompt}
            ],
            temperature=0.3,
            max_tokens=1000
        )
        
        # Extract usage
        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
        
        return response.choices[0].message.content.strip(), usage
    
    def _format_results_for_synthesis(self, tool_results: List[ToolResult]) -> str:
        """Format tool results as text for the synthesis LLM."""
        parts = []
        
        for tr in tool_results:
            if tr.success:
                parts.append(f"**{tr.tool_name}** (success):\n{json.dumps(tr.result, indent=2)}")
            else:
                parts.append(f"**{tr.tool_name}** (failed): {tr.error}")
        
        return "\n\n".join(parts)
    
    def _fallback_response(self, query: str, error: str, start_time: float) -> OrchestratorResult:
        """Generate a fallback response using the default tool."""
        logger.info(f"Using fallback for query: {query[:50]}...")
        
        result = self._tool_query_documents({"question": query, "top_k": 0})
        
        return OrchestratorResult(
            answer=result.get("answer", "I couldn't process your request."),
            tools_used=[self.config.default_tool],
            tool_results=[ToolResult(
                tool_name=self.config.default_tool,
                success=True,
                result=result
            )],
            routing_decision=RoutingDecision(
                tools=[{"name": self.config.default_tool, "params": {"question": query}}],
                reasoning=f"Fallback due to error: {error}",
                confidence=0.5
            ),
            total_time=time.time() - start_time,
            success=True
        )
