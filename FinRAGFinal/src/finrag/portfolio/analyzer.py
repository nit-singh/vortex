"""Portfolio Analyzer - Provide portfolio insights and analysis."""

import logging
from typing import Dict, List, Any
from .manager import PortfolioManager

logger = logging.getLogger(__name__)


class PortfolioAnalyzer:
    """Analyze portfolio allocations and provide insights."""
    
    def __init__(self, portfolio_manager: PortfolioManager):
        """Initialize portfolio analyzer."""
        self.portfolio_manager = portfolio_manager
    
    def generate_allocation_context(self, ticker: str) -> str:
        """Generate context about why a stock is in the portfolio."""
        allocation = self.portfolio_manager.get_allocation_by_ticker(ticker)
        if not allocation:
            return f"{ticker} is not in the portfolio."
        
        portfolio_summary = self.portfolio_manager.get_portfolio_summary()
        stock_value = self.portfolio_manager.calculate_stock_value(ticker)
        
        context = f"""
Portfolio Context for {ticker}:
- Allocation: {allocation['percentage']}% of portfolio
- Monetary Value: ₹{stock_value:,.0f} (of total ₹{portfolio_summary['total_value']:,.0f})
- Portfolio Risk Profile: {portfolio_summary['risk_profile']}
- Investment Horizon: {portfolio_summary['investment_horizon']}
- Part of {portfolio_summary['total_stocks']}-stock diversified portfolio
"""
        return context.strip()
    
    def get_portfolio_overview_context(self) -> str:
        """Generate overview of entire portfolio."""
        portfolio_summary = self.portfolio_manager.get_portfolio_summary()
        allocations = self.portfolio_manager.get_allocations()
        
        context = f"""
Portfolio Overview:
Name: {portfolio_summary['portfolio_name']}
Total Value: ₹{portfolio_summary['total_value']:,.0f}
Risk Profile: {portfolio_summary['risk_profile']}
Investment Horizon: {portfolio_summary['investment_horizon']}
Number of Stocks: {portfolio_summary['total_stocks']}

Stock Allocations:
"""
        for alloc in sorted(allocations, key=lambda x: x['percentage'], reverse=True):
            ticker = alloc['ticker']
            percentage = alloc['percentage']
            value = self.portfolio_manager.calculate_stock_value(ticker)
            context += f"- {ticker}: {percentage}% (₹{value:,.0f})\n"
        
        return context.strip()
    
    def get_related_portfolio_stocks(self, ticker: str) -> List[Dict[str, Any]]:
        """Get other stocks in portfolio for comparison context."""
        allocations = self.portfolio_manager.get_allocations()
        return [a for a in allocations if a['ticker'].upper() != ticker.upper()]
    
    def is_portfolio_query(self, query: str) -> bool:
        """Determine if query is about portfolio."""
        portfolio_keywords = [
            'portfolio', 'allocation', 'my stocks', 'my holdings',
            'what stocks', 'which stocks', 'invested in',
            'my investments', 'distribution'
        ]
        
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in portfolio_keywords)
