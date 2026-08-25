"""Intent Analyzer - Automatically detect query intent and requirements."""

import logging
from typing import Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


class QueryIntent(str, Enum):
    """Query intent categories."""
    PORTFOLIO_OVERVIEW = "portfolio_overview"
    ALLOCATION_RATIONALE = "allocation_rationale"
    STOCK_ANALYSIS = "stock_analysis"
    COMPARISON = "comparison"
    FUNDAMENTAL_QUERY = "fundamental_query"
    GENERAL_QUERY = "general_query"


class IntentAnalyzer:
    """
    Analyze user queries to determine intent and data requirements.
    
    Automatically detects:
    - What the user is asking for
    - Which data sources are needed
    - Whether portfolio context is required
    """
    
    def __init__(self):
        """Initialize intent analyzer with keyword patterns."""
        self.intent_patterns = self._build_intent_patterns()
    
    def _build_intent_patterns(self) -> Dict[QueryIntent, List[str]]:
        """Build keyword patterns for each intent."""
        return {
            QueryIntent.PORTFOLIO_OVERVIEW: [
                'portfolio', 'allocation', 'my stocks', 'my holdings',
                'what stocks', 'which stocks', 'show my', 'my investments',
                'distribution', 'breakdown', 'what do i have', 'what am i invested in'
            ],
            QueryIntent.ALLOCATION_RATIONALE: [
                'why', 'reason', 'rationale', 'why is', 'why did', 'why do',
                'why selected', 'why choose', 'why chosen', 'justification',
                'explain', 'selection', 'basis', 'criteria'
            ],
            QueryIntent.COMPARISON: [
                'compare', 'vs', 'versus', 'or', 'better', 'difference',
                'which is', 'between', 'comparison', 'vs.', 'and', 'versus'
            ],
            QueryIntent.FUNDAMENTAL_QUERY: [
                'revenue', 'profit', 'margin', 'ratio', 'earnings', 'pe',
                'financial', 'metrics', 'performance', 'growth', 'debt',
                'roe', 'roa', 'valuation', 'price', 'dividend'
            ],
            QueryIntent.STOCK_ANALYSIS: [
                'analyze', 'analysis', 'how is', 'performance', 'doing',
                'status', 'report', 'overview', 'about', 'tell me about',
                'information', 'details', 'latest'
            ]
        }
    
    def analyze_intent(
        self,
        query: str,
        has_tickers: bool = False,
        ticker_count: int = 0,
        is_portfolio_stock: bool = False
    ) -> Dict[str, Any]:
        """
        Analyze query to determine intent and requirements.
        
        Args:
            query: User query
            has_tickers: Whether tickers were extracted
            ticker_count: Number of tickers found
            is_portfolio_stock: Whether query mentions portfolio stock
            
        Returns:
            Dictionary with intent analysis
        """
        query_lower = query.lower()
        
        # Detect primary intent
        intent_scores = self._score_intents(query_lower)
        primary_intent = max(intent_scores.items(), key=lambda x: x[1])[0]
        
        # Special case: If multiple tickers, likely comparison
        if ticker_count >= 2:
            primary_intent = QueryIntent.COMPARISON
        
        # Special case: Portfolio-specific query
        if is_portfolio_stock and self._has_portfolio_keywords(query_lower):
            if primary_intent == QueryIntent.STOCK_ANALYSIS:
                primary_intent = QueryIntent.ALLOCATION_RATIONALE
        
        # Determine data source requirements
        requirements = self._determine_requirements(
            primary_intent,
            query_lower,
            has_tickers,
            is_portfolio_stock
        )
        
        return {
            'intent': primary_intent,
            'confidence': intent_scores[primary_intent],
            'requires_annual_reports': requirements['reports'],
            'requires_fundamentals': requirements['fundamentals'],
            'requires_portfolio': requirements['portfolio'],
            'is_multi_stock': ticker_count > 1
        }
    
    def _score_intents(self, query_lower: str) -> Dict[QueryIntent, float]:
        """
        Score each intent based on keyword presence.
        
        Args:
            query_lower: Lowercase query
            
        Returns:
            Dictionary mapping intents to scores
        """
        scores = {intent: 0.0 for intent in QueryIntent}
        
        for intent, keywords in self.intent_patterns.items():
            matches = sum(1 for keyword in keywords if keyword in query_lower)
            if matches > 0:
                scores[intent] = matches / len(keywords)
        
        # Default to general query if no matches
        if max(scores.values()) == 0:
            scores[QueryIntent.GENERAL_QUERY] = 1.0
        
        return scores
    
    def _determine_requirements(
        self,
        intent: QueryIntent,
        query_lower: str,
        has_tickers: bool,
        is_portfolio_stock: bool
    ) -> Dict[str, bool]:
        """
        Determine which data sources are needed.
        
        Args:
            intent: Detected intent
            query_lower: Lowercase query
            has_tickers: Whether tickers were extracted
            is_portfolio_stock: Whether portfolio stock mentioned
            
        Returns:
            Dictionary with data source requirements
        """
        requirements = {
            'reports': False,
            'fundamentals': False,
            'portfolio': False
        }
        
        # Portfolio overview queries
        if intent == QueryIntent.PORTFOLIO_OVERVIEW:
            requirements['portfolio'] = True
            requirements['fundamentals'] = True  # For context
            requirements['reports'] = False
        
        # Allocation rationale queries
        elif intent == QueryIntent.ALLOCATION_RATIONALE:
            requirements['portfolio'] = True
            requirements['fundamentals'] = True
            requirements['reports'] = True  # For detailed justification
        
        # Stock analysis queries
        elif intent == QueryIntent.STOCK_ANALYSIS:
            requirements['reports'] = True
            requirements['fundamentals'] = True
            if is_portfolio_stock:
                requirements['portfolio'] = True
        
        # Comparison queries
        elif intent == QueryIntent.COMPARISON:
            requirements['reports'] = True
            requirements['fundamentals'] = True
            if is_portfolio_stock:
                requirements['portfolio'] = True
        
        # Fundamental queries
        elif intent == QueryIntent.FUNDAMENTAL_QUERY:
            requirements['fundamentals'] = True  # Primary source
            requirements['reports'] = True  # Supporting context
            if is_portfolio_stock:
                requirements['portfolio'] = True
        
        # General queries
        else:
            requirements['reports'] = True
            if has_tickers:
                requirements['fundamentals'] = True
            if is_portfolio_stock:
                requirements['portfolio'] = True
        
        return requirements
    
    def _has_portfolio_keywords(self, query_lower: str) -> bool:
        """Check if query has portfolio-specific keywords."""
        portfolio_keywords = [
            'my', 'portfolio', 'allocation', 'invested', 'holding'
        ]
        return any(keyword in query_lower for keyword in portfolio_keywords)
    
    def get_intent_description(self, intent: QueryIntent) -> str:
        """
        Get human-readable description of intent.
        
        Args:
            intent: Query intent
            
        Returns:
            Description string
        """
        descriptions = {
            QueryIntent.PORTFOLIO_OVERVIEW: "User wants to see their portfolio overview",
            QueryIntent.ALLOCATION_RATIONALE: "User wants to know why a stock is in their portfolio",
            QueryIntent.STOCK_ANALYSIS: "User wants analysis of a specific stock",
            QueryIntent.COMPARISON: "User wants to compare multiple stocks",
            QueryIntent.FUNDAMENTAL_QUERY: "User wants specific financial metrics",
            QueryIntent.GENERAL_QUERY: "General query about financial documents"
        }
        return descriptions.get(intent, "Unknown intent")
