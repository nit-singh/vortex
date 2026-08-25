"""Tool definitions and registry for the FinRAG orchestrator."""

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """Categories of tools for organization."""
    QUERY = "query"
    SCORING = "scoring"
    PORTFOLIO = "portfolio"
    DATA = "data"
    SYSTEM = "system"


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None


@dataclass
class Tool:
    """Definition of a tool that can be called by the orchestrator."""
    name: str
    description: str
    when_to_use: str
    category: ToolCategory
    parameters: List[ToolParameter]
    examples: List[str] = field(default_factory=list)
    
    def to_prompt_description(self) -> str:
        """Generate LLM-friendly description for routing prompt."""
        params_desc = []
        for p in self.parameters:
            req = "required" if p.required else f"optional, default={p.default}"
            enum_info = f", choices: {p.enum}" if p.enum else ""
            params_desc.append(f"    - {p.name} ({p.type}, {req}): {p.description}{enum_info}")
        
        params_str = "\n".join(params_desc) if params_desc else "    (no parameters)"
        examples_str = "\n".join(f'    - "{ex}"' for ex in self.examples[:3])
        
        return f"""**{self.name}**
  Description: {self.description}
  When to use: {self.when_to_use}
  Parameters:
{params_str}
  Example queries:
{examples_str}"""

    def to_schema(self) -> Dict[str, Any]:
        """Generate JSON schema for the tool."""
        properties = {}
        required = []
        
        for p in self.parameters:
            prop = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            if p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }


@dataclass
class ToolResult:
    """Result from executing a tool."""
    tool_name: str
    success: bool
    result: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time
        }


class ToolRegistry:
    """
    Registry of all available tools for the orchestrator.
    
    This defines WHAT tools exist and their schemas.
    The actual execution logic is in the orchestrator.
    """
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register all default FinRAG tools."""
        
        # Tool 1: Query Documents
        self.register(Tool(
            name="query_documents",
            description="Search annual reports and financial documents for information about companies. Returns relevant excerpts and synthesized answers.",
            when_to_use="User asks factual questions about a company's financials, revenue, strategy, management, risks, operations, or any information that would be in an annual report.",
            category=ToolCategory.QUERY,
            parameters=[
                ToolParameter(
                    name="question",
                    type="string",
                    description="The question to answer from the documents",
                    required=True
                ),
                ToolParameter(
                    name="retrieval_method",
                    type="string",
                    description="Method to retrieve documents",
                    required=False,
                    default="collapsed_tree",
                    enum=["collapsed_tree", "tree_traversal"]
                ),
                ToolParameter(
                    name="top_k",
                    type="integer",
                    description="Number of document chunks to retrieve",
                    required=False,
                    default=10
                ),
                ToolParameter(
                    name="filter_company",
                    type="string",
                    description="Filter results to a specific company name",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="filter_sector",
                    type="string",
                    description="Filter results to a specific sector",
                    required=False,
                    default=None
                )
            ],
            examples=[
                "What is TCS's revenue for 2024?",
                "Tell me about Infosys's digital transformation strategy",
                "What are the risk factors mentioned by Reliance?",
                "How did HDFC Bank perform last year?"
            ]
        ))
        
        # Tool 2: Score Stock - DISABLED (commented out to prevent orchestrator from using it)
        # This tool is disabled as per user request. Use query_documents instead for stock analysis.
        # self.register(Tool(
        #     name="score_stock",
        #     description="Generate a comprehensive investment score (0-100) for a stock using sentiment analysis, quantitative metrics, YoY trends, and LLM judgment. Provides buy/sell/hold recommendation.",
        #     when_to_use="User asks for investment advice, stock rating, outlook, whether to buy/sell a stock, or wants a comprehensive analysis of a stock's investment potential.",
        #     category=ToolCategory.SCORING,
        #     parameters=[
        #         ToolParameter(
        #             name="ticker",
        #             type="string",
        #             description="Stock ticker symbol (e.g., 'TCS', 'INFY', 'RELIANCE')",
        #             required=True
        #         ),
        #         ToolParameter(
        #             name="company_name",
        #             type="string",
        #             description="Full company name for better document matching",
        #             required=False,
        #             default=None
        #         ),
        #         ToolParameter(
        #             name="ticker_suffix",
        #             type="string",
        #             description="Exchange suffix (e.g., '.NS' for NSE, '.BO' for BSE)",
        #             required=False,
        #             default=".NS"
        #         )
        #     ],
        #     examples=[
        #         "Should I buy TCS stock?",
        #         "What's the outlook for Infosys?",
        #         "Rate HDFC Bank as an investment",
        #         "Is Reliance a good buy right now?",
        #         "Give me a score for Wipro stock"
        #     ]
        # ))
        
        # Tool 3: Compare Stocks
        self.register(Tool(
            name="compare_stocks",
            description="Compare two stocks side-by-side on multiple dimensions including financials, sentiment, risk, and investment scores.",
            when_to_use="User wants to compare two specific stocks, asks which is better, or uses 'vs' or 'compare' language.",
            category=ToolCategory.SCORING,
            parameters=[
                ToolParameter(
                    name="ticker1",
                    type="string",
                    description="First stock ticker symbol",
                    required=True
                ),
                ToolParameter(
                    name="ticker2",
                    type="string",
                    description="Second stock ticker symbol",
                    required=True
                ),
                ToolParameter(
                    name="company_name1",
                    type="string",
                    description="First company name",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="company_name2",
                    type="string",
                    description="Second company name",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="ticker_suffix",
                    type="string",
                    description="Exchange suffix for both tickers",
                    required=False,
                    default=".NS"
                )
            ],
            examples=[
                "Compare TCS vs Infosys",
                "Which is better: HDFC Bank or ICICI Bank?",
                "TCS or Wipro - which should I invest in?",
                "Compare Reliance and Tata Motors"
            ]
        ))
        
        # Tool 4: Get Portfolio Info
        self.register(Tool(
            name="get_portfolio",
            description="Get information about the user's investment portfolio including holdings, allocations, and summary statistics.",
            when_to_use="User asks about their portfolio, their holdings, what stocks they own, their allocation, or portfolio performance.",
            category=ToolCategory.PORTFOLIO,
            parameters=[
                ToolParameter(
                    name="ticker",
                    type="string",
                    description="Optional: Get info for a specific stock in portfolio",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="include_analysis",
                    type="boolean",
                    description="Include portfolio analysis (sector distribution, risk metrics)",
                    required=False,
                    default=True
                )
            ],
            examples=[
                "What stocks do I own?",
                "Show my portfolio",
                "What's my allocation in TCS?",
                "How is my portfolio distributed?",
                "Why do I own Hero MotoCorp?"
            ]
        ))
        
        # Tool 5: Get Fundamentals
        self.register(Tool(
            name="get_fundamentals",
            description="Get key financial metrics and fundamentals for a stock (P/E, P/B, ROE, market cap, revenue, etc.) from real-time market data.",
            when_to_use="User asks for specific financial metrics, ratios, or fundamental data about a stock.",
            category=ToolCategory.DATA,
            parameters=[
                ToolParameter(
                    name="ticker",
                    type="string",
                    description="Stock ticker symbol",
                    required=True
                ),
                ToolParameter(
                    name="ticker_suffix",
                    type="string",
                    description="Exchange suffix",
                    required=False,
                    default=".NS"
                )
            ],
            examples=[
                "What's TCS's P/E ratio?",
                "Show me Infosys fundamentals",
                "What's the market cap of Reliance?",
                "Give me HDFC Bank's financial metrics"
            ]
        ))
        
        # Tool 6: Get Tree Statistics
        self.register(Tool(
            name="get_statistics",
            description="Get statistics about the document index including number of documents, nodes, tree depth, and coverage.",
            when_to_use="User asks about what documents are indexed, how many companies are covered, or system status.",
            category=ToolCategory.SYSTEM,
            parameters=[],
            examples=[
                "What documents do you have?",
                "How many companies are indexed?",
                "What's the system status?",
                "Show me the index statistics"
            ]
        ))
        
        # Tool 7: Analyze Query (for complex multi-part queries)
        self.register(Tool(
            name="analyze_with_context",
            description="Answer complex queries that need multiple sources: annual reports + fundamentals + portfolio context combined.",
            when_to_use="User asks a complex question that requires combining information from documents, real-time data, AND portfolio - especially 'why' questions about portfolio holdings.",
            category=ToolCategory.QUERY,
            parameters=[
                ToolParameter(
                    name="question",
                    type="string",
                    description="The complex question to answer",
                    required=True
                ),
                ToolParameter(
                    name="include_portfolio",
                    type="boolean",
                    description="Include portfolio context",
                    required=False,
                    default=True
                ),
                ToolParameter(
                    name="include_fundamentals",
                    type="boolean",
                    description="Include real-time fundamental data",
                    required=False,
                    default=True
                ),
                ToolParameter(
                    name="top_k",
                    type="integer",
                    description="Number of document chunks to retrieve",
                    required=False,
                    default=10
                )
            ],
            examples=[
                "Why is Hero MotoCorp in my portfolio?",
                "How does my TCS holding compare to its recent performance?",
                "Should I increase my allocation in Infosys based on their latest report?",
                "Explain my portfolio's exposure to the IT sector"
            ]
        ))
    
    def register(self, tool: Tool) -> None:
        """Register a new tool."""
        self.tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")
    
    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self.tools.get(name)
    
    def list_tools(self) -> List[str]:
        """List all tool names."""
        return list(self.tools.keys())
    
    def get_all(self) -> List[Tool]:
        """Get all tools."""
        return list(self.tools.values())
    
    def get_by_category(self, category: ToolCategory) -> List[Tool]:
        """Get tools by category."""
        return [t for t in self.tools.values() if t.category == category]
    
    def generate_routing_prompt(self) -> str:
        """Generate the complete routing prompt with all tool descriptions."""
        tool_descriptions = "\n\n".join(
            tool.to_prompt_description() 
            for tool in self.tools.values()
        )
        return tool_descriptions
    
    def generate_tool_schemas(self) -> List[Dict[str, Any]]:
        """Generate JSON schemas for all tools (OpenAI function calling format)."""
        return [tool.to_schema() for tool in self.tools.values()]
