"""
Fetch financial ratios and market data using yfinance.
"""
import yfinance as yf
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import numpy as np


class FinancialDataFetcher:
    """Fetch and process financial data from Yahoo Finance."""
    
    def __init__(self):
        """Initialize the financial data fetcher."""
        pass
    
    def get_company_data(self, ticker: str) -> Dict[str, Any]:
        """
        Get comprehensive financial data for a company.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL', 'RELIANCE.NS')
        
        Returns:
            Dictionary containing financial ratios and metrics
        """
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Get historical data for momentum calculation
            hist = stock.history(period="1y")
            
            data = {
                "ticker": ticker,
                "company_name": info.get("longName", ticker),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                
                # Valuation Metrics
                "current_price": info.get("currentPrice", 0),
                "market_cap": info.get("marketCap", 0),
                "pe_ratio": info.get("trailingPE", None),
                "forward_pe": info.get("forwardPE", None),
                "peg_ratio": info.get("pegRatio", None),
                "price_to_book": info.get("priceToBook", None),
                "price_to_sales": info.get("priceToSalesTrailing12Months", None),
                "enterprise_value": info.get("enterpriseValue", 0),
                "ev_to_revenue": info.get("enterpriseToRevenue", None),
                "ev_to_ebitda": info.get("enterpriseToEbitda", None),
                
                # Profitability Metrics
                "profit_margin": info.get("profitMargins", None),
                "operating_margin": info.get("operatingMargins", None),
                "gross_margin": info.get("grossMargins", None),
                "roe": info.get("returnOnEquity", None),
                "roa": info.get("returnOnAssets", None),
                "roic": info.get("returnOnCapital", None),
                
                # Growth Metrics
                "revenue_growth": info.get("revenueGrowth", None),
                "earnings_growth": info.get("earningsGrowth", None),
                "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth", None),
                "revenue_per_share": info.get("revenuePerShare", None),
                
                # Financial Health
                "total_cash": info.get("totalCash", 0),
                "total_debt": info.get("totalDebt", 0),
                "debt_to_equity": info.get("debtToEquity", None),
                "current_ratio": info.get("currentRatio", None),
                "quick_ratio": info.get("quickRatio", None),
                "free_cash_flow": info.get("freeCashflow", 0),
                "operating_cash_flow": info.get("operatingCashflow", 0),
                
                # Dividend Metrics
                "dividend_yield": info.get("dividendYield", None),
                "dividend_rate": info.get("dividendRate", None),
                "payout_ratio": info.get("payoutRatio", None),
                
                # Analyst Recommendations
                "target_mean_price": info.get("targetMeanPrice", None),
                "target_high_price": info.get("targetHighPrice", None),
                "target_low_price": info.get("targetLowPrice", None),
                "recommendation_key": info.get("recommendationKey", None),
                "number_of_analyst_opinions": info.get("numberOfAnalystOpinions", 0),
                
                # Momentum Indicators (from historical data)
                "price_change_1m": self._calculate_price_change(hist, 30),
                "price_change_3m": self._calculate_price_change(hist, 90),
                "price_change_6m": self._calculate_price_change(hist, 180),
                "price_change_1y": self._calculate_price_change(hist, 365),
                "volatility": self._calculate_volatility(hist),
                "52_week_high": info.get("fiftyTwoWeekHigh", None),
                "52_week_low": info.get("fiftyTwoWeekLow", None),
                
                # Trading Metrics
                "average_volume": info.get("averageVolume", 0),
                "beta": info.get("beta", None),
                
                # Data quality
                "data_fetch_time": datetime.now().isoformat(),
                "data_completeness": self._calculate_completeness(info)
            }
            
            return data
            
        except Exception as e:
            print(f"Error fetching data for {ticker}: {str(e)}")
            return {
                "ticker": ticker,
                "error": str(e),
                "data_completeness": 0.0
            }
    
    def _calculate_price_change(self, hist, days: int) -> Optional[float]:
        """Calculate percentage price change over specified days."""
        try:
            if len(hist) < days:
                days = len(hist)
            if days < 2:
                return None
            
            current_price = hist['Close'].iloc[-1]
            past_price = hist['Close'].iloc[-days]
            
            return ((current_price - past_price) / past_price) * 100
        except Exception:
            return None
    
    def _calculate_volatility(self, hist) -> Optional[float]:
        """Calculate annualized volatility."""
        try:
            if len(hist) < 20:
                return None
            
            returns = hist['Close'].pct_change().dropna()
            volatility = returns.std() * np.sqrt(252)  # Annualized
            return volatility * 100  # Convert to percentage
        except Exception:
            return None
    
    def _calculate_completeness(self, info: Dict) -> float:
        """Calculate data completeness score (0-100)."""
        key_fields = [
            'currentPrice', 'marketCap', 'trailingPE', 'profitMargins',
            'revenueGrowth', 'returnOnEquity', 'debtToEquity', 'freeCashflow',
            'forwardPE', 'priceToBook', 'operatingMargins', 'beta'
        ]
        
        available = sum(1 for field in key_fields if info.get(field) is not None)
        return (available / len(key_fields)) * 100
    
    def get_peer_comparison(self, ticker: str, sector: str = None) -> Dict[str, Any]:
        """
        Get peer comparison data (placeholder for future enhancement).
        
        Args:
            ticker: Primary ticker
            sector: Sector for peer comparison
        
        Returns:
            Peer comparison metrics
        """
        # This can be enhanced to fetch peer data
        return {
            "ticker": ticker,
            "sector": sector,
            "note": "Peer comparison not yet implemented"
        }
