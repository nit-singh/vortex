#!/usr/bin/env python3
"""FinRAG Pathway MCP Server - Native Pathway implementation with LLM orchestration.

Usage: python pathway_mcp_server.py
"""

import os
import sys
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from finrag.utils import load_env_file
load_env_file()

import pathway as pw
from pathway.xpacks.llm.mcp_server import McpServable, McpServer, PathwayMcp

import pathway as pw
pw.set_license_key(os.getenv("PATHWAY_LICENSE_KEY"))

from main import FinRAGPipeline
from finrag.chat import ChatMemoryManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Schema Definitions

class EmptyRequestSchema(pw.Schema):
    pass


class QueryRequestSchema(pw.Schema):
    question: str
    method: Optional[str]
    top_k: Optional[int]


class ScoreStockRequestSchema(pw.Schema):
    ticker: str
    company_name: Optional[str]
    ticker_suffix: Optional[str]
    save_output: Optional[bool]


class UpdateTreeRequestSchema(pw.Schema):
    new_data_dir: Optional[str]


class EnhancedQueryRequestSchema(pw.Schema):
    question: str
    method: Optional[str]
    top_k: Optional[int]
    include_portfolio: Optional[bool]
    include_fundamentals: Optional[bool]


class CompareStocksRequestSchema(pw.Schema):
    ticker1: str
    ticker2: str
    company_name1: Optional[str]
    company_name2: Optional[str]
    ticker_suffix: Optional[str]


class BatchScoreRequestSchema(pw.Schema):
    tickers_json: str
    save_output: Optional[bool]
    output_file: Optional[str]


class ChatInteractiveRequestSchema(pw.Schema):
    question: str
    session_id: Optional[str]
    method: Optional[str]
    top_k: Optional[int]
    use_memory: Optional[bool]


class BuildTreeRequestSchema(pw.Schema):
    force_rebuild: Optional[bool]


class GetPortfolioRequestSchema(pw.Schema):
    ticker: Optional[str]
    include_analysis: Optional[bool]


class GetFundamentalsRequestSchema(pw.Schema):
    ticker: str
    ticker_suffix: Optional[str]


class ClearHistoryRequestSchema(pw.Schema):
    session_id: Optional[str]


class GetHistoryRequestSchema(pw.Schema):
    session_id: Optional[str]


# FinRAG Tools Implementation

class FinRAGTools(McpServable):
    """FinRAG tools exposed via Pathway MCP Server."""
    
    def __init__(self, tree_path: str = "finrag_tree", data_dir: str = "new_data"):
        """Initialize FinRAG pipeline and memory manager."""
        self.tree_path = tree_path
        self.data_dir = data_dir
        self._pipeline = None
        
        # Initialize chat memory manager (session-based conversation history)
        self.memory_manager = ChatMemoryManager(memory_size=5)
        
        logger.info(f"FinRAG MCP Tools initialized (tree: {tree_path}, data: {data_dir})")
    
    @property
    def pipeline(self) -> FinRAGPipeline:
        """Lazy load the FinRAG pipeline."""
        if self._pipeline is None:
            logger.info("Loading FinRAG pipeline...")
            self._pipeline = FinRAGPipeline(
                tree_path=self.tree_path,
                data_dir=self.data_dir
            )
            # Load existing tree if available
            tree_path_obj = Path(self.tree_path)
            if tree_path_obj.exists():
                logger.info(f"Loading existing tree from {self.tree_path}")
                self._pipeline.finrag.load(self.tree_path)
            else:
                logger.warning(f"No existing tree found at {self.tree_path}")
        return self._pipeline
    
    def chat_interactive(self, input_table: pw.Table) -> pw.Table:
        """
        Interactive chat with FinRAG that maintains conversation memory.
        
        This method:
        1. Retrieves last 5 conversation turns from memory for the session
        2. Formats them as context
        3. Queries FinRAG with the context
        4. Stores the new query-response pair in memory
        """
        
        @pw.udf
        def process_chat_interactive(question: str, session_id: str, method: str, 
                                      top_k: int, use_memory: bool) -> str:
            """UDF to process interactive chat with memory."""
            try:
                # Apply defaults
                session_id = session_id or "default"
                method = method or "collapsed_tree"
                top_k = top_k or 10
                use_memory = use_memory if use_memory is not None else True
                
                logger.info(f"Interactive chat: session={session_id}, question='{question[:50]}...'")
                
                # Step 1: Retrieve conversation history if memory is enabled
                memory_context = ""
                
                if use_memory:
                    memory_context = self.memory_manager.format_context(session_id)
                    if memory_context:
                        logger.info(f"Using {self.memory_manager.get_session_count(session_id)} previous turns as context")
                
                # Step 2: Prepare query for retrieval
                # Smart retrieval: use memory context only when appropriate
                retrieval_question = question
                
                # Check if question has pronouns that require context resolution
                pronoun_patterns = ['their', 'its', 'it ', 'they', 'them', 'this', 'that', 'these', 'those']
                question_lower = question.lower()
                has_pronoun = any(pattern in question_lower for pattern in pronoun_patterns)
                
                # Check if question explicitly mentions a company/entity (topic switch indicator)
                # Common company name patterns in financial context
                explicit_entity_keywords = [
                    'reliance', 'hero', 'infosys', 'tcs', 'hdfc', 'icici', 'tata', 'bajaj',
                    'moto', 'industries', 'ltd', 'limited', 'corporation', 'corp', 'about'
                ]
                mentions_explicit_entity = any(keyword in question_lower for keyword in explicit_entity_keywords)
                
                if has_pronoun and memory_context and use_memory and not mentions_explicit_entity:
                    # For pronoun questions WITHOUT explicit entity mention, use ONLY the most recent turn
                    # This ensures "their" refers to the most recent entity discussed, not older ones
                    # Example: After discussing Reliance, "Their revenue?" should refer to Reliance, not Hero
                    recent_turns = self.memory_manager.retrieve_last_n(session_id, n=1)  # Only last turn
                    if recent_turns:
                        # Format only the most recent turn for context
                        recent_context = self.memory_manager.format_context(session_id, max_turns=1)
                        if recent_context:
                            retrieval_question = f"{recent_context}\n\nCurrent question: {question}"
                            logger.info("Question contains pronouns - using MOST RECENT turn only (prevents old entity confusion)")
                        else:
                            # Fallback: use full context if format fails
                            retrieval_question = f"{memory_context}\n\nCurrent question: {question}"
                    else:
                        # No recent turns, use full context
                        retrieval_question = f"{memory_context}\n\nCurrent question: {question}"
                elif mentions_explicit_entity:
                    # Question mentions explicit entity (topic switch) - use question as-is
                    # This handles "What about Reliance?" or "Tell me about Reliance Industries"
                    retrieval_question = question
                    logger.info("Question mentions explicit entity - treating as topic switch, using question only")
                else:
                    # No pronouns, no explicit entity - use question as-is
                    retrieval_question = question
                
                # Step 3: Query FinRAG pipeline with appropriate question
                result = self.pipeline.query(retrieval_question, method, top_k)
                
                # Step 2b: If memory exists, enhance the answer with conversation context
                # This allows the LLM to understand references (like "their", "it") while 
                # keeping retrieval focused on current question
                if memory_context and use_memory and self.pipeline.finrag:
                    # Get the retrieved context from the result
                    retrieved_context = ""
                    
                    # Try to get context from retrieved nodes
                    if "retrieved_nodes" in result and result["retrieved_nodes"]:
                        retrieved_texts = [node.get("text", "") for node in result["retrieved_nodes"]]
                        retrieved_context = "\n\n".join(retrieved_texts)
                    
                    # If no context in nodes, try to get from result directly
                    if not retrieved_context and "context" in result:
                        retrieved_context = result["context"]
                    
                    # If we still don't have context, we need to get it from the retriever
                    if not retrieved_context:
                        # Re-retrieve to get context
                        retrieved_nodes = self.pipeline.finrag.retriever.retrieve(question, method, top_k)
                        if retrieved_nodes:
                            retrieved_texts = [node.text for node, score in retrieved_nodes]
                            retrieved_context = "\n\n".join(retrieved_texts[:5])  # Use top 5 nodes
                    
                    if retrieved_context:
                        # Combine memory context with retrieved context
                        enhanced_context = (
                            f"{memory_context}\n\n"
                            f"### Relevant Information Retrieved from Documents ###\n"
                            f"{retrieved_context}"
                        )
                        
                        # Re-answer with enhanced context that includes both memory and retrieved info
                        if hasattr(self.pipeline.finrag, 'qa_model'):
                            enhanced_answer = self.pipeline.finrag.qa_model.answer_question(
                                enhanced_context, 
                                question
                            )
                            result["answer"] = enhanced_answer.get("answer", result.get("answer", ""))
                            logger.debug("Enhanced answer with memory context")
                
                # Extract answer from result
                answer = result.get("answer", "No answer generated")
                
                # Step 3: Store conversation in memory
                if use_memory:
                    self.memory_manager.store(
                        session_id=session_id,
                        query=question,
                        response=answer
                    )
                    logger.debug(f"Stored conversation turn for session '{session_id}'")
                
                # Step 4: Format response
                response = {
                    "answer": answer,
                    "session_id": session_id,
                    "memory_used": use_memory and bool(memory_context),
                    "previous_turns": self.memory_manager.get_session_count(session_id) if use_memory else 0,
                    "retrieval_method": result.get("retrieval_method", method),
                    "nodes_retrieved": len(result.get("retrieved_nodes", [])),
                }
                
                # Include memory statistics if available
                if use_memory and memory_context:
                    response["memory_preview"] = memory_context[:200] + "..." if len(memory_context) > 200 else memory_context
                
                return json.dumps(response, indent=2)
                
            except Exception as e:
                logger.error(f"Error in chat_interactive: {e}", exc_info=True)
                return json.dumps({
                    "status": "error",
                    "message": f"Chat interactive failed: {str(e)}",
                    "session_id": session_id if 'session_id' in dir() else "default"
                }, indent=2)
        
        result_table = input_table.select(
            result=process_chat_interactive(
                pw.this.question,
                pw.this.session_id,
                pw.this.method,
                pw.this.top_k,
                pw.this.use_memory
            )
        )
        
        return result_table
    
    def query_documents(self, input_table: pw.Table) -> pw.Table:
        """Query the FinRAG document tree using RAPTOR and Pathway VectorStore."""
        
        @pw.udf
        def perform_query(question: str, method: str, top_k: int) -> str:
            """UDF to perform the actual query."""
            try:
                # Apply defaults
                method = method or "collapsed_tree"
                top_k = top_k or 10
                
                logger.info(f"Querying: {question}")
                result = self.pipeline.query(question, method, top_k)
                
                response = {
                    "answer": result.get("answer", "No answer generated"),
                    "retrieval_method": result.get("retrieval_method", method),
                    "nodes_retrieved": len(result.get("retrieved_nodes", [])),
                    "retrieved_nodes": result.get("retrieved_nodes", [])[:5]  # Top 5 nodes
                }
                
                return json.dumps(response, indent=2)
            except Exception as e:
                logger.error(f"Query error: {e}", exc_info=True)
                return json.dumps({"error": str(e)})
        
        # Process the input table and return result
        result_table = input_table.select(
            result=perform_query(pw.this.question, pw.this.method, pw.this.top_k)
        )
        
        return result_table
    
    def score_stock(self, input_table: pw.Table) -> pw.Table:
        """Score stock using ensemble financial analysis (0-100)."""
        
        @pw.udf
        def perform_scoring(ticker: str, company_name: Optional[str], 
                           ticker_suffix: str, save_output: bool) -> str:
            """UDF to perform stock scoring."""
            try:
                # Apply defaults
                ticker_suffix = ticker_suffix or ""
                save_output = save_output if save_output is not None else False
                
                logger.info(f"Scoring stock: {ticker}{ticker_suffix}")
                result = self.pipeline.score_stock(
                    ticker, company_name, ticker_suffix, save_output
                )
                
                if not result:
                    return json.dumps({"error": f"Failed to score {ticker}"})
                
                response = {
                    "ticker": result.get("ticker"),
                    "company_name": result.get("company_name"),
                    "final_score": result.get("score"),
                    "direction": result.get("direction"),
                    "confidence": result.get("confidence"),
                    "recommendation": result.get("recommendation"),
                    "component_scores": result.get("component_scores"),
                    "breakdown": result.get("breakdown")
                }
                
                return json.dumps(response, indent=2)
            except Exception as e:
                logger.error(f"Scoring error: {e}", exc_info=True)
                return json.dumps({"error": str(e)})
        
        result_table = input_table.select(
            result=perform_scoring(
                pw.this.ticker,
                pw.this.company_name,
                pw.this.ticker_suffix,
                pw.this.save_output
            )
        )
        
        return result_table
    
    def get_statistics(self, input_table: pw.Table) -> pw.Table:
        """Get RAPTOR tree statistics."""
        
        @pw.udf
        def fetch_statistics(dummy: Any) -> str:
            """UDF to fetch tree statistics."""
            try:
                logger.info("Retrieving tree statistics")
                stats = self.pipeline.finrag.get_statistics()
                return json.dumps(stats, indent=2)
            except Exception as e:
                logger.error(f"Statistics error: {e}", exc_info=True)
                return json.dumps({"error": str(e)})
        
        result_table = input_table.select(result=fetch_statistics(pw.this.id))
        return result_table
    
    def update_tree(self, input_table: pw.Table) -> pw.Table:
        """Incrementally update RAPTOR tree with new documents."""
        
        @pw.udf
        def perform_update(new_data_dir: str) -> str:
            """UDF to update the tree."""
            try:
                # Apply default
                new_data_dir = new_data_dir or "update_data"
                
                logger.info(f"Updating tree with documents from: {new_data_dir}")
                self.pipeline.update_tree(new_data_dir)
                stats = self.pipeline.finrag.get_statistics()
                
                response = {
                    "status": "success",
                    "message": f"Tree updated with documents from {new_data_dir}",
                    "statistics": stats
                }
                return json.dumps(response, indent=2)
            except Exception as e:
                logger.error(f"Update error: {e}", exc_info=True)
                return json.dumps({"status": "error", "message": str(e)})
        
        result_table = input_table.select(result=perform_update(pw.this.new_data_dir))
        return result_table
    
    def build_tree(self, input_table: pw.Table) -> pw.Table:
        """Build the initial RAPTOR tree from PDF documents."""
        
        @pw.udf
        def perform_build(force_rebuild: bool) -> str:
            """UDF to build the tree."""
            try:
                force_rebuild = force_rebuild if force_rebuild is not None else False
                
                logger.info(f"Building tree (force_rebuild={force_rebuild})")
                self.pipeline.build_tree(force_rebuild)
                stats = self.pipeline.finrag.get_statistics()
                
                response = {
                    "status": "success",
                    "message": "Tree built successfully",
                    "statistics": stats
                }
                return json.dumps(response, indent=2)
            except Exception as e:
                logger.error(f"Build error: {e}", exc_info=True)
                return json.dumps({"status": "error", "message": str(e)})
        
        result_table = input_table.select(result=perform_build(pw.this.force_rebuild))
        return result_table
    
    def query_enhanced(self, input_table: pw.Table) -> pw.Table:
        """Enhanced query with multi-source context (reports, fundamentals, portfolio)."""
        
        @pw.udf
        def perform_enhanced_query(question: str, method: str, top_k: int,
                                   include_portfolio: bool, include_fundamentals: bool) -> str:
            """UDF for enhanced query."""
            try:
                # Apply defaults
                method = method or "collapsed_tree"
                top_k = top_k or 10
                include_portfolio = True
                include_fundamentals = include_fundamentals if include_fundamentals is not None else True
                
                logger.info(f"Enhanced query: {question}")
                result = self.pipeline.query_enhanced(
                    question, method, top_k, include_portfolio, include_fundamentals
                )
                
                response = {
                    "answer": result.get("answer", "No answer generated"),
                    "query_analysis": {
                        "intent": result.get("intent"),
                        "tickers": result.get("tickers", []),
                        "sources_used": result.get("sources_used", [])
                    },
                    "retrieval_method": result.get("retrieval_method", method)
                }
                
                return json.dumps(response, indent=2)
            except Exception as e:
                logger.error(f"Enhanced query error: {e}", exc_info=True)
                return json.dumps({"error": str(e)})
        
        result_table = input_table.select(
            result=perform_enhanced_query(
                pw.this.question,
                pw.this.method,
                pw.this.top_k,
                pw.this.include_portfolio,
                pw.this.include_fundamentals
            )
        )
        
        return result_table
    
    def compare_stocks(self, input_table: pw.Table) -> pw.Table:
        """Compare two stocks side-by-side."""
        
        @pw.udf
        def perform_comparison(ticker1: str, ticker2: str, 
                              company_name1: Optional[str], company_name2: Optional[str],
                              ticker_suffix: str) -> str:
            """UDF for stock comparison."""
            try:
                # Apply default
                ticker_suffix = ticker_suffix or ""
                
                logger.info(f"Comparing stocks: {ticker1} vs {ticker2}")
                
                # Score both stocks
                score1 = self.pipeline.score_stock(
                    ticker1, company_name1, ticker_suffix, save_output=False
                )
                score2 = self.pipeline.score_stock(
                    ticker2, company_name2, ticker_suffix, save_output=False
                )
                
                comparison = {
                    "stock1": {
                        "ticker": ticker1,
                        "score": score1.get("score") if score1 else None,
                        "direction": score1.get("direction") if score1 else None,
                        "recommendation": score1.get("recommendation") if score1 else None,
                        "component_scores": score1.get("component_scores") if score1 else None
                    },
                    "stock2": {
                        "ticker": ticker2,
                        "score": score2.get("score") if score2 else None,
                        "direction": score2.get("direction") if score2 else None,
                        "recommendation": score2.get("recommendation") if score2 else None,
                        "component_scores": score2.get("component_scores") if score2 else None
                    },
                    "winner": ticker1 if (score1 and score2 and score1.get("score", 0) > score2.get("score", 0)) else ticker2,
                    "score_difference": abs(score1.get("score", 0) - score2.get("score", 0)) if (score1 and score2) else None
                }
                
                return json.dumps(comparison, indent=2)
            except Exception as e:
                logger.error(f"Comparison error: {e}", exc_info=True)
                return json.dumps({"error": str(e)})
        
        result_table = input_table.select(
            result=perform_comparison(
                pw.this.ticker1,
                pw.this.ticker2,
                pw.this.company_name1,
                pw.this.company_name2,
                pw.this.ticker_suffix
            )
        )
        
        return result_table
    
    def batch_score_stocks(self, input_table: pw.Table) -> pw.Table:
        """Score multiple stocks in batch."""
        
        @pw.udf
        def perform_batch_scoring(tickers_json: str, save_output: bool, output_file: str) -> str:
            """UDF for batch stock scoring."""
            try:
                # Apply defaults
                save_output = save_output if save_output is not None else True
                output_file = output_file or "batch_scores.json"
                
                # Parse tickers JSON
                tickers = json.loads(tickers_json)
                
                logger.info(f"Batch scoring {len(tickers)} stocks")
                batch_result = self.pipeline.batch_score_stocks(
                    tickers=tickers,
                    save_output=save_output,
                    output_file=output_file
                )
                
                return json.dumps(batch_result, indent=2)
            except Exception as e:
                logger.error(f"Batch scoring error: {e}", exc_info=True)
                return json.dumps({"error": str(e)})
        
        result_table = input_table.select(
            result=perform_batch_scoring(
                pw.this.tickers_json,
                pw.this.save_output,
                pw.this.output_file
            )
        )
        
        return result_table
    
    def get_portfolio(self, input_table: pw.Table) -> pw.Table:
        """Get portfolio information and analysis."""
        
        @pw.udf
        def fetch_portfolio(ticker: Optional[str], include_analysis: Optional[bool]) -> str:
            """UDF to fetch portfolio information."""
            try:
                include_analysis = include_analysis if include_analysis is not None else True
                portfolio_manager = self.pipeline.portfolio_manager
                
                if ticker:
                    # Get specific stock info
                    allocation = portfolio_manager.get_allocation_by_ticker(ticker)
                    if allocation:
                        response = {
                            "found": True,
                            "ticker": ticker,
                            "allocation": allocation
                        }
                    else:
                        response = {
                            "found": False,
                            "ticker": ticker,
                            "message": f"{ticker} is not in your portfolio"
                        }
                else:
                    # Get full portfolio
                    summary = portfolio_manager.get_portfolio_summary()
                    allocations = portfolio_manager.get_allocations()
                    
                    response = {
                        "summary": summary,
                        "holdings": allocations
                    }
                    
                    if include_analysis:
                        try:
                            analyzer = self.pipeline.portfolio_analyzer
                            response["analysis"] = {
                                "sector_distribution": analyzer.get_sector_distribution() if hasattr(analyzer, 'get_sector_distribution') else None,
                            }
                        except Exception as e:
                            logger.warning(f"Portfolio analysis failed: {e}")
                
                return json.dumps(response, indent=2)
            except Exception as e:
                logger.error(f"Portfolio error: {e}", exc_info=True)
                return json.dumps({"error": str(e)})
        
        result_table = input_table.select(
            result=fetch_portfolio(pw.this.ticker, pw.this.include_analysis)
        )
        
        return result_table
    
    def get_fundamentals(self, input_table: pw.Table) -> pw.Table:
        """Get financial metrics and fundamentals for a stock."""
        
        @pw.udf
        def fetch_fundamentals(ticker: str, ticker_suffix: Optional[str]) -> str:
            """UDF to fetch fundamental data."""
            try:
                ticker_suffix = ticker_suffix or ".NS"
                full_ticker = f"{ticker}{ticker_suffix}"
                
                # Use the scoring pipeline's data fetcher
                from finrag.scoring import FinancialDataFetcher
                fetcher = FinancialDataFetcher()
                data = fetcher.get_company_data(full_ticker)
                
                response = {
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
                
                return json.dumps(response, indent=2)
            except Exception as e:
                logger.error(f"Fundamentals error: {e}", exc_info=True)
                return json.dumps({"error": str(e)})
        
        result_table = input_table.select(
            result=fetch_fundamentals(pw.this.ticker, pw.this.ticker_suffix)
        )
        
        return result_table
    
    def clear_history(self, input_table: pw.Table) -> pw.Table:
        """Clear conversation history for a session."""
        
        @pw.udf
        def do_clear(session_id: str) -> str:
            """UDF to clear conversation history."""
            try:
                session_id = session_id or "default"
                self.memory_manager.clear_session(session_id)
                return json.dumps({
                    "success": True,
                    "message": f"Conversation history cleared for session '{session_id}'"
                })
            except Exception as e:
                logger.error(f"Clear history error: {e}")
                return json.dumps({"success": False, "error": str(e)})
        
        result_table = input_table.select(result=do_clear(pw.this.session_id))
        return result_table
    
    def get_history(self, input_table: pw.Table) -> pw.Table:
        """Get conversation history (last 5 turns) for a session."""
        
        @pw.udf
        def fetch_history(session_id: str) -> str:
            """UDF to fetch conversation history."""
            try:
                session_id = session_id or "default"
                session_count = self.memory_manager.get_session_count(session_id)
                
                if session_count > 0:
                    # Get all turns from memory manager
                    turns = self.memory_manager.retrieve_last_n(session_id, n=5)
                    history = []
                    for i, turn in enumerate(turns, 1):
                        history.append({
                            "turn": i,
                            "user": turn['query'][:200] + "..." if len(turn['query']) > 200 else turn['query'],
                            "assistant": turn['response'][:200] + "..." if len(turn['response']) > 200 else turn['response']
                        })
                    return json.dumps({
                        "session_id": session_id,
                        "turns": len(history),
                        "max_turns": 5,
                        "history": history
                    }, indent=2)
                else:
                    return json.dumps({
                        "session_id": session_id,
                        "turns": 0,
                        "max_turns": 5,
                        "history": [],
                        "message": "No conversation history yet"
                    })
            except Exception as e:
                logger.error(f"Get history error: {e}")
                return json.dumps({"error": str(e)})
        
        result_table = input_table.select(result=fetch_history(pw.this.session_id))
        return result_table
    
    def register_mcp(self, server: McpServer):
        """Register all FinRAG tools with the MCP server."""
        
        # Primary tool: Chat Interactive with conversation memory
        server.tool(
            "chat_interactive",
            request_handler=self.chat_interactive,
            schema=ChatInteractiveRequestSchema,
        )
        
        # Individual tools (can also be called directly)
        server.tool(
            "query_documents",
            request_handler=self.query_documents,
            schema=QueryRequestSchema,
        )
        
        server.tool(
            "score_stock",
            request_handler=self.score_stock,
            schema=ScoreStockRequestSchema,
        )
        
        server.tool(
            "compare_stocks",
            request_handler=self.compare_stocks,
            schema=CompareStocksRequestSchema,
        )
        
        server.tool(
            "get_portfolio",
            request_handler=self.get_portfolio,
            schema=GetPortfolioRequestSchema,
        )
        
        server.tool(
            "get_fundamentals",
            request_handler=self.get_fundamentals,
            schema=GetFundamentalsRequestSchema,
        )
        
        server.tool(
            "get_statistics",
            request_handler=self.get_statistics,
            schema=EmptyRequestSchema,
        )
        
        server.tool(
            "update_tree",
            request_handler=self.update_tree,
            schema=UpdateTreeRequestSchema,
        )
        
        server.tool(
            "build_tree",
            request_handler=self.build_tree,
            schema=BuildTreeRequestSchema,
        )
        
        server.tool(
            "query_enhanced",
            request_handler=self.query_enhanced,
            schema=EnhancedQueryRequestSchema,
        )
        
        server.tool(
            "batch_score_stocks",
            request_handler=self.batch_score_stocks,
            schema=BatchScoreRequestSchema,
        )
        
        server.tool(
            "clear_history",
            request_handler=self.clear_history,
            schema=ClearHistoryRequestSchema,
        )
        
        server.tool(
            "get_history",
            request_handler=self.get_history,
            schema=GetHistoryRequestSchema,
        )
        
        logger.info("All FinRAG tools registered with MCP server")
        logger.info("  - chat_interactive: Session-based chat with 5-turn memory")
        logger.info("  - clear_history, get_history: Manage conversation memory")
        logger.info("  - build_tree, update_tree: Manage RAPTOR tree")
        logger.info("  - query_documents, score_stock, compare_stocks, etc: Direct access")


def run_interactive_chat(tree_path: str = "finrag_tree", data_dir: str = "new_data"):
    """Run interactive chat mode in terminal."""
    print("\n" + "=" * 60)
    print("FINRAG INTERACTIVE CHAT (MCP Server Mode)")
    print("=" * 60)
    
    # Initialize FinRAG tools
    print("Loading FinRAG system...")
    finrag_tools = FinRAGTools(tree_path=tree_path, data_dir=data_dir)
    
    # Force load the pipeline
    _ = finrag_tools.pipeline
    print("System loaded with 5-turn conversation memory")
    
    session_id = "interactive"
    
    print("\nInteractive mode. Commands:")
    print("   'quit' or 'exit' - Exit chat")
    print("   'clear' - Clear conversation history")
    print("   'history' - Show conversation history")
    print("-" * 60)
    
    while True:
        try:
            mem_count = finrag_tools.memory_manager.get_session_count(session_id)
            mem_indicator = f"[{mem_count}/5]" if mem_count > 0 else ""
            user_input = input(f"\nYou {mem_indicator}: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\nGoodbye!")
                break
            if not user_input:
                continue
            
            if user_input.lower() == 'clear':
                finrag_tools.memory_manager.clear_session(session_id)
                print("Conversation history cleared.")
                continue
            
            if user_input.lower() == 'history':
                turns = finrag_tools.memory_manager.retrieve_last_n(session_id, n=5)
                if turns:
                    print("\nConversation History:")
                    print("-" * 40)
                    for i, turn in enumerate(turns, 1):
                        print(f"{i}. You: {turn['query'][:80]}{'...' if len(turn['query']) > 80 else ''}")
                        print(f"   Bot: {turn['response'][:80]}{'...' if len(turn['response']) > 80 else ''}")
                else:
                    print("No conversation history yet.")
                continue
            
            # Process message with memory context (simulating chat_interactive logic)
            import time
            start_time = time.time()
            
            # Get memory context
            memory_context = finrag_tools.memory_manager.format_context(session_id)
            
            # Query with or without context based on pronouns
            question_lower = user_input.lower()
            pronoun_patterns = ['their', 'its', 'it ', 'they', 'them', 'this', 'that', 'these', 'those']
            has_pronoun = any(pattern in question_lower for pattern in pronoun_patterns)
            
            if has_pronoun and memory_context:
                recent_context = finrag_tools.memory_manager.format_context(session_id, max_turns=1)
                if recent_context:
                    retrieval_question = f"{recent_context}\n\nCurrent question: {user_input}"
                else:
                    retrieval_question = user_input
            else:
                retrieval_question = user_input
            
            result = finrag_tools.pipeline.query(retrieval_question, "collapsed_tree", 10)
            answer = result.get("answer", "No answer generated")
            
            # Store in memory
            finrag_tools.memory_manager.store(
                session_id=session_id,
                query=user_input,
                response=answer
            )
            
            elapsed_time = time.time() - start_time
            
            print(f"\nAssistant: {answer}")
            print(f"\n   Time: {elapsed_time:.2f}s")
            print(f"   Memory: {finrag_tools.memory_manager.get_session_count(session_id)}/5 turns")
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")
            logger.error(f"Interactive chat error: {e}", exc_info=True)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="FinRAG Pathway MCP Server - Native Pathway implementation"
    )
    parser.add_argument(
        "--tree-path",
        type=str,
        default="finrag_tree",
        help="Path to the RAPTOR tree"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="new_data",
        help="Directory containing PDF documents"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="MCP server host"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8123,
        help="MCP server port"
    )
    parser.add_argument(
        "--transport",
        type=str,
        default="streamable-http",
        choices=["streamable-http", "stdio"],
        help="MCP transport type: streamable-http (for standalone) or stdio (for Claude Desktop)"
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run interactive chat mode instead of MCP server"
    )
    
    args = parser.parse_args()
    
    # Interactive chat mode
    if args.interactive:
        run_interactive_chat(args.tree_path, args.data_dir)
        return
    
    logger.info("="*60)
    logger.info("Starting FinRAG Pathway MCP Server")
    logger.info("="*60)
    logger.info(f"Tree path: {args.tree_path}")
    logger.info(f"Data directory: {args.data_dir}")
    logger.info(f"Transport: {args.transport}")
    if args.transport == "streamable-http":
        logger.info(f"Server: http://{args.host}:{args.port}/mcp/")
    else:
        logger.info("Using stdio transport for Claude Desktop")
    logger.info("="*60)
    
    # Initialize FinRAG tools
    finrag_tools = FinRAGTools(
        tree_path=args.tree_path,
        data_dir=args.data_dir
    )
    
    # Create Pathway MCP Server with appropriate transport
    if args.transport == "streamable-http":
        pathway_mcp_server = PathwayMcp(
            name="FinRAG Pathway MCP Server",
            transport="streamable-http",
            host=args.host,
            port=args.port,
            serve=[finrag_tools],
        )
    else:
        # stdio transport for Claude Desktop
        pathway_mcp_server = PathwayMcp(
            name="FinRAG Pathway MCP Server",
            transport="stdio",
            serve=[finrag_tools],
        )
    
    logger.info("Server initialized. Starting Pathway runtime...")
    logger.info("Use Ctrl+C to stop the server")
    
    # Run Pathway
    try:
        pw.run(
            monitoring_level=pw.MonitoringLevel.NONE,
            terminate_on_error=False,
        )
    except KeyboardInterrupt:
        logger.info("\nServer stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
