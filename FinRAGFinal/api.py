"""
FinRAG API - FastAPI endpoints for querying and scoring

This module provides REST API endpoints for:
1. **Chat** - LLM-driven intelligent routing (NEW - RECOMMENDED)
2. Querying the FinRAG system
3. Scoring stocks using ensemble methods

Usage:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload
    
    # Or using the run script:
    python api.py
"""

import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from finrag.utils import load_env_file
load_env_file()

from finrag import FinRAG, FinRAGConfig
from finrag.vectorstore import PathwayConfig
from finrag.scoring import EnsembleScorer, ScoringConfig
from finrag.portfolio import PortfolioManager, PortfolioAnalyzer
from finrag.retrieval import TickerExtractor, IntentAnalyzer, MultiSourceRetriever, FundamentalDataCache
from finrag.orchestrator import FinRAGOrchestrator, OrchestratorConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Hardcoded list of all 97 tickers from tickers_allocation.csv
ALL_TICKERS = [
    {"ticker": "AARTIIND", "company_name": "Aarti Industries", "ticker_suffix": ".NS"},
    {"ticker": "ADANIENT", "company_name": "Adani Enterprises", "ticker_suffix": ".NS"},
    {"ticker": "APOLLOTYRE", "company_name": "Apollo Tyres", "ticker_suffix": ".NS"},
    {"ticker": "ASHOKLEY", "company_name": "Ashok Leyland", "ticker_suffix": ".NS"},
    {"ticker": "ASIANPAINT", "company_name": "Asian Paints", "ticker_suffix": ".NS"},
    {"ticker": "AUROPHARMA", "company_name": "Aurobindo Pharma", "ticker_suffix": ".NS"},
    {"ticker": "AXISBANK", "company_name": "Axis Bank", "ticker_suffix": ".NS"},
    {"ticker": "BAJFINANCE", "company_name": "Bajaj Finance", "ticker_suffix": ".NS"},
    {"ticker": "BATAINDIA", "company_name": "Bata India", "ticker_suffix": ".NS"},
    {"ticker": "BDL", "company_name": "Bharat Dynamics", "ticker_suffix": ".NS"},
    {"ticker": "BEML", "company_name": "BEML", "ticker_suffix": ".NS"},
    {"ticker": "BHARATFORG", "company_name": "Bharat Forge", "ticker_suffix": ".NS"},
    {"ticker": "BHARTIARTL", "company_name": "Bharti Airtel", "ticker_suffix": ".NS"},
    {"ticker": "BHEL", "company_name": "BHEL", "ticker_suffix": ".NS"},
    {"ticker": "BIOCON", "company_name": "Biocon", "ticker_suffix": ".NS"},
    {"ticker": "BPCL", "company_name": "BPCL", "ticker_suffix": ".NS"},
    {"ticker": "BRITANNIA", "company_name": "Britannia Industries", "ticker_suffix": ".NS"},
    {"ticker": "BSOFT", "company_name": "Birlasoft", "ticker_suffix": ".NS"},
    {"ticker": "CDSL", "company_name": "CDSL", "ticker_suffix": ".NS"},
    {"ticker": "CESC", "company_name": "CESC", "ticker_suffix": ".NS"},
    {"ticker": "CIPLA", "company_name": "Cipla", "ticker_suffix": ".NS"},
    {"ticker": "COALINDIA", "company_name": "Coal India", "ticker_suffix": ".NS"},
    {"ticker": "COFORGE", "company_name": "Coforge", "ticker_suffix": ".NS"},
    {"ticker": "CONCOR", "company_name": "Container Corporation", "ticker_suffix": ".NS"},
    {"ticker": "CUMMINSIND", "company_name": "Cummins India", "ticker_suffix": ".NS"},
    {"ticker": "DIXON", "company_name": "Dixon Technologies", "ticker_suffix": ".NS"},
    {"ticker": "DRREDDY", "company_name": "Dr Reddys Laboratories", "ticker_suffix": ".NS"},
    {"ticker": "EICHERMOT", "company_name": "Eicher Motors", "ticker_suffix": ".NS"},
    {"ticker": "GODREJPROP", "company_name": "Godrej Properties", "ticker_suffix": ".NS"},
    {"ticker": "GOLDBEES", "company_name": "Nippon India ETF Gold BeES", "ticker_suffix": ".NS"},
    {"ticker": "GRSE", "company_name": "Garden Reach Shipbuilders", "ticker_suffix": ".NS"},
    {"ticker": "HAVELLS", "company_name": "Havells India", "ticker_suffix": ".NS"},
    {"ticker": "HCLTECH", "company_name": "HCL Technologies", "ticker_suffix": ".NS"},
    {"ticker": "HDFCAMC", "company_name": "HDFC Asset Management", "ticker_suffix": ".NS"},
    {"ticker": "HDFCBANK", "company_name": "HDFC Bank", "ticker_suffix": ".NS"},
    {"ticker": "HEROMOTOCO", "company_name": "Hero MotoCorp", "ticker_suffix": ".NS"},
    {"ticker": "HINDALCO", "company_name": "Hindalco", "ticker_suffix": ".NS"},
    {"ticker": "HINDUNILVR", "company_name": "Hindustan Unilever", "ticker_suffix": ".NS"},
    {"ticker": "ICICIBANK", "company_name": "ICICI Bank", "ticker_suffix": ".NS"},
    {"ticker": "IDFCFIRSTB", "company_name": "IDFC First Bank", "ticker_suffix": ".NS"},
    {"ticker": "IEX", "company_name": "Indian Energy Exchange", "ticker_suffix": ".NS"},
    {"ticker": "IIFL", "company_name": "IIFL Finance", "ticker_suffix": ".NS"},
    {"ticker": "INDIGO", "company_name": "InterGlobe Aviation", "ticker_suffix": ".NS"},
    {"ticker": "INDUSTOWER", "company_name": "Indus Towers", "ticker_suffix": ".NS"},
    {"ticker": "INFY", "company_name": "Infosys", "ticker_suffix": ".NS"},
    {"ticker": "IRCON", "company_name": "Ircon International", "ticker_suffix": ".NS"},
    {"ticker": "ITC", "company_name": "ITC", "ticker_suffix": ".NS"},
    {"ticker": "JSWSTEEL", "company_name": "JSW Steel", "ticker_suffix": ".NS"},
    {"ticker": "KOTAKBANK", "company_name": "Kotak Mahindra Bank", "ticker_suffix": ".NS"},
    {"ticker": "LALPATHLAB", "company_name": "Dr Lal PathLabs", "ticker_suffix": ".NS"},
    {"ticker": "LAURUSLABS", "company_name": "Laurus Labs", "ticker_suffix": ".NS"},
    {"ticker": "LUPIN", "company_name": "Lupin", "ticker_suffix": ".NS"},
    {"ticker": "M&M", "company_name": "Mahindra & Mahindra", "ticker_suffix": ".NS"},
    {"ticker": "MANAPPURAM", "company_name": "Manappuram Finance", "ticker_suffix": ".NS"},
    {"ticker": "MARICO", "company_name": "Marico", "ticker_suffix": ".NS"},
    {"ticker": "MARUTI", "company_name": "Maruti Suzuki", "ticker_suffix": ".NS"},
    {"ticker": "MCX", "company_name": "MCX", "ticker_suffix": ".NS"},
    {"ticker": "MON100", "company_name": "Motilal Oswal Nasdaq 100 ETF", "ticker_suffix": ".NS"},
    {"ticker": "MPHASIS", "company_name": "Mphasis", "ticker_suffix": ".NS"},
    {"ticker": "MRF", "company_name": "MRF", "ticker_suffix": ".NS"},
    {"ticker": "MUTHOOTFIN", "company_name": "Muthoot Finance", "ticker_suffix": ".NS"},
    {"ticker": "NAVINFLUOR", "company_name": "Navin Fluorine", "ticker_suffix": ".NS"},
    {"ticker": "NESTLEIND", "company_name": "Nestle India", "ticker_suffix": ".NS"},
    {"ticker": "NIFTYBEES", "company_name": "Nippon India ETF Nifty BeES", "ticker_suffix": ".NS"},
    {"ticker": "OBEROIRLTY", "company_name": "Oberoi Realty", "ticker_suffix": ".NS"},
    {"ticker": "OIL", "company_name": "Oil India", "ticker_suffix": ".NS"},
    {"ticker": "ONGC", "company_name": "ONGC", "ticker_suffix": ".NS"},
    {"ticker": "PAGEIND", "company_name": "Page Industries", "ticker_suffix": ".NS"},
    {"ticker": "PERSISTENT", "company_name": "Persistent Systems", "ticker_suffix": ".NS"},
    {"ticker": "PIDILITIND", "company_name": "Pidilite Industries", "ticker_suffix": ".NS"},
    {"ticker": "PIIND", "company_name": "PI Industries", "ticker_suffix": ".NS"},
    {"ticker": "POLYCAB", "company_name": "Polycab India", "ticker_suffix": ".NS"},
    {"ticker": "POONAWALLA", "company_name": "Poonawalla Fincorp", "ticker_suffix": ".NS"},
    {"ticker": "PRESTIGE", "company_name": "Prestige Estates", "ticker_suffix": ".NS"},
    {"ticker": "RAYMOND", "company_name": "Raymond", "ticker_suffix": ".NS"},
    {"ticker": "RELIANCE", "company_name": "Reliance Industries", "ticker_suffix": ".NS"},
    {"ticker": "RITES", "company_name": "RITES", "ticker_suffix": ".NS"},
    {"ticker": "RVNL", "company_name": "Rail Vikas Nigam", "ticker_suffix": ".NS"},
    {"ticker": "SAIL", "company_name": "SAIL", "ticker_suffix": ".NS"},
    {"ticker": "SBIN", "company_name": "State Bank of India", "ticker_suffix": ".NS"},
    {"ticker": "SHREECEM", "company_name": "Shree Cement", "ticker_suffix": ".NS"},
    {"ticker": "SIEMENS", "company_name": "Siemens", "ticker_suffix": ".NS"},
    {"ticker": "SRF", "company_name": "SRF", "ticker_suffix": ".NS"},
    {"ticker": "SUNPHARMA", "company_name": "Sun Pharma", "ticker_suffix": ".NS"},
    {"ticker": "SUZLON", "company_name": "Suzlon Energy", "ticker_suffix": ".NS"},
    {"ticker": "TATACHEM", "company_name": "Tata Chemicals", "ticker_suffix": ".NS"},
    {"ticker": "TATACOMM", "company_name": "Tata Communications", "ticker_suffix": ".NS"},
    {"ticker": "TATAELXSI", "company_name": "Tata Elxsi", "ticker_suffix": ".NS"},
    {"ticker": "TATASTEEL", "company_name": "Tata Steel", "ticker_suffix": ".NS"},
    {"ticker": "TCS", "company_name": "TCS", "ticker_suffix": ".NS"},
    {"ticker": "TECHM", "company_name": "Tech Mahindra", "ticker_suffix": ".NS"},
    {"ticker": "TITAN", "company_name": "Titan", "ticker_suffix": ".NS"},
    {"ticker": "TRIDENT", "company_name": "Trident", "ticker_suffix": ".NS"},
    {"ticker": "TVSMOTOR", "company_name": "TVS Motor", "ticker_suffix": ".NS"},
    {"ticker": "VOLTAS", "company_name": "Voltas", "ticker_suffix": ".NS"},
    {"ticker": "WIPRO", "company_name": "Wipro", "ticker_suffix": ".NS"},
    {"ticker": "ZENSARTECH", "company_name": "Zensar Technologies", "ticker_suffix": ".NS"},
]

# Global variables for FinRAG system
finrag_system = None
ensemble_scorer = None
scoring_config = None
portfolio_manager = None
portfolio_analyzer = None
ticker_extractor = None
intent_analyzer = None
multi_source_retriever = None
fundamental_cache = None
finrag_orchestrator = None  # NEW: LLM orchestrator
finrag_pipeline = None  # NEW: Pipeline for orchestrator


# Pydantic models for request/response
class QueryRequest(BaseModel):
    """Request model for query endpoint."""
    question: str = Field(..., description="Question to ask the system", min_length=1)
    retrieval_method: Optional[str] = Field(
        "collapsed_tree",
        description="Retrieval method: 'tree_traversal' or 'collapsed_tree'"
    )
    top_k: Optional[int] = Field(10, description="Number of documents to retrieve", ge=1, le=50)


class QueryEnhancedRequest(BaseModel):
    """Request model for enhanced query endpoint with multi-source context."""
    question: str = Field(..., description="Question to ask the system", min_length=1)
    retrieval_method: Optional[str] = Field(
        "collapsed_tree",
        description="Retrieval method: 'tree_traversal' or 'collapsed_tree'"
    )
    top_k: Optional[int] = Field(10, description="Number of documents to retrieve", ge=1, le=50)
    include_portfolio: Optional[bool] = Field(True, description="Include portfolio context")
    include_fundamentals: Optional[bool] = Field(True, description="Include fundamental metrics")


class QueryResponse(BaseModel):
    """Response model for query endpoint."""
    answer: str = Field(..., description="Generated answer")
    question: str = Field(..., description="Original question")
    # retrieval_method: str = Field(..., description="Retrieval method used")
    # retrieved_nodes: List[Dict[str, Any]] = Field(..., description="Retrieved node metadata")
    success: bool = Field(True, description="Whether the query was successful")


class QueryEnhancedResponse(BaseModel):
    """Response model for enhanced query endpoint."""
    answer: str = Field(..., description="Generated answer")
    question: str = Field(..., description="Original question")
    intent: str = Field(..., description="Detected query intent")
    tickers: List[str] = Field(..., description="Extracted tickers")
    companies: List[str] = Field(..., description="Extracted company names")
    sources_used: List[str] = Field(..., description="Data sources used (annual_reports, fundamentals, portfolio)")
    success: bool = Field(True, description="Whether the query was successful")


class ScoreRequest(BaseModel):
    """Request model for scoring endpoint."""
    ticker: str = Field(..., description="Stock ticker symbol (e.g., AAPL, TCS)", min_length=1)
    company_name: Optional[str] = Field(None, description="Company name for RAG queries")
    ticker_suffix: Optional[str] = Field("", description="Ticker suffix (e.g., '.NS' for NSE)")
    save_output: Optional[bool] = Field(True, description="Whether to save the score to JSON file")


class ScoreResponse(BaseModel):
    """Response model for scoring endpoint."""
    ticker: str
    company_name: str
    score: float = Field(..., description="Final score (0-100)")
    direction: str = Field(..., description="Bullish, Bearish, or Neutral")
    confidence: float = Field(..., description="Confidence percentage (0-100)")
    recommendation: str = Field(..., description="Investment recommendation")
    time_horizon: str = Field(..., description="Recommended time horizon")
    component_scores: Dict[str, float] = Field(..., description="Individual component scores")
    breakdown: Dict[str, Any] = Field(..., description="Detailed breakdown")
    success: bool = Field(True, description="Whether scoring was successful")


class BatchScoreRequest(BaseModel):
    """Request model for batch scoring endpoint."""
    tickers: List[Dict[str, str]] = Field(
        ..., 
        description="List of ticker dictionaries with 'ticker', 'company_name', and optional 'ticker_suffix'",
        min_items=1
    )
    save_output: Optional[bool] = Field(True, description="Whether to save the batch results to JSON file")
    output_file: Optional[str] = Field("batch_scores.json", description="Output filename for batch results")


class BatchScoreResponse(BaseModel):
    """Response model for batch scoring endpoint."""
    timestamp: str = Field(..., description="Timestamp of batch scoring")
    summary: Dict[str, Any] = Field(..., description="Summary statistics of batch scoring")
    results: List[Dict[str, Any]] = Field(..., description="Individual stock scoring results")
    success: bool = Field(True, description="Whether batch scoring was successful")


class HealthResponse(BaseModel):
    """Response model for health check endpoint."""
    status: str
    system_loaded: bool
    scorer_initialized: bool
    orchestrator_ready: bool = False
    tree_stats: Optional[Dict[str, Any]] = None


# NEW: Chat models for LLM-driven orchestration
class ChatRequest(BaseModel):
    """Request model for the intelligent chat endpoint."""
    message: str = Field(..., description="User's natural language message", min_length=1)


class ChatResponse(BaseModel):
    """Response model for the chat endpoint."""
    answer: str = Field(..., description="Generated answer")
    tool_used: str = Field(..., description="Tools that were called to answer")
    tool_args: Optional[Dict[str, Any]] = Field(None, description="Arguments passed to tools")
    confidence: Optional[float] = Field(None, description="Routing confidence score")
    sources: Optional[List[str]] = Field(None, description="Source documents used")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata including timing and reasoning")


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources."""
    global finrag_system, ensemble_scorer, scoring_config
    global portfolio_manager, portfolio_analyzer, ticker_extractor
    global intent_analyzer, multi_source_retriever, fundamental_cache
    global finrag_orchestrator, finrag_pipeline
    
    logger.info("Starting FinRAG API...")
    
    # Initialize FinRAG system
    try:
        tree_path = Path("finrag_tree")
        if not tree_path.exists():
            logger.error(f"Tree not found at {tree_path}. Please run main.py --mode build first.")
            raise RuntimeError("FinRAG tree not built. Run: python main.py --mode build")
        
        logger.info("Loading FinRAG system...")
        config = FinRAGConfig()
        config.use_metadata_clustering = True
        config.verbose = False  # Reduce logging for API
        
        pathway_config = PathwayConfig(
            host="127.0.0.1",
            port=8754,
            dimension=1536,
            metric="cosine",
            index_type="usearch",
            enable_streaming=True
        )
        
        finrag_system = FinRAG(
            config=config,
            use_pathway=True,
            pathway_config=pathway_config
        )
        
        finrag_system.load(str(tree_path))
        logger.info("✓ FinRAG system loaded")
        
        # Initialize scoring components
        logger.info("Initializing ensemble scorer...")
        scoring_config = ScoringConfig()
        ensemble_scorer = EnsembleScorer(config=scoring_config)
        logger.info("✓ Ensemble scorer initialized")
        
        # Initialize portfolio and enhanced query components
        logger.info("Initializing portfolio and enhanced query components...")
        portfolio_manager = PortfolioManager("data/portfolio/portfolio.json")
        portfolio_manager.load_portfolio()
        portfolio_analyzer = PortfolioAnalyzer(portfolio_manager)
        ticker_extractor = TickerExtractor("data/mappings/ticker_mapping.json")
        intent_analyzer = IntentAnalyzer()
        fundamental_cache = FundamentalDataCache("data/fundamentals", ttl_hours=24)
        multi_source_retriever = MultiSourceRetriever(
            ticker_extractor=ticker_extractor,
            intent_analyzer=intent_analyzer,
            fundamental_cache=fundamental_cache,
            portfolio_manager=portfolio_manager,
            portfolio_analyzer=portfolio_analyzer
        )
        logger.info("✓ Enhanced query components initialized")
        
        # Initialize LLM Orchestrator with conversation memory
        logger.info("Initializing LLM Orchestrator with 5-turn memory...")
        from main import FinRAGPipeline
        finrag_pipeline = FinRAGPipeline(tree_path="finrag_tree", data_dir="new_data")
        finrag_pipeline.finrag = finrag_system  # Reuse already loaded system
        finrag_pipeline._portfolio_manager = portfolio_manager
        finrag_pipeline._portfolio_analyzer = portfolio_analyzer
        finrag_pipeline._ticker_extractor = ticker_extractor
        finrag_pipeline._intent_analyzer = intent_analyzer
        finrag_pipeline._fundamental_cache = fundamental_cache
        finrag_pipeline._multi_source_retriever = multi_source_retriever
        
        orchestrator_config = OrchestratorConfig(
            routing_model="gpt-4o-mini",
            synthesis_model="gpt-4o-mini",
            max_tools_per_query=3,
            fallback_on_error=True
        )
        finrag_orchestrator = FinRAGOrchestrator(
            pipeline=finrag_pipeline,
            config=orchestrator_config,
            memory_size=5  # Remember last 5 conversation turns
        )
        logger.info("✓ LLM Orchestrator initialized with conversation memory")
        
        logger.info("API ready to serve requests!")
        logger.info("  - /chat: LLM-driven intelligent routing with memory (RECOMMENDED)")
        logger.info("  - /query, /score, etc: Direct endpoints")
        
    except Exception as e:
        logger.error(f"Failed to initialize FinRAG: {e}")
        raise
    
    yield
    
    # Cleanup
    logger.info("Shutting down FinRAG API...")


# Create FastAPI app
app = FastAPI(
    title="FinRAG API",
    description="Financial RAG System with Pathway VectorStore - Query and Score Stocks",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint with API information."""
    return {
        "message": "FinRAG API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "chat": "/chat (intelligent routing with memory)",
            "chat_clear": "/chat/clear (clear conversation history)",
            "query": "/query",
            "query_enhanced": "/query_enhanced",
            "score": "/score",
            "batch_score": "/batch_score",
            "docs": "/docs"
        }
    }


@app.post("/chat/clear")
async def clear_chat_history():
    """Clear the conversation history for the chat endpoint."""
    if finrag_orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    finrag_orchestrator.clear_history()
    return {"message": "Conversation history cleared", "success": True}


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    system_loaded = finrag_system is not None
    scorer_initialized = ensemble_scorer is not None
    orchestrator_ready = finrag_orchestrator is not None
    
    tree_stats = None
    if system_loaded:
        try:
            tree_stats = finrag_system.get_statistics()
        except Exception as e:
            logger.error(f"Error getting tree stats: {e}")
    
    return HealthResponse(
        status="healthy" if (system_loaded and scorer_initialized and orchestrator_ready) else "unhealthy",
        system_loaded=system_loaded,
        scorer_initialized=scorer_initialized,
        orchestrator_ready=orchestrator_ready,
        tree_stats=tree_stats
    )


# =============================================================================
# Chat Endpoint (Intelligent LLM-Driven Routing)
# =============================================================================

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Intelligent chat endpoint with automatic tool routing.
    
    The LLM analyzes your query and automatically decides which tool to use:
    - query_documents: For document-based questions about companies
    - score_stock: For investment analysis and scoring
    - compare_stocks: For comparing multiple stocks
    - get_portfolio: For portfolio information
    - get_fundamentals: For company fundamental data
    - get_statistics: For system statistics
    
    Args:
        request: ChatRequest with your message
        
    Returns:
        ChatResponse with answer, tool used, and metadata
        
    Example:
        ```
        POST /chat
        {
            "message": "What are Apple's latest revenue numbers and growth trends?"
        }
        ```
    """
    if finrag_orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    try:
        logger.info(f"Chat request: {request.message}")
        
        # Run synchronous orchestrator in thread pool (with memory enabled)
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, 
            lambda: finrag_orchestrator.chat(request.message, use_memory=True)
        )
        
        # Extract sources from tool results if available
        sources = []
        if result.tool_results:
            for tr in result.tool_results:
                if tr.result and isinstance(tr.result, dict):
                    if "sources" in tr.result:
                        sources.extend(tr.result["sources"])
        
        return ChatResponse(
            answer=result.answer,
            tool_used=", ".join(result.tools_used) if result.tools_used else "none",
            tool_args=result.routing_decision.to_dict() if result.routing_decision else None,
            confidence=result.routing_decision.confidence if result.routing_decision else None,
            sources=sources if sources else None,
            metadata={
                "success": result.success,
                "total_time": result.total_time,
                "reasoning": result.routing_decision.reasoning if result.routing_decision else None,
                "error": result.error,
                "memory_turns": len(finrag_orchestrator.conversation_history)
            }
        )
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query", response_model=QueryResponse)
async def query_system(request: QueryRequest):
    """
    Query the FinRAG system with a question.
    
    Args:
        request: QueryRequest with question and optional parameters
        
    Returns:
        QueryResponse with answer and metadata
        
    Example:
        ```
        POST /query
        {
            "question": "What is Apple's latest revenue?",
            "retrieval_method": "collapsed_tree",
            "top_k": 10
        }
        ```
    """
    if finrag_system is None:
        raise HTTPException(status_code=503, detail="FinRAG system not initialized")
    
    try:
        logger.info(f"Query received: {request.question}")
        
        result = finrag_system.query(
            question=request.question,
            retrieval_method=request.retrieval_method,
            top_k=request.top_k
        )
        
        return QueryResponse(
            answer=result.get("answer", "No answer generated"),
            question=request.question,
            #retrieval_method=result.get("retrieval_method", request.retrieval_method),
            #retrieved_nodes=result.get("retrieved_nodes", []),
            success=True
        )
        
    except Exception as e:
        logger.error(f"Query error: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@app.post("/query_enhanced", response_model=QueryEnhancedResponse)
async def query_enhanced(request: QueryEnhancedRequest):
    """
    Enhanced query with multi-source context (annual reports + fundamentals + portfolio).
    
    Args:
        request: QueryEnhancedRequest with question and optional parameters
        
    Returns:
        QueryEnhancedResponse with answer, intent, tickers, and sources used
        
    Example:
        ```
        POST /query_enhanced
        {
            "question": "Why is Hero MotoCorp in my portfolio?",
            "top_k": 10,
            "include_portfolio": true,
            "include_fundamentals": true
        }
        ```
    """
    if finrag_system is None or multi_source_retriever is None:
        raise HTTPException(status_code=503, detail="Enhanced query system not initialized")
    
    try:
        logger.info(f"Enhanced query received: {request.question}")
        
        # Step 1: Analyze query
        query_analysis = multi_source_retriever.analyze_query(request.question)
        
        # Override source requirements based on parameters
        if not request.include_portfolio:
            query_analysis['requires_portfolio'] = False
        if not request.include_fundamentals:
            query_analysis['requires_fundamentals'] = False
        
        # Step 2: Retrieve context from multiple sources
        raptor_retriever = finrag_system.retriever if hasattr(finrag_system, 'retriever') else None
        
        context_result = multi_source_retriever.retrieve_context(
            query_analysis=query_analysis,
            raptor_retriever=raptor_retriever,
            top_k=request.top_k
        )
        
        # Step 3: Generate answer
        merged_context = context_result['merged_context']
        answer_result = finrag_system.qa_model.answer_question(merged_context, request.question)
        
        return QueryEnhancedResponse(
            answer=answer_result.get('answer', 'No answer generated'),
            question=request.question,
            intent=query_analysis['intent'],
            tickers=query_analysis['tickers'],
            companies=query_analysis['company_names'],
            sources_used=context_result['sources_used'],
            success=True
        )
        
    except Exception as e:
        logger.error(f"Enhanced query error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Enhanced query failed: {str(e)}")


@app.post("/score", response_model=ScoreResponse)
async def score_stock(request: ScoreRequest):
    """
    Score a stock using ensemble method.
    
    Args:
        request: ScoreRequest with ticker and optional company name
        
    Returns:
        ScoreResponse with comprehensive stock score
        
    Example:
        ```
        POST /score
        {
            "ticker": "AAPL",
            "company_name": "Apple Inc"
        }
        ```
        
        Indian stocks:
        ```
        POST /score
        {
            "ticker": "TCS",
            "company_name": "Tata Consultancy Services",
            "ticker_suffix": ".NS"
        }
        ```
    """
    if finrag_system is None or ensemble_scorer is None:
        raise HTTPException(status_code=503, detail="Scoring system not initialized")
    
    try:
        company_name = request.company_name or request.ticker
        logger.info(f"Scoring request: {request.ticker}{request.ticker_suffix} ({company_name})")
        
        result = ensemble_scorer.score_company(
            finrag=finrag_system,
            ticker=request.ticker,
            company_name=company_name,
            ticker_suffix=request.ticker_suffix
        )
        
        # Determine recommendation
        if result.direction == "bullish" and result.confidence > 70:
            recommendation = "STRONG BUY"
        elif result.direction == "bullish":
            recommendation = "BUY"
        elif result.direction == "neutral" and result.score > 50:
            recommendation = "HOLD (Slight Positive)"
        elif result.direction == "neutral":
            recommendation = "HOLD"
        elif result.direction == "bearish" and result.confidence > 70:
            recommendation = "STRONG SELL"
        else:
            recommendation = "SELL"
        
        # Save output to JSON if requested
        if request.save_output:
            try:
                output_dir = Path("output")
                output_dir.mkdir(exist_ok=True)
                output_file = output_dir / f"{request.ticker}_score.json"
                
                with open(output_file, 'w') as f:
                    f.write(result.to_json())
                
                logger.info(f"Results saved to: {output_file}")
            except Exception as e:
                logger.warning(f"Failed to save output: {e}")
        
        return ScoreResponse(
            ticker=request.ticker,
            company_name=company_name,
            score=result.score,
            direction=result.direction,
            confidence=result.confidence,
            recommendation=recommendation,
            time_horizon=result.time_horizon,
            component_scores={
                "sentiment": result.sentiment_score,
                "yoy_trends": result.yoy_trend_score,
                "risk_adjusted": result.risk_adjusted_score,
                "quantitative": result.quantitative_score,
                "llm_judge": result.llm_judge_score
            },
            breakdown=result.breakdown,
            success=True
        )
        
    except Exception as e:
        logger.error(f"Scoring error: {e}")
        raise HTTPException(status_code=500, detail=f"Scoring failed: {str(e)}")


@app.post("/batch_score", response_model=BatchScoreResponse)
async def batch_score_stocks(request: BatchScoreRequest):
    """
    Score multiple stocks in a single request.
    
    Args:
        request: BatchScoreRequest with list of tickers to score
        
    Returns:
        BatchScoreResponse with summary statistics and individual results
        
    Example:
        ```
        POST /batch_score
        {
            "tickers": [
                {"ticker": "AAPL", "company_name": "Apple Inc."},
                {"ticker": "TCS", "company_name": "Tata Consultancy Services", "ticker_suffix": ".NS"},
                {"ticker": "WIPRO", "company_name": "Wipro Limited", "ticker_suffix": ".NS"}
            ],
            "save_output": true,
            "output_file": "batch_scores.json"
        }
        ```
    """
    if finrag_system is None:
        raise HTTPException(status_code=503, detail="FinRAG system not initialized")
    
    try:
        logger.info(f"Batch scoring request for {len(request.tickers)} stocks")
        
        # Call the batch_score_stocks method from FinRAGPipeline
        batch_result = finrag_system.batch_score_stocks(
            tickers=request.tickers,
            save_output=request.save_output,
            output_file=request.output_file
        )
        
        return BatchScoreResponse(
            timestamp=batch_result["timestamp"],
            summary=batch_result["summary"],
            results=batch_result["results"],
            success=True
        )
        
    except Exception as e:
        logger.error(f"Batch scoring error: {e}")
        raise HTTPException(status_code=500, detail=f"Batch scoring failed: {str(e)}")


@app.post("/batch_score_all", response_model=BatchScoreResponse)
async def batch_score_all_stocks(
    save_output: Optional[bool] = Query(True, description="Whether to save the batch results to JSON file"),
    output_file: Optional[str] = Query("all_stocks_scores.json", description="Output filename for batch results")
):
    """
    Score all 97 hardcoded stocks in a single request (no user input needed).
    
    Uses the predefined list of NSE stocks from tickers_allocation.csv.
    
    Returns:
        BatchScoreResponse with summary statistics and individual results
        
    Example:
        POST /batch_score_all
        POST /batch_score_all?save_output=true&output_file=my_scores.json
    """
    if finrag_system is None:
        raise HTTPException(status_code=503, detail="FinRAG system not initialized")
    
    try:
        logger.info(f"Batch scoring ALL {len(ALL_TICKERS)} stocks from hardcoded list")
        
        # Call the batch_score_stocks method with hardcoded tickers
        batch_result = finrag_system.batch_score_stocks(
            tickers=ALL_TICKERS,
            save_output=save_output,
            output_file=output_file
        )
        
        return BatchScoreResponse(
            timestamp=batch_result["timestamp"],
            summary=batch_result["summary"],
            results=batch_result["results"],
            success=True
        )
        
    except Exception as e:
        logger.error(f"Batch scoring error: {e}")
        raise HTTPException(status_code=500, detail=f"Batch scoring failed: {str(e)}")


@app.get("/tickers", response_model=Dict[str, Any])
async def get_all_tickers():
    """
    Get the list of all 97 hardcoded tickers available for scoring.
    
    Returns:
        Dictionary with count and list of all available tickers
    """
    return {
        "count": len(ALL_TICKERS),
        "tickers": ALL_TICKERS
    }


@app.get("/query", response_model=QueryResponse)
async def query_system_get(
    question: str = Query(..., description="Question to ask"),
    retrieval_method: str = Query("collapsed_tree", description="Retrieval method"),
    top_k: int = Query(10, ge=1, le=50, description="Number of documents to retrieve")
):
    """
    Query endpoint with GET method (alternative to POST).
    
    Example:
        GET /query?question=What%20is%20Apple%27s%20revenue&top_k=10
    """
    request = QueryRequest(
        question=question,
        retrieval_method=retrieval_method,
        top_k=top_k
    )
    return await query_system(request)


@app.get("/query_enhanced", response_model=QueryEnhancedResponse)
async def query_enhanced_get(
    question: str = Query(..., description="Question to ask"),
    retrieval_method: str = Query("collapsed_tree", description="Retrieval method"),
    top_k: int = Query(10, ge=1, le=50, description="Number of documents to retrieve"),
    include_portfolio: bool = Query(True, description="Include portfolio context"),
    include_fundamentals: bool = Query(True, description="Include fundamental metrics")
):
    """
    Enhanced query endpoint with GET method (alternative to POST).
    
    Example:
        GET /query_enhanced?question=Why%20is%20Hero%20MotoCorp%20in%20my%20portfolio?
        GET /query_enhanced?question=What%20are%20my%20stocks?&include_fundamentals=true
    """
    request = QueryEnhancedRequest(
        question=question,
        retrieval_method=retrieval_method,
        top_k=top_k,
        include_portfolio=include_portfolio,
        include_fundamentals=include_fundamentals
    )
    return await query_enhanced(request)


@app.get("/score", response_model=ScoreResponse)
async def score_stock_get(
    ticker: str = Query(..., description="Stock ticker symbol"),
    company_name: Optional[str] = Query(None, description="Company name"),
    ticker_suffix: str = Query("", description="Ticker suffix"),
    save_output: bool = Query(True, description="Save score to JSON file")
):
    """
    Score endpoint with GET method (alternative to POST).
    
    Example:
        GET /score?ticker=AAPL&company_name=Apple
        GET /score?ticker=TCS&ticker_suffix=.NS&save_output=true
    """
    request = ScoreRequest(
        ticker=ticker,
        company_name=company_name,
        ticker_suffix=ticker_suffix,
        save_output=save_output
    )
    return await score_stock(request)


def run_interactive_chat():
    """Run interactive chat mode in terminal."""
    import asyncio
    
    print("\n" + "=" * 60)
    print("🤖 FINRAG INTERACTIVE CHAT (API Mode)")
    print("=" * 60)
    print("Loading FinRAG system...")
    
    # Initialize components synchronously for CLI
    from finrag import FinRAG, FinRAGConfig
    from finrag.vectorstore import PathwayConfig
    from finrag.orchestrator import FinRAGOrchestrator, OrchestratorConfig
    from main import FinRAGPipeline
    
    tree_path = Path("finrag_tree")
    if not tree_path.exists():
        print("❌ Error: Tree not found. Run: python main.py --mode build")
        return
    
    config = FinRAGConfig()
    pathway_config = PathwayConfig(
        host="127.0.0.1", port=8754, dimension=1536,
        metric="cosine", index_type="usearch", enable_streaming=True
    )
    
    finrag = FinRAG(config=config, use_pathway=True, pathway_config=pathway_config)
    finrag.load(str(tree_path))
    print("✓ FinRAG system loaded")
    
    # Initialize pipeline and orchestrator
    pipeline = FinRAGPipeline(tree_path="finrag_tree", data_dir="new_data")
    pipeline.finrag = finrag
    
    orchestrator_config = OrchestratorConfig(
        routing_model="gpt-4o-mini",
        synthesis_model="gpt-4o-mini",
        max_tools_per_query=3,
        fallback_on_error=True
    )
    orchestrator = FinRAGOrchestrator(
        pipeline=pipeline,
        config=orchestrator_config,
        memory_size=5
    )
    print("✓ Orchestrator ready with 5-turn memory")
    
    print("\n💬 Interactive mode. Commands:")
    print("   'quit' or 'exit' - Exit chat")
    print("   'clear' - Clear conversation history")
    print("   'history' - Show conversation history")
    print("-" * 60)
    
    while True:
        try:
            mem_count = len(orchestrator.conversation_history)
            mem_indicator = f"[💾 {mem_count}/5]" if mem_count > 0 else ""
            user_input = input(f"\n📝 You {mem_indicator}: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\n👋 Goodbye!")
                break
            if not user_input:
                continue
            
            if user_input.lower() == 'clear':
                orchestrator.clear_history()
                print("🗑️  Conversation history cleared.")
                continue
            
            if user_input.lower() == 'history':
                if orchestrator.conversation_history:
                    print("\n📜 Conversation History:")
                    print("-" * 40)
                    for i, turn in enumerate(orchestrator.conversation_history, 1):
                        print(f"{i}. You: {turn['user'][:80]}{'...' if len(turn['user']) > 80 else ''}")
                        print(f"   Bot: {turn['assistant'][:80]}{'...' if len(turn['assistant']) > 80 else ''}")
                else:
                    print("📜 No conversation history yet.")
                continue
            
            # Process message
            result = orchestrator.chat(user_input, use_memory=True)
            
            print(f"\n🤖 Assistant: {result.answer}")
            print(f"\n   📊 Tools: {', '.join(result.tools_used)}")
            print(f"   ⏱️  Time: {result.total_time:.2f}s")
            print(f"   💾 Memory: {len(orchestrator.conversation_history)}/5 turns")
            
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")


def main():
    """Run the API server or interactive chat."""
    import argparse
    
    parser = argparse.ArgumentParser(description="FinRAG API Server")
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run interactive chat mode instead of API server"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="API server host"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="API server port"
    )
    
    args = parser.parse_args()
    
    if args.interactive:
        run_interactive_chat()
    else:
        uvicorn.run(
            "api:app",
            host=args.host,
            port=args.port,
            reload=True,
            log_level="info"
        )


if __name__ == "__main__":
    main()
