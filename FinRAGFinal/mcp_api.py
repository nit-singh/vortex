"""
FinRAG MCP Server HTTP API Wrapper

This module exposes FinRAG MCP server tools via HTTP REST API endpoints.
This is the PRIMARY way to interact with FinRAG from web dashboards.

The MCP server tools are accessed directly (not via stdio), allowing
for HTTP-based integration.

Usage:
    uvicorn mcp_api:app --host 0.0.0.0 --port 8002 --reload
"""

import sys
import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from finrag.utils import load_env_file
load_env_file()

from mcp_server import FinRAGMCPServer
from mcp.types import TextContent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global MCP server instance
mcp_server: Optional[FinRAGMCPServer] = None


# =============================================================================
# Request/Response Models
# =============================================================================

class ChatInteractiveRequest(BaseModel):
    """Request model for interactive chat endpoint."""
    question: str = Field(..., description="User's question or query")
    session_id: str = Field(default="default", description="Unique session identifier for conversation memory")
    method: str = Field(default="collapsed_tree", description="Retrieval method: tree_traversal or collapsed_tree")
    top_k: int = Field(default=10, description="Number of most relevant nodes to retrieve")
    use_memory: bool = Field(default=True, description="Whether to use conversation history as context")


class ChatInteractiveResponse(BaseModel):
    """Response model for interactive chat endpoint."""
    answer: str = Field(..., description="Generated answer")
    session_id: str = Field(..., description="Session identifier")
    memory_used: bool = Field(..., description="Whether previous conversations were used")
    previous_turns: int = Field(..., description="Number of previous conversation turns stored")
    retrieval_method: str = Field(..., description="Retrieval method used")
    nodes_retrieved: int = Field(..., description="Number of nodes retrieved")


class QueryRequest(BaseModel):
    """Request model for document query."""
    question: str = Field(..., description="Question to query documents")
    method: str = Field(default="collapsed_tree", description="Retrieval method")
    top_k: int = Field(default=10, description="Number of nodes to retrieve")


class QueryResponse(BaseModel):
    """Response model for document query."""
    answer: str = Field(..., description="Generated answer")
    retrieved_nodes: int = Field(..., description="Number of nodes retrieved")


# =============================================================================
# Lifecycle Management
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup MCP server."""
    global mcp_server
    
    logger.info("Starting FinRAG MCP HTTP API...")
    
    try:
        # Initialize MCP server (same as mcp_server.py but for HTTP access)
        tree_path = Path("finrag_tree")
        data_dir = Path("new_data")
        
        if not tree_path.exists():
            logger.error(f"Tree not found at {tree_path}. Please run main.py --mode build first.")
            raise RuntimeError("FinRAG tree not built. Run: python main.py --mode build")
        
        logger.info("Initializing FinRAG MCP Server...")
        mcp_server = FinRAGMCPServer(
            tree_path=str(tree_path),
            data_dir=str(data_dir)
        )
        logger.info("✓ FinRAG MCP Server initialized")
        logger.info("MCP API ready to serve requests!")
        
    except Exception as e:
        logger.error(f"Failed to initialize MCP server: {e}", exc_info=True)
        raise
    
    yield
    
    # Cleanup (if needed)
    logger.info("Shutting down MCP HTTP API...")


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="FinRAG MCP HTTP API",
    description="HTTP REST API wrapper for FinRAG MCP Server tools",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for web dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Helper Functions
# =============================================================================

def _parse_mcp_response(content: List[TextContent]) -> Dict[str, Any]:
    """Parse MCP TextContent response to dictionary."""
    if not content:
        return {"answer": "No response generated"}
    
    try:
        # Try to parse as JSON first
        text = content[0].text
        return json.loads(text)
    except (json.JSONDecodeError, AttributeError):
        # If not JSON, return as plain text
        return {"answer": content[0].text if content else "No response"}


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy" if mcp_server else "not_initialized",
        "service": "finrag_mcp_api",
        "mcp_server_ready": mcp_server is not None
    }


@app.post("/chat/interactive", response_model=ChatInteractiveResponse)
async def chat_interactive(request: ChatInteractiveRequest):
    """
    Interactive chat endpoint with session-based conversation memory.
    
    This endpoint calls the MCP server's chat_interactive tool.
    Perfect for web dashboards with multi-turn conversations.
    
    Args:
        request: ChatInteractiveRequest with question and session_id
        
    Returns:
        ChatInteractiveResponse with answer and memory metadata
        
    Example:
        ```
        POST /chat/interactive
        {
            "question": "What is Apple's revenue?",
            "session_id": "user123"
        }
        ```
    """
    if mcp_server is None:
        raise HTTPException(status_code=503, detail="MCP server not initialized")
    
    try:
        logger.info(f"Chat interactive request: session={request.session_id}, question='{request.question[:50]}...'")
        
        # Call MCP server's chat_interactive tool handler directly
        arguments = {
            "question": request.question,
            "session_id": request.session_id,
            "method": request.method,
            "top_k": request.top_k,
            "use_memory": request.use_memory
        }
        
        result = await mcp_server._handle_chat_interactive(arguments)
        response_data = _parse_mcp_response(result)
        
        # Extract fields from response
        answer = response_data.get("answer", "No answer generated")
        memory_used = response_data.get("memory_used", False)
        previous_turns = response_data.get("previous_turns", 0)
        retrieval_method = response_data.get("retrieval_method", request.method)
        nodes_retrieved = response_data.get("nodes_retrieved", 0)
        
        return ChatInteractiveResponse(
            answer=answer,
            session_id=request.session_id,
            memory_used=memory_used,
            previous_turns=previous_turns,
            retrieval_method=retrieval_method,
            nodes_retrieved=nodes_retrieved
        )
        
    except Exception as e:
        logger.error(f"Chat interactive error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat interactive failed: {str(e)}")


@app.post("/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    """
    Query documents endpoint.
    
    Calls the MCP server's query_documents tool.
    
    Args:
        request: QueryRequest with question and retrieval parameters
        
    Returns:
        QueryResponse with answer and retrieval metadata
    """
    if mcp_server is None:
        raise HTTPException(status_code=503, detail="MCP server not initialized")
    
    try:
        logger.info(f"Query request: question='{request.question[:50]}...'")
        
        arguments = {
            "question": request.question,
            "method": request.method,
            "top_k": request.top_k
        }
        
        result = await mcp_server._handle_query(arguments)
        response_data = _parse_mcp_response(result)
        
        answer = response_data.get("answer", "No answer generated")
        retrieved_nodes = response_data.get("retrieved_nodes", 0)
        
        return QueryResponse(
            answer=answer,
            retrieved_nodes=retrieved_nodes
        )
        
    except Exception as e:
        logger.error(f"Query error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@app.get("/tools")
async def list_tools():
    """
    List all available MCP server tools.
    
    Returns:
        List of available tools with descriptions
    """
    if mcp_server is None:
        raise HTTPException(status_code=503, detail="MCP server not initialized")
    
    try:
        # Get tools list from MCP server
        tools = await mcp_server.server.list_tools()
        return {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description
                }
                for tool in tools
            ]
        }
    except Exception as e:
        logger.error(f"List tools error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list tools: {str(e)}")


def run_server(host: str = "0.0.0.0", port: int = 8002):
    """Run the MCP HTTP API server."""
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="FinRAG MCP HTTP API Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8002, help="Port to bind to")
    
    args = parser.parse_args()
    
    logger.info(f"Starting FinRAG MCP HTTP API on {args.host}:{args.port}")
    run_server(host=args.host, port=args.port)

