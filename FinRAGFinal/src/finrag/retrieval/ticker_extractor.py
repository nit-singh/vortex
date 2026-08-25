"""Ticker Extractor - Extract stock tickers from user queries using hybrid approach."""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from difflib import SequenceMatcher
import logging

logger = logging.getLogger(__name__)


class TickerExtractor:
    """Extract stock tickers from queries using pattern matching, fuzzy matching, and LLM fallback."""
    
    def __init__(
        self,
        mapping_path: str = "data/mappings/ticker_mapping.json",
        llm_model: Optional[Any] = None
    ):
        """Initialize ticker extractor."""
        self.mapping_path = Path(mapping_path)
        self.llm_model = llm_model
        self.ticker_map = self._load_ticker_mapping()
        self.company_to_ticker = self._build_company_index()
    
    def _load_ticker_mapping(self) -> List[Dict[str, Any]]:
        """Load ticker mapping from JSON."""
        if not self.mapping_path.exists():
            logger.warning(f"Ticker mapping not found at {self.mapping_path}")
            return []
        
        try:
            with open(self.mapping_path, 'r') as f:
                mapping = json.load(f)
            logger.info(f"Loaded {len(mapping)} ticker mappings")
            return mapping
        except Exception as e:
            logger.error(f"Error loading ticker mapping: {e}")
            return []
    
    def _build_company_index(self) -> Dict[str, str]:
        """Build index mapping company names/aliases to tickers."""
        index = {}
        
        for entry in self.ticker_map:
            ticker = entry['ticker']
            company_name = entry['company_name']
            aliases = entry.get('aliases', [])
            
            # Add company name
            index[company_name.lower()] = ticker
            
            # Add all aliases
            for alias in aliases:
                index[alias.lower()] = ticker
        
        return index
    
    def extract_tickers(
        self,
        query: str,
        portfolio_tickers: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Extract tickers from query using hybrid approach."""
        query_lower = query.lower()
        extracted_tickers = []
        company_names = []
        confidence_scores = []
        method_used = []
        
        # Step 1: Direct ticker pattern matching (e.g., "AAPL", "TCS.NS")
        ticker_patterns = self._extract_by_pattern(query)
        for ticker, confidence in ticker_patterns:
            extracted_tickers.append(ticker)
            confidence_scores.append(confidence)
            method_used.append("pattern")
            # Try to find company name
            company = self._get_company_name(ticker)
            company_names.append(company if company else ticker)
        
        # Step 2: Company name fuzzy matching
        if not extracted_tickers:
            fuzzy_matches = self._extract_by_fuzzy_matching(query)
            for ticker, company, confidence in fuzzy_matches:
                if ticker not in extracted_tickers:
                    extracted_tickers.append(ticker)
                    company_names.append(company)
                    confidence_scores.append(confidence)
                    method_used.append("fuzzy")
        
        # Step 3: Check portfolio context
        if not extracted_tickers and portfolio_tickers:
            portfolio_matches = self._extract_from_portfolio_context(
                query, portfolio_tickers
            )
            for ticker, confidence in portfolio_matches:
                if ticker not in extracted_tickers:
                    extracted_tickers.append(ticker)
                    confidence_scores.append(confidence)
                    method_used.append("portfolio")
                    company = self._get_company_name(ticker)
                    company_names.append(company if company else ticker)
        
        # Step 4: LLM fallback for complex queries
        if not extracted_tickers and self.llm_model:
            llm_results = self._extract_by_llm(query, portfolio_tickers)
            if llm_results:
                extracted_tickers = llm_results['tickers']
                company_names = llm_results['company_names']
                confidence_scores = [0.8] * len(extracted_tickers)
                method_used = ['llm'] * len(extracted_tickers)
        
        return {
            'tickers': extracted_tickers,
            'company_names': company_names,
            'confidence_scores': confidence_scores,
            'methods': method_used,
            'has_tickers': len(extracted_tickers) > 0
        }
    
    def _extract_by_pattern(self, query: str) -> List[Tuple[str, float]]:
        """
        Extract tickers using regex patterns.
        
        Matches:
        - Single uppercase words (e.g., AAPL, TCS)
        - Tickers with suffixes (e.g., TCS.NS, HEROMOTOCO.NS)
        """
        results = []
        
        # Pattern 1: Ticker with suffix (e.g., TCS.NS, HEROMOTOCO.NS)
        pattern1 = r'\b([A-Z][A-Z0-9\-]+\.[A-Z]{2})\b'
        matches1 = re.findall(pattern1, query)
        for match in matches1:
            if self._validate_ticker(match):
                results.append((match, 0.95))
        
        # Pattern 2: Simple uppercase ticker (e.g., AAPL, TCS, MSFT)
        pattern2 = r'\b([A-Z]{2,10})\b'
        matches2 = re.findall(pattern2, query)
        for match in matches2:
            # Skip if already found with suffix
            if any(match in ticker for ticker, _ in results):
                continue
            if self._validate_ticker(match):
                results.append((match, 0.85))
        
        return results
    
    def _extract_by_fuzzy_matching(
        self,
        query: str,
        threshold: float = 0.75
    ) -> List[Tuple[str, str, float]]:
        """
        Extract tickers by fuzzy matching company names.
        
        Args:
            query: User query
            threshold: Minimum similarity threshold (0-1)
            
        Returns:
            List of (ticker, company_name, confidence) tuples
        """
        results = []
        query_lower = query.lower()
        
        for company_name, ticker in self.company_to_ticker.items():
            # Check if company name is in query
            if company_name in query_lower:
                # Exact match in query
                confidence = 0.95
                company_display = self._get_company_name(ticker)
                results.append((ticker, company_display, confidence))
                continue
            
            # Fuzzy matching for partial matches
            similarity = SequenceMatcher(None, query_lower, company_name).ratio()
            if similarity >= threshold:
                company_display = self._get_company_name(ticker)
                results.append((ticker, company_display, similarity))
        
        # Sort by confidence and return top matches
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:3]  # Return top 3 matches
    
    def _extract_from_portfolio_context(
        self,
        query: str,
        portfolio_tickers: List[str]
    ) -> List[Tuple[str, float]]:
        """
        Check if query mentions stocks from portfolio by name.
        
        Args:
            query: User query
            portfolio_tickers: List of portfolio tickers
            
        Returns:
            List of (ticker, confidence) tuples
        """
        results = []
        query_lower = query.lower()
        
        for ticker in portfolio_tickers:
            company_name = self._get_company_name(ticker)
            if company_name:
                company_lower = company_name.lower()
                if company_lower in query_lower or ticker.lower() in query_lower:
                    results.append((ticker, 0.90))
        
        return results
    
    def _extract_by_llm(
        self,
        query: str,
        portfolio_tickers: Optional[List[str]] = None
    ) -> Optional[Dict[str, List[str]]]:
        """
        Use LLM to extract tickers from complex queries.
        
        Args:
            query: User query
            portfolio_tickers: Optional portfolio tickers for context
            
        Returns:
            Dictionary with tickers and company names
        """
        if not self.llm_model:
            return None
        
        try:
            # Build available tickers context
            available_tickers = [entry['ticker'] for entry in self.ticker_map]
            available_companies = [entry['company_name'] for entry in self.ticker_map]
            
            prompt = f"""Extract stock ticker(s) from this query: "{query}"

Available tickers: {', '.join(available_tickers[:20])}...
Available companies: {', '.join(available_companies[:20])}...
"""
            
            if portfolio_tickers:
                prompt += f"\nUser's portfolio tickers: {', '.join(portfolio_tickers)}\n"
            
            prompt += """
Return ONLY a JSON object with this exact format:
{
    "tickers": ["TICKER1", "TICKER2"],
    "company_names": ["Company 1", "Company 2"]
}

If no tickers found, return empty arrays. Do not include any explanatory text."""
            
            # Call LLM
            response = self.llm_model.generate(prompt)
            
            # Parse JSON response
            import json
            result = json.loads(response.strip())
            
            return result
        
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return None
    
    def _validate_ticker(self, ticker: str) -> bool:
        """
        Validate if a string is likely a valid ticker.
        
        Args:
            ticker: Ticker string to validate
            
        Returns:
            True if valid ticker format
        """
        # Check if ticker exists in our mapping
        for entry in self.ticker_map:
            if entry['ticker'].upper() == ticker.upper():
                return True
            if ticker.upper() in [alias.upper() for alias in entry.get('aliases', [])]:
                return True
        
        # Check if it matches ticker format (even if not in mapping)
        # e.g., 2-10 uppercase letters, optional .XX suffix
        if re.match(r'^[A-Z]{2,10}(\.[A-Z]{2})?$', ticker):
            return True
        
        return False
    
    def _get_company_name(self, ticker: str) -> Optional[str]:
        """
        Get company name for a ticker.
        
        Args:
            ticker: Stock ticker
            
        Returns:
            Company name or None
        """
        for entry in self.ticker_map:
            if entry['ticker'].upper() == ticker.upper():
                return entry['company_name']
        return None
    
    def add_ticker_mapping(
        self,
        ticker: str,
        company_name: str,
        aliases: Optional[List[str]] = None
    ) -> bool:
        """
        Add a new ticker mapping.
        
        Args:
            ticker: Stock ticker
            company_name: Company name
            aliases: Optional list of aliases
            
        Returns:
            True if successful
        """
        new_entry = {
            'ticker': ticker,
            'company_name': company_name,
            'aliases': aliases or [company_name]
        }
        
        self.ticker_map.append(new_entry)
        self.company_to_ticker = self._build_company_index()
        
        # Save to file
        try:
            with open(self.mapping_path, 'w') as f:
                json.dump(self.ticker_map, f, indent=2)
            logger.info(f"Added ticker mapping for {ticker}")
            return True
        except Exception as e:
            logger.error(f"Error saving ticker mapping: {e}")
            return False
