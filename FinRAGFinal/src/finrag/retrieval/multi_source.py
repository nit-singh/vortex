"""Multi-Source Retriever - Retrieve context from multiple sources."""

import logging
from typing import Dict, Any, List, Optional
from .intent_analyzer import IntentAnalyzer, QueryIntent
from .ticker_extractor import TickerExtractor
from .fundamental_cache import FundamentalDataCache

logger = logging.getLogger(__name__)


class MultiSourceRetriever:
    """
    Retrieve context from multiple sources based on query intent.
    
    Sources:
    1. Annual Reports (RAPTOR tree)
    2. Fundamental Analysis (cached scoring data)
    3. Portfolio Allocations (user portfolio)
    """
    
    def __init__(
        self,
        ticker_extractor: TickerExtractor,
        intent_analyzer: IntentAnalyzer,
        fundamental_cache: FundamentalDataCache,
        portfolio_manager: Any = None,
        portfolio_analyzer: Any = None
    ):
        """
        Initialize multi-source retriever.
        
        Args:
            ticker_extractor: Ticker extraction component
            intent_analyzer: Intent analysis component
            fundamental_cache: Fundamental data cache
            portfolio_manager: Portfolio manager instance
            portfolio_analyzer: Portfolio analyzer instance
        """
        self.ticker_extractor = ticker_extractor
        self.intent_analyzer = intent_analyzer
        self.fundamental_cache = fundamental_cache
        self.portfolio_manager = portfolio_manager
        self.portfolio_analyzer = portfolio_analyzer
    
    def analyze_query(
        self,
        query: str
    ) -> Dict[str, Any]:
        """
        Analyze query to extract tickers and determine intent.
        
        Args:
            query: User query
            
        Returns:
            Analysis results with tickers and intent
        """
        # Get portfolio context if available
        portfolio_tickers = []
        if self.portfolio_manager:
            portfolio_tickers = self.portfolio_manager.get_tickers()
        
        # Extract tickers
        ticker_results = self.ticker_extractor.extract_tickers(
            query,
            portfolio_tickers=portfolio_tickers
        )
        
        # Check if tickers are in portfolio
        is_portfolio_stock = False
        if self.portfolio_manager and ticker_results['has_tickers']:
            is_portfolio_stock = any(
                self.portfolio_manager.is_in_portfolio(t)
                for t in ticker_results['tickers']
            )
        
        # Analyze intent
        intent_results = self.intent_analyzer.analyze_intent(
            query=query,
            has_tickers=ticker_results['has_tickers'],
            ticker_count=len(ticker_results['tickers']),
            is_portfolio_stock=is_portfolio_stock
        )
        
        return {
            'query': query,
            'tickers': ticker_results['tickers'],
            'company_names': ticker_results['company_names'],
            'ticker_confidence': ticker_results['confidence_scores'],
            'ticker_methods': ticker_results['methods'],
            'intent': intent_results['intent'],
            'intent_confidence': intent_results['confidence'],
            'requires_annual_reports': intent_results['requires_annual_reports'],
            'requires_fundamentals': intent_results['requires_fundamentals'],
            'requires_portfolio': intent_results['requires_portfolio'],
            'is_portfolio_stock': is_portfolio_stock,
            'is_multi_stock': intent_results['is_multi_stock']
        }
    
    def retrieve_context(
        self,
        query_analysis: Dict[str, Any],
        raptor_retriever: Any = None,
        top_k: int = 10,
        retrieval_method: str = "collapsed_tree"
    ) -> Dict[str, Any]:
        """
        Retrieve context from all required sources.
        
        Args:
            query_analysis: Output from analyze_query()
            raptor_retriever: FinRAG retriever for annual reports
            top_k: Number of documents to retrieve from RAPTOR
            retrieval_method: Method for RAPTOR retrieval ("collapsed_tree" or "tree_traversal")
            
        Returns:
            Dictionary with context from all sources
        """
        context = {
            'annual_reports': None,
            'fundamentals': {},
            'portfolio': None,
            'sources_used': []
        }
        
        query = query_analysis['query']
        tickers = query_analysis['tickers']
        intent = query_analysis['intent']
        
        # 1. Retrieve from annual reports (RAPTOR tree)
        if query_analysis['requires_annual_reports'] and raptor_retriever:
            logger.info("Retrieving context from annual reports...")
            context['annual_reports'] = self._retrieve_from_raptor(
                query=query,
                tickers=tickers,
                raptor_retriever=raptor_retriever,
                top_k=top_k,
                retrieval_method=retrieval_method
            )
            if context['annual_reports']:
                context['sources_used'].append('annual_reports')
        
        # Retrieve fundamentals
        if query_analysis['requires_fundamentals'] and tickers:
            logger.info(f"Retrieving fundamental data for {len(tickers)} tickers...")
            for ticker in tickers:
                fundamental_data = self._retrieve_fundamentals(ticker, generate_if_missing=True)
                if fundamental_data:
                    context['fundamentals'][ticker] = fundamental_data
            if context['fundamentals']:
                context['sources_used'].append('fundamentals')
        
        # 3. Retrieve portfolio context
        if query_analysis['requires_portfolio']:
            logger.info("Retrieving portfolio context...")
            context['portfolio'] = self._retrieve_portfolio_context(
                query_analysis=query_analysis
            )
            if context['portfolio']:
                context['sources_used'].append('portfolio')
        
        # Merge context based on intent priority
        merged_context = self._merge_context(
            context=context,
            intent=intent,
            tickers=tickers
        )
        
        return {
            'merged_context': merged_context,
            'context_sources': context,
            'sources_used': context['sources_used']
        }
    
    def _retrieve_from_raptor(
        self,
        query: str,
        tickers: List[str],
        raptor_retriever: Any,
        top_k: int,
        retrieval_method: str = "collapsed_tree"
    ) -> Optional[str]:
        """Retrieve context from RAPTOR tree."""
        try:
            if raptor_retriever is None:
                logger.warning("RAPTOR retriever not available")
                return None
            
            # Use the tree's retrieve method with configurable method
            retrieved_nodes = raptor_retriever.retrieve(
                query,
                method=retrieval_method,
                k=top_k
            )
            
            if not retrieved_nodes:
                logger.warning("No nodes retrieved from RAPTOR tree")
                return None
            
            # Build context from retrieved nodes
            context_parts = []
            for node, score in retrieved_nodes:
                # Extract text from node
                node_text = node.text if hasattr(node, 'text') else str(node)
                context_parts.append(f"[Relevance: {score:.3f}]\n{node_text}")
            
            logger.info(f"Retrieved {len(context_parts)} nodes from RAPTOR tree")
            return "\n\n".join(context_parts)
        
        except Exception as e:
            logger.error(f"Error retrieving from RAPTOR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _retrieve_fundamentals(
        self, 
        ticker: str,
        generate_if_missing: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve fundamental data for a ticker.
        
        Args:
            ticker: Stock ticker
            generate_if_missing: If True, generate fundamental data if not cached
            
        Returns:
            Fundamental data dictionary or None
        """
        # Check cache first
        cached_data = self.fundamental_cache.get(ticker)
        if cached_data:
            logger.info(f"  ✓ Using cached fundamental data for {ticker}")
            return cached_data
        
        # Generate if missing and requested
        if generate_if_missing:
            logger.info(f"  ⚙ No cache found for {ticker}, fetching financial metrics...")
            try:
                # Import financial data fetcher directly
                from ..scoring.financial_data_fetcher import FinancialDataFetcher
                
                # Initialize fetcher
                fetcher = FinancialDataFetcher()
                
                # Fetch financial data from yfinance
                logger.info(f"    Fetching data from yfinance for {ticker}...")
                financial_data = fetcher.get_company_data(ticker)
                
                if not financial_data:
                    logger.warning(f"  ⚠ Could not fetch financial data for {ticker}")
                    return None
                
                # Extract key metrics
                fundamental_data = {
                    'financial_metrics': {
                        'market_cap': financial_data.get('market_cap'),
                        'revenue': financial_data.get('revenue'),
                        'profit_margin': financial_data.get('profit_margin'),
                        'eps': financial_data.get('eps'),
                        'pe_ratio': financial_data.get('pe_ratio'),
                        'pb_ratio': financial_data.get('pb_ratio'),
                        'debt_to_equity': financial_data.get('debt_to_equity'),
                        'roe': financial_data.get('roe'),
                        'dividend_yield': financial_data.get('dividend_yield'),
                        'beta': financial_data.get('beta'),
                    },
                    'price_info': {
                        'current_price': financial_data.get('current_price'),
                        'day_high': financial_data.get('day_high'),
                        'day_low': financial_data.get('day_low'),
                        'fifty_two_week_high': financial_data.get('fifty_two_week_high'),
                        'fifty_two_week_low': financial_data.get('fifty_two_week_low'),
                    },
                    'company_info': {
                        'company_name': financial_data.get('company_name'),
                        'sector': financial_data.get('sector'),
                        'industry': financial_data.get('industry'),
                    }
                }
                
                # Cache the data
                self.fundamental_cache.set(ticker, fundamental_data)
                logger.info(f"  ✓ Fetched and cached financial metrics for {ticker}")
                
                return fundamental_data
                
            except Exception as e:
                logger.error(f"  ✗ Failed to generate fundamental data for {ticker}: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                return None
        
        # If not cached and generation not requested
        logger.debug(f"No cached fundamental data for {ticker}")
        return None
    
    def _retrieve_portfolio_context(
        self,
        query_analysis: Dict[str, Any]
    ) -> Optional[str]:
        """Retrieve portfolio allocation context."""
        if not self.portfolio_analyzer:
            return None
        
        intent = query_analysis['intent']
        tickers = query_analysis['tickers']
        
        try:
            # Portfolio overview query
            if intent == QueryIntent.PORTFOLIO_OVERVIEW:
                return self.portfolio_analyzer.get_portfolio_overview_context()
            
            # Allocation rationale for specific stock
            elif intent == QueryIntent.ALLOCATION_RATIONALE and tickers:
                ticker = tickers[0]
                return self.portfolio_analyzer.generate_allocation_context(ticker)
            
            # General query with portfolio stock mentioned
            elif tickers and self.portfolio_manager:
                # Get context for first ticker if in portfolio
                ticker = tickers[0]
                if self.portfolio_manager.is_in_portfolio(ticker):
                    return self.portfolio_analyzer.generate_allocation_context(ticker)
            
            return None
        
        except Exception as e:
            logger.error(f"Error retrieving portfolio context: {e}")
            return None
    
    def _merge_context(
        self,
        context: Dict[str, Any],
        intent: QueryIntent,
        tickers: List[str]
    ) -> str:
        """
        Merge context from all sources with appropriate priority.
        
        Args:
            context: Context from all sources
            intent: Query intent
            tickers: Extracted tickers
            
        Returns:
            Merged context string
        """
        merged_parts = []
        
        # Priority order based on intent
        if intent == QueryIntent.PORTFOLIO_OVERVIEW:
            # Portfolio is primary
            if context['portfolio']:
                merged_parts.append(f"=== PORTFOLIO INFORMATION ===\n{context['portfolio']}")
            if context['fundamentals']:
                merged_parts.append(self._format_fundamentals(context['fundamentals']))
        
        elif intent == QueryIntent.ALLOCATION_RATIONALE:
            # Portfolio rationale is primary, fundamentals and reports support
            if context['portfolio']:
                merged_parts.append(f"=== PORTFOLIO CONTEXT ===\n{context['portfolio']}")
            if context['fundamentals']:
                merged_parts.append(self._format_fundamentals(context['fundamentals']))
            if context['annual_reports']:
                merged_parts.append(f"=== ANNUAL REPORTS ===\n{context['annual_reports']}")
        
        elif intent == QueryIntent.FUNDAMENTAL_QUERY:
            # Fundamentals are primary
            if context['fundamentals']:
                merged_parts.append(self._format_fundamentals(context['fundamentals']))
            if context['annual_reports']:
                merged_parts.append(f"=== ANNUAL REPORTS (Additional Context) ===\n{context['annual_reports']}")
            if context['portfolio']:
                merged_parts.append(f"=== PORTFOLIO CONTEXT ===\n{context['portfolio']}")
        
        else:
            # Default: Annual reports primary, fundamentals and portfolio supporting
            if context['annual_reports']:
                merged_parts.append(f"=== ANNUAL REPORTS ===\n{context['annual_reports']}")
            if context['fundamentals']:
                merged_parts.append(self._format_fundamentals(context['fundamentals']))
            if context['portfolio']:
                merged_parts.append(f"=== PORTFOLIO CONTEXT ===\n{context['portfolio']}")
        
        return "\n\n".join(merged_parts) if merged_parts else "No relevant context found."
    
    def _format_fundamentals(self, fundamentals_dict: Dict[str, Dict[str, Any]]) -> str:
        """Format fundamental data for context."""
        parts = ["=== FUNDAMENTAL ANALYSIS ==="]
        
        for ticker, data in fundamentals_dict.items():
            parts.append(f"\n{ticker}:")
            
            # Format key metrics
            if 'financial_metrics' in data:
                metrics = data['financial_metrics']
                parts.append("Financial Metrics:")
                for key, value in metrics.items():
                    parts.append(f"  - {key}: {value}")
            
            # Format sentiment
            if 'sentiment_analysis' in data:
                sentiment = data['sentiment_analysis']
                parts.append(f"Sentiment: {sentiment.get('overall_sentiment', 'N/A')}")
                parts.append(f"Sentiment Score: {sentiment.get('sentiment_score', 'N/A')}")
            
            # Format risks and opportunities
            if 'risk_factors' in data:
                parts.append(f"Risk Factors: {', '.join(data['risk_factors'])}")
            if 'opportunities' in data:
                parts.append(f"Opportunities: {', '.join(data['opportunities'])}")
        
        return "\n".join(parts)
