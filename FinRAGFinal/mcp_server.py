"""
FinRAG MCP Server - Model Context Protocol Server for FinRAG

This MCP server exposes FinRAG capabilities to AI assistants (like Claude)
via the Model Context Protocol, allowing direct interaction with:
- Document querying
- Stock scoring
- Tree updates
- Statistics and resources

Usage:
    python mcp_server.py

Configuration for Claude Desktop:
    Add to ~/.config/Claude/claude_desktop_config.json (Linux/Mac)
    or %APPDATA%\Claude\claude_desktop_config.json (Windows):
    
    {
      "mcpServers": {
        "finrag": {
          "command": "python",
          "args": ["path/to/mcp_server.py"],
          "env": {
            "OPENAI_API_KEY": "your-key-here"
          }
        }
      }
    }
"""

import sys
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from finrag.utils import load_env_file
load_env_file()

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    Resource,
)

from main import FinRAGPipeline
from finrag.chat import ChatMemoryManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FinRAGMCPServer:
    """
    MCP Server for FinRAG - Exposes FinRAG capabilities via Model Context Protocol.
    
    This server provides:
    - Tools: Actions AI assistants can take (query, score, update)
    - Resources: Data AI assistants can access (tree structure, statistics)
    - Prompts: Reusable prompt templates for common tasks
    """
    
    def __init__(self, tree_path: str = "finrag_tree", data_dir: str = "new_data"):
        """
        Initialize the MCP server with FinRAG pipeline.
        
        Args:
            tree_path: Path to the RAPTOR tree
            data_dir: Directory containing PDF documents
        """
        self.server = Server("finrag-mcp-server")
        self.tree_path = tree_path
        self.data_dir = data_dir
        
        # Lazy load pipeline (only when needed)
        self._pipeline = None
        
        # Initialize chat memory manager (session-based conversation history)
        self.memory_manager = ChatMemoryManager(memory_size=5)
        
        # Register handlers
        self._register_tools()
        self._register_resources()
        self._register_prompts()
        
        logger.info("FinRAG MCP Server initialized")
    
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
    
    def _register_tools(self):
        """Register FinRAG tools with MCP server."""
        
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            """List all available FinRAG tools."""
            return [
                Tool(
                    name="query_documents",
                    description=(
                        "Query the FinRAG document tree for information. "
                        "Uses hierarchical RAPTOR tree with Pathway VectorStore "
                        "for semantic similarity search across financial documents."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The question to ask about the financial documents"
                            },
                            "method": {
                                "type": "string",
                                "enum": ["tree_traversal", "collapsed_tree"],
                                "default": "collapsed_tree",
                                "description": "Retrieval method: tree_traversal (level-by-level) or collapsed_tree (all nodes)"
                            },
                            "top_k": {
                                "type": "integer",
                                "default": 10,
                                "description": "Number of most relevant nodes to retrieve"
                            }
                        },
                        "required": ["question"]
                    }
                ),
                Tool(
                    name="score_stock",
                    description=(
                        "Score a stock using ensemble financial analysis. "
                        "Combines sentiment analysis, YoY trends, risk assessment, "
                        "quantitative metrics, and LLM judge to produce a comprehensive "
                        "investment score (0-100) with direction (bullish/bearish/neutral)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ticker": {
                                "type": "string",
                                "description": "Stock ticker symbol (e.g., AAPL, MSFT, HEROMOTOCO)"
                            },
                            "company_name": {
                                "type": "string",
                                "description": "Company name for RAG queries (optional, defaults to ticker)"
                            },
                            "ticker_suffix": {
                                "type": "string",
                                "default": "",
                                "description": "Exchange suffix (e.g., .NS for NSE India, .BO for BSE)"
                            },
                            "save_output": {
                                "type": "boolean",
                                "default": False,
                                "description": "Whether to save the score to output/ folder"
                            }
                        },
                        "required": ["ticker"]
                    }
                ),
                Tool(
                    name="update_tree",
                    description=(
                        "Incrementally update the RAPTOR tree with new PDF documents. "
                        "This adds new documents to the existing tree structure without "
                        "rebuilding from scratch. New embeddings are created only for "
                        "new documents, making this much faster than full rebuild."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "new_data_dir": {
                                "type": "string",
                                "default": "update_data",
                                "description": "Directory containing new PDF files to add"
                            }
                        }
                    }
                ),
                Tool(
                    name="get_statistics",
                    description=(
                        "Get current statistics about the RAPTOR tree structure, "
                        "including total nodes, leaf nodes, tree depth, and node "
                        "distribution across levels."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                Tool(
                    name="build_tree",
                    description=(
                        "Build the initial RAPTOR tree from PDF documents. "
                        "This creates the hierarchical tree structure with embeddings. "
                        "Only use this for initial setup or complete rebuild."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "force_rebuild": {
                                "type": "boolean",
                                "default": False,
                                "description": "Force rebuild even if tree exists"
                            }
                        }
                    }
                ),
                Tool(
                    name="query_enhanced",
                    description=(
                        "Enhanced query with multi-source context. Automatically extracts tickers, "
                        "detects query intent, and retrieves context from multiple sources: "
                        "annual reports (RAPTOR tree), fundamental metrics (yfinance), and "
                        "portfolio allocations. Ideal for investment analysis questions."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "Question about stocks, portfolio, or financial analysis"
                            },
                            "method": {
                                "type": "string",
                                "enum": ["tree_traversal", "collapsed_tree"],
                                "default": "collapsed_tree",
                                "description": "Retrieval method for annual reports"
                            },
                            "top_k": {
                                "type": "integer",
                                "default": 10,
                                "description": "Number of nodes to retrieve from RAPTOR tree"
                            },
                            "include_portfolio": {
                                "type": "boolean",
                                "default": True,
                                "description": "Include portfolio context if available"
                            },
                            "include_fundamentals": {
                                "type": "boolean",
                                "default": True,
                                "description": "Include fundamental metrics from yfinance"
                            }
                        },
                        "required": ["question"]
                    }
                ),
                Tool(
                    name="compare_stocks",
                    description=(
                        "Compare two stocks side-by-side using document queries and "
                        "ensemble scoring. Returns detailed comparison of financial "
                        "metrics, sentiment, and investment recommendations."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ticker1": {
                                "type": "string",
                                "description": "First stock ticker symbol"
                            },
                            "ticker2": {
                                "type": "string",
                                "description": "Second stock ticker symbol"
                            },
                            "company_name1": {
                                "type": "string",
                                "description": "First company name (optional)"
                            },
                            "company_name2": {
                                "type": "string",
                                "description": "Second company name (optional)"
                            },
                            "ticker_suffix": {
                                "type": "string",
                                "default": "",
                                "description": "Exchange suffix for both stocks"
                            }
                        },
                        "required": ["ticker1", "ticker2"]
                    }
                ),
                Tool(
                    name="chat_interactive",
                    description=(
                        "Interactive chat with FinRAG that maintains conversation memory. "
                        "This tool remembers the last 5 query-response pairs from previous "
                        "conversations and uses them as context for answering new questions. "
                        "Perfect for multi-turn conversations where follow-up questions "
                        "reference previous answers."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The user's question or query"
                            },
                            "session_id": {
                                "type": "string",
                                "default": "default",
                                "description": "Unique session identifier for conversation memory (default: 'default')"
                            },
                            "method": {
                                "type": "string",
                                "enum": ["tree_traversal", "collapsed_tree"],
                                "default": "collapsed_tree",
                                "description": "Retrieval method for document search"
                            },
                            "top_k": {
                                "type": "integer",
                                "default": 10,
                                "description": "Number of most relevant nodes to retrieve"
                            },
                            "use_memory": {
                                "type": "boolean",
                                "default": True,
                                "description": "Whether to use conversation history as context"
                            }
                        },
                        "required": ["question"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """Handle tool calls from AI assistants."""
            logger.info(f"Tool called: {name} with arguments: {arguments}")
            
            try:
                if name == "query_documents":
                    return await self._handle_query(arguments)
                
                elif name == "score_stock":
                    return await self._handle_score(arguments)
                
                elif name == "update_tree":
                    return await self._handle_update(arguments)
                
                elif name == "get_statistics":
                    return await self._handle_statistics(arguments)
                
                elif name == "build_tree":
                    return await self._handle_build(arguments)
                
                elif name == "query_enhanced":
                    return await self._handle_query_enhanced(arguments)
                
                elif name == "compare_stocks":
                    return await self._handle_compare(arguments)
                
                elif name == "chat_interactive":
                    return await self._handle_chat_interactive(arguments)
                
                else:
                    raise ValueError(f"Unknown tool: {name}")
            
            except Exception as e:
                logger.error(f"Error handling tool {name}: {e}", exc_info=True)
                return [TextContent(
                    type="text",
                    text=f"Error: {str(e)}"
                )]
    
    async def _handle_query(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle query_documents tool call."""
        question = args["question"]
        method = args.get("method", "collapsed_tree")
        top_k = args.get("top_k", 10)
        
        logger.info(f"Querying: {question}")
        result = self.pipeline.query(question, method, top_k)
        
        # Format response
        response = {
            "answer": result.get("answer", "No answer generated"),
            "retrieval_method": result.get("retrieval_method", method),
            "nodes_retrieved": len(result.get("retrieved_nodes", [])),
            "retrieved_nodes": result.get("retrieved_nodes", [])
        }
        
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]
    
    async def _handle_score(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle score_stock tool call."""
        ticker = args["ticker"]
        company_name = args.get("company_name")
        ticker_suffix = args.get("ticker_suffix", "")
        save_output = args.get("save_output", False)
        
        logger.info(f"Scoring stock: {ticker}{ticker_suffix}")
        result = self.pipeline.score_stock(
            ticker, company_name, ticker_suffix, save_output
        )
        
        if not result:
            return [TextContent(
                type="text",
                text=f"Error: Failed to score {ticker}"
            )]
        
        # Format response
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
        
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]
    
    async def _handle_update(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle update_tree tool call."""
        new_data_dir = args.get("new_data_dir", "update_data")
        
        logger.info(f"Updating tree with documents from: {new_data_dir}")
        
        try:
            self.pipeline.update_tree(new_data_dir)
            stats = self.pipeline.finrag.get_statistics()
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": f"Tree updated with documents from {new_data_dir}",
                    "statistics": stats
                }, indent=2)
            )]
        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                }, indent=2)
            )]
    
    async def _handle_statistics(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle get_statistics tool call."""
        logger.info("Retrieving tree statistics")
        stats = self.pipeline.finrag.get_statistics()
        
        return [TextContent(
            type="text",
            text=json.dumps(stats, indent=2)
        )]
    
    async def _handle_build(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle build_tree tool call."""
        force_rebuild = args.get("force_rebuild", False)
        
        logger.info(f"Building tree (force_rebuild={force_rebuild})")
        
        try:
            self.pipeline.build_tree(force_rebuild)
            stats = self.pipeline.finrag.get_statistics()
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": "Tree built successfully",
                    "statistics": stats
                }, indent=2)
            )]
        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                }, indent=2)
            )]
    
    async def _handle_query_enhanced(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle query_enhanced tool call."""
        question = args["question"]
        method = args.get("method", "collapsed_tree")
        top_k = args.get("top_k", 10)
        include_portfolio = args.get("include_portfolio", True)
        include_fundamentals = args.get("include_fundamentals", True)
        
        logger.info(f"Enhanced query: {question}")
        result = self.pipeline.query_enhanced(
            question, method, top_k, include_portfolio, include_fundamentals
        )
        
        # Format response
        response = {
            "answer": result.get("answer", "No answer generated"),
            "query_analysis": {
                "intent": result.get("intent"),
                "tickers": result.get("tickers", []),
                "sources_used": result.get("sources_used", [])
            },
            "retrieval_method": result.get("retrieval_method", method)
        }
        
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]
    
    async def _handle_chat_interactive(self, args: Dict[str, Any]) -> List[TextContent]:
        """
        Handle chat_interactive tool call with conversation memory.
        
        This method:
        1. Retrieves last 5 conversation turns from memory for the session
        2. Formats them as context
        3. Queries FinRAG with the context
        4. Stores the new query-response pair in memory
        """
        question = args["question"]
        session_id = args.get("session_id", "default")
        method = args.get("method", "collapsed_tree")
        top_k = args.get("top_k", 10)
        use_memory = args.get("use_memory", True)
        
        logger.info(f"Interactive chat: session={session_id}, question='{question[:50]}...'")
        
        try:
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
            result = self.pipeline.query(retrieval_question, method, top_k, quiet=True)
            
            # Step 2b: If memory exists, enhance the answer with conversation context
            # This allows the LLM to understand references (like "their", "it") while 
            # keeping retrieval focused on current question
            if memory_context and use_memory and self.pipeline.finrag:
                # Get the retrieved context from the result
                # The context might be in the result or we need to reconstruct it
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
            
            return [TextContent(
                type="text",
                text=json.dumps(response, indent=2)
            )]
            
        except Exception as e:
            logger.error(f"Error in chat_interactive: {e}", exc_info=True)
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": f"Chat interactive failed: {str(e)}",
                    "session_id": session_id
                }, indent=2)
            )]
    
    async def _handle_compare(self, args: Dict[str, Any]) -> List[TextContent]:
        """Handle compare_stocks tool call."""
        ticker1 = args["ticker1"]
        ticker2 = args["ticker2"]
        company_name1 = args.get("company_name1")
        company_name2 = args.get("company_name2")
        ticker_suffix = args.get("ticker_suffix", "")
        
        logger.info(f"Comparing stocks: {ticker1} vs {ticker2}")
        
        # Score both stocks
        score1 = self.pipeline.score_stock(
            ticker1, company_name1, ticker_suffix, save_output=False
        )
        score2 = self.pipeline.score_stock(
            ticker2, company_name2, ticker_suffix, save_output=False
        )
        
        # Compare
        comparison = {
            "stock1": {
                "ticker": ticker1,
                "score": score1.get("score"),
                "direction": score1.get("direction"),
                "recommendation": score1.get("recommendation"),
                "component_scores": score1.get("component_scores")
            },
            "stock2": {
                "ticker": ticker2,
                "score": score2.get("score"),
                "direction": score2.get("direction"),
                "recommendation": score2.get("recommendation"),
                "component_scores": score2.get("component_scores")
            },
            "winner": ticker1 if score1.get("score", 0) > score2.get("score", 0) else ticker2,
            "score_difference": abs(score1.get("score", 0) - score2.get("score", 0))
        }
        
        return [TextContent(
            type="text",
            text=json.dumps(comparison, indent=2)
        )]
    
    def _register_resources(self):
        """Register FinRAG resources with MCP server."""
        
        @self.server.list_resources()
        async def list_resources() -> List[Resource]:
            """List all available FinRAG resources."""
            return [
                Resource(
                    uri="finrag://tree/structure",
                    name="RAPTOR Tree Structure",
                    description="Hierarchical document tree structure with node counts per level",
                    mimeType="application/json"
                ),
                Resource(
                    uri="finrag://tree/statistics",
                    name="Tree Statistics",
                    description="Current tree statistics including total nodes, leaves, depth",
                    mimeType="application/json"
                ),
                Resource(
                    uri="finrag://config/pathway",
                    name="Pathway Configuration",
                    description="Pathway VectorStore configuration settings",
                    mimeType="application/json"
                ),
                Resource(
                    uri="finrag://cache/status",
                    name="Cache Status",
                    description="Status of document parsing cache",
                    mimeType="application/json"
                )
            ]
        
        @self.server.read_resource()
        async def read_resource(uri: str) -> str:
            """Read a specific FinRAG resource."""
            logger.info(f"Reading resource: {uri}")
            
            if uri == "finrag://tree/structure":
                stats = self.pipeline.finrag.get_statistics()
                structure = {
                    "total_nodes": stats.get("total_nodes", 0),
                    "leaf_nodes": stats.get("leaf_nodes", 0),
                    "root_nodes": stats.get("root_nodes", 0),
                    "tree_depth": stats.get("tree_depth", 0),
                    "levels": stats.get("levels", {})
                }
                return json.dumps(structure, indent=2)
            
            elif uri == "finrag://tree/statistics":
                stats = self.pipeline.finrag.get_statistics()
                return json.dumps(stats, indent=2)
            
            elif uri == "finrag://config/pathway":
                config = {
                    "host": self.pipeline.pathway_config.host,
                    "port": self.pipeline.pathway_config.port,
                    "dimension": self.pipeline.pathway_config.dimension,
                    "metric": self.pipeline.pathway_config.metric,
                    "index_type": self.pipeline.pathway_config.index_type,
                    "enable_streaming": self.pipeline.pathway_config.enable_streaming
                }
                return json.dumps(config, indent=2)
            
            elif uri == "finrag://cache/status":
                cache_dir = Path("cache") / "parsed_docs"
                cached_files = list(cache_dir.glob("*.txt")) if cache_dir.exists() else []
                status = {
                    "cache_directory": str(cache_dir),
                    "cached_documents": len(cached_files),
                    "cache_files": [f.name for f in cached_files[:10]]  # First 10
                }
                return json.dumps(status, indent=2)
            
            raise ValueError(f"Unknown resource: {uri}")
    
    def _register_prompts(self):
        """Register reusable prompt templates."""
        
        @self.server.list_prompts()
        async def list_prompts() -> List[Dict[str, Any]]:
            """List all available prompt templates."""
            return [
                {
                    "name": "analyze_company",
                    "description": "Comprehensive company analysis with query and scoring",
                    "arguments": [
                        {"name": "ticker", "description": "Stock ticker", "required": True},
                        {"name": "company_name", "description": "Company name", "required": False}
                    ]
                },
                {
                    "name": "investment_recommendation",
                    "description": "Get investment recommendation with detailed analysis",
                    "arguments": [
                        {"name": "ticker", "description": "Stock ticker", "required": True}
                    ]
                },
                {
                    "name": "compare_for_investment",
                    "description": "Compare two stocks and recommend which to invest in",
                    "arguments": [
                        {"name": "ticker1", "description": "First stock ticker", "required": True},
                        {"name": "ticker2", "description": "Second stock ticker", "required": True}
                    ]
                }
            ]
        
        @self.server.get_prompt()
        async def get_prompt(name: str, arguments: Dict[str, str]) -> str:
            """Get a specific prompt template with filled arguments."""
            
            if name == "analyze_company":
                ticker = arguments["ticker"]
                company_name = arguments.get("company_name", ticker)
                return f"""Perform a comprehensive analysis of {company_name} ({ticker}):

1. Query the financial documents for:
   - Recent financial performance
   - Revenue and profit trends
   - Risk factors
   - Growth strategy

2. Score the stock using ensemble method

3. Provide investment recommendation with reasoning

Use the query_documents and score_stock tools."""
            
            elif name == "investment_recommendation":
                ticker = arguments["ticker"]
                return f"""Analyze {ticker} and provide investment recommendation:

1. Score the stock
2. Query for key financial metrics
3. Evaluate risks and opportunities
4. Provide clear BUY/HOLD/SELL recommendation with confidence level

Use score_stock and query_documents tools."""
            
            elif name == "compare_for_investment":
                ticker1 = arguments["ticker1"]
                ticker2 = arguments["ticker2"]
                return f"""Compare {ticker1} vs {ticker2} for investment decision:

1. Score both stocks
2. Compare financial metrics from documents
3. Analyze relative strengths and weaknesses
4. Recommend which stock to invest in with reasoning

Use compare_stocks and query_documents tools."""
            
            raise ValueError(f"Unknown prompt: {name}")
    
    async def run(self):
        """Run the MCP server."""
        logger.info("Starting FinRAG MCP Server...")
        logger.info(f"Tree path: {self.tree_path}")
        logger.info(f"Data directory: {self.data_dir}")
        
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


async def main():
    """Main entry point for MCP server."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="FinRAG MCP Server - Model Context Protocol interface for FinRAG"
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
    
    args = parser.parse_args()
    
    server = FinRAGMCPServer(
        tree_path=args.tree_path,
        data_dir=args.data_dir
    )
    
    await server.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)
