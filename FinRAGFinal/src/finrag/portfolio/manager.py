"""Portfolio Manager - Handle portfolio data operations."""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class PortfolioManager:
    """Manage portfolio allocations and operations."""
    
    def __init__(self, portfolio_path: str = "data/portfolio/portfolio.json"):
        """Initialize portfolio manager."""
        self.portfolio_path = Path(portfolio_path)
        self.portfolio_path.parent.mkdir(parents=True, exist_ok=True)
        self._portfolio_data = None
    
    def load_portfolio(self) -> Dict[str, Any]:
        """Load portfolio from JSON file."""
        if not self.portfolio_path.exists():
            logger.warning(f"No portfolio found at {self.portfolio_path}")
            return self._create_empty_portfolio()
        
        try:
            with open(self.portfolio_path, 'r') as f:
                self._portfolio_data = json.load(f)
            logger.info(f"Loaded portfolio with {len(self._portfolio_data.get('allocations', []))} stocks")
            return self._portfolio_data
        except Exception as e:
            logger.error(f"Error loading portfolio: {e}")
            return self._create_empty_portfolio()
    
    def save_portfolio(self, portfolio_data: Dict[str, Any]) -> bool:
        """Save portfolio to JSON file."""
        try:
            portfolio_data['last_updated'] = datetime.now().strftime("%Y-%m-%d")
            
            with open(self.portfolio_path, 'w') as f:
                json.dump(portfolio_data, f, indent=2)
            
            self._portfolio_data = portfolio_data
            logger.info(f"Portfolio saved successfully to {self.portfolio_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving portfolio: {e}")
            return False
    
    def get_allocations(self) -> List[Dict[str, Any]]:
        """Get all stock allocations."""
        if self._portfolio_data is None:
            self.load_portfolio()
        
        return self._portfolio_data.get('allocations', [])
    
    def get_allocation_by_ticker(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get allocation for a specific ticker."""
        allocations = self.get_allocations()
        
        for allocation in allocations:
            if allocation['ticker'].upper() == ticker.upper():
                return allocation
        
        return None
    
    def get_tickers(self) -> List[str]:
        """Get list of all tickers in portfolio."""
        allocations = self.get_allocations()
        return [alloc['ticker'] for alloc in allocations]
    
    def is_in_portfolio(self, ticker: str) -> bool:
        """Check if ticker is in portfolio."""
        return self.get_allocation_by_ticker(ticker) is not None
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio summary information."""
        if self._portfolio_data is None:
            self.load_portfolio()
        
        allocations = self.get_allocations()
        total_percentage = sum(alloc['percentage'] for alloc in allocations)
        
        return {
            'portfolio_name': self._portfolio_data.get('portfolio_name', 'Unknown'),
            'total_stocks': len(allocations),
            'total_percentage': round(total_percentage, 2),
            'total_value': self._portfolio_data.get('total_value', 0),
            'risk_profile': self._portfolio_data.get('risk_profile', 'unknown'),
            'investment_horizon': self._portfolio_data.get('investment_horizon', 'unknown'),
            'tickers': self.get_tickers(),
            'created_date': self._portfolio_data.get('created_date'),
            'last_updated': self._portfolio_data.get('last_updated')
        }
    
    def add_allocation(self, ticker: str, percentage: float) -> bool:
        """Add or update stock allocation."""
        if self._portfolio_data is None:
            self.load_portfolio()
        
        allocations = self._portfolio_data.get('allocations', [])
        
        # Check if ticker already exists
        existing = next((a for a in allocations if a['ticker'].upper() == ticker.upper()), None)
        
        if existing:
            existing['percentage'] = percentage
            logger.info(f"Updated {ticker} allocation to {percentage}%")
        else:
            allocations.append({
                'ticker': ticker,
                'percentage': percentage
            })
            logger.info(f"Added {ticker} with {percentage}% allocation")
        
        self._portfolio_data['allocations'] = allocations
        return self.save_portfolio(self._portfolio_data)
    
    def remove_allocation(self, ticker: str) -> bool:
        """Remove stock allocation."""
        if self._portfolio_data is None:
            self.load_portfolio()
        
        allocations = self._portfolio_data.get('allocations', [])
        original_count = len(allocations)
        
        self._portfolio_data['allocations'] = [
            a for a in allocations 
            if a['ticker'].upper() != ticker.upper()
        ]
        
        if len(self._portfolio_data['allocations']) < original_count:
            logger.info(f"Removed {ticker} from portfolio")
            return self.save_portfolio(self._portfolio_data)
        else:
            logger.warning(f"{ticker} not found in portfolio")
            return False
    
    def update_portfolio_metadata(
        self,
        total_value: Optional[float] = None,
        risk_profile: Optional[str] = None,
        investment_horizon: Optional[str] = None,
        portfolio_name: Optional[str] = None
    ) -> bool:
        """Update portfolio metadata."""
        if self._portfolio_data is None:
            self.load_portfolio()
        
        if total_value is not None:
            self._portfolio_data['total_value'] = total_value
        if risk_profile is not None:
            self._portfolio_data['risk_profile'] = risk_profile
        if investment_horizon is not None:
            self._portfolio_data['investment_horizon'] = investment_horizon
        if portfolio_name is not None:
            self._portfolio_data['portfolio_name'] = portfolio_name
        
        return self.save_portfolio(self._portfolio_data)
    
    def _create_empty_portfolio(self) -> Dict[str, Any]:
        """Create an empty portfolio structure."""
        return {
            'portfolio_name': 'Default Portfolio',
            'created_date': datetime.now().strftime("%Y-%m-%d"),
            'last_updated': datetime.now().strftime("%Y-%m-%d"),
            'allocations': [],
            'total_value': 0,
            'risk_profile': 'moderate',
            'investment_horizon': 'medium-term'
        }
    
    def calculate_stock_value(self, ticker: str) -> Optional[float]:
        """Calculate monetary value of a stock allocation."""
        allocation = self.get_allocation_by_ticker(ticker)
        if allocation and self._portfolio_data:
            total_value = self._portfolio_data.get('total_value', 0)
            percentage = allocation['percentage']
            return (percentage / 100) * total_value
        return None
