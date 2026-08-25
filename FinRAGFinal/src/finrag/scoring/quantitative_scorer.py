"""
Quantitative scoring based on financial ratios from yfinance.
"""
from typing import Dict, Any
import numpy as np


class QuantitativeScorer:
    """Score stocks based on quantitative financial metrics."""
    
    def __init__(self):
        """Initialize quantitative scorer."""
        self.weights = {
            "valuation": 0.20,      # PE, PB, PS ratios
            "profitability": 0.25,  # Margins, ROE, ROA
            "growth": 0.25,         # Revenue/earnings growth
            "financial_health": 0.15,  # Debt, cash flow
            "momentum": 0.15        # Price trends, analyst ratings
        }
    
    def score_financial_data(self, financial_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate quantitative score from financial data.
        
        Args:
            financial_data: Financial metrics from yfinance
        
        Returns:
            Dictionary with scores and breakdown
        """
        if "error" in financial_data:
            return {
                "score": 50,  # Neutral score
                "confidence": 0,
                "error": financial_data["error"]
            }
        
        # Score each category
        valuation_score = self._score_valuation(financial_data)
        profitability_score = self._score_profitability(financial_data)
        growth_score = self._score_growth(financial_data)
        health_score = self._score_financial_health(financial_data)
        momentum_score = self._score_momentum(financial_data)
        
        # Calculate weighted score
        total_score = (
            valuation_score * self.weights["valuation"] +
            profitability_score * self.weights["profitability"] +
            growth_score * self.weights["growth"] +
            health_score * self.weights["financial_health"] +
            momentum_score * self.weights["momentum"]
        )
        
        # Calculate confidence based on data completeness
        confidence = financial_data.get("data_completeness", 50)
        
        return {
            "score": max(0, min(100, total_score)),
            "confidence": confidence,
            "breakdown": {
                "valuation": valuation_score,
                "profitability": profitability_score,
                "growth": growth_score,
                "financial_health": health_score,
                "momentum": momentum_score
            },
            "raw_data": financial_data
        }
    
    def _score_valuation(self, data: Dict) -> float:
        """Score valuation metrics (0-100)."""
        scores = []
        
        # PE Ratio (lower is better, optimal 10-20)
        pe = data.get("pe_ratio")
        if pe is not None and pe > 0:
            if pe < 10:
                scores.append(90)
            elif pe < 15:
                scores.append(80)
            elif pe < 20:
                scores.append(70)
            elif pe < 30:
                scores.append(50)
            else:
                scores.append(30)
        
        # PEG Ratio (lower is better, <1 is good)
        peg = data.get("peg_ratio")
        if peg is not None and peg > 0:
            if peg < 1:
                scores.append(85)
            elif peg < 1.5:
                scores.append(70)
            elif peg < 2:
                scores.append(55)
            else:
                scores.append(40)
        
        # Price to Book (lower is better, <3 is good)
        pb = data.get("price_to_book")
        if pb is not None and pb > 0:
            if pb < 1:
                scores.append(90)
            elif pb < 2:
                scores.append(75)
            elif pb < 3:
                scores.append(60)
            else:
                scores.append(40)
        
        return np.mean(scores) if scores else 50
    
    def _score_profitability(self, data: Dict) -> float:
        """Score profitability metrics (0-100)."""
        scores = []
        
        # Profit Margin (higher is better)
        profit_margin = data.get("profit_margin")
        if profit_margin is not None:
            margin_pct = profit_margin * 100
            if margin_pct > 20:
                scores.append(95)
            elif margin_pct > 15:
                scores.append(85)
            elif margin_pct > 10:
                scores.append(75)
            elif margin_pct > 5:
                scores.append(60)
            else:
                scores.append(40)
        
        # Operating Margin
        op_margin = data.get("operating_margin")
        if op_margin is not None:
            op_pct = op_margin * 100
            if op_pct > 25:
                scores.append(95)
            elif op_pct > 15:
                scores.append(80)
            elif op_pct > 10:
                scores.append(65)
            else:
                scores.append(45)
        
        # ROE (higher is better, >15% is good)
        roe = data.get("roe")
        if roe is not None:
            roe_pct = roe * 100
            if roe_pct > 20:
                scores.append(90)
            elif roe_pct > 15:
                scores.append(75)
            elif roe_pct > 10:
                scores.append(60)
            else:
                scores.append(40)
        
        # ROA
        roa = data.get("roa")
        if roa is not None:
            roa_pct = roa * 100
            if roa_pct > 10:
                scores.append(90)
            elif roa_pct > 5:
                scores.append(70)
            elif roa_pct > 2:
                scores.append(55)
            else:
                scores.append(40)
        
        return np.mean(scores) if scores else 50
    
    def _score_growth(self, data: Dict) -> float:
        """Score growth metrics (0-100)."""
        scores = []
        
        # Revenue Growth (higher is better)
        rev_growth = data.get("revenue_growth")
        if rev_growth is not None:
            growth_pct = rev_growth * 100
            if growth_pct > 20:
                scores.append(95)
            elif growth_pct > 15:
                scores.append(85)
            elif growth_pct > 10:
                scores.append(75)
            elif growth_pct > 5:
                scores.append(60)
            elif growth_pct > 0:
                scores.append(50)
            else:
                scores.append(30)
        
        # Earnings Growth
        earn_growth = data.get("earnings_growth")
        if earn_growth is not None:
            eg_pct = earn_growth * 100
            if eg_pct > 25:
                scores.append(95)
            elif eg_pct > 15:
                scores.append(80)
            elif eg_pct > 10:
                scores.append(70)
            elif eg_pct > 5:
                scores.append(55)
            else:
                scores.append(40)
        
        return np.mean(scores) if scores else 50
    
    def _score_financial_health(self, data: Dict) -> float:
        """Score financial health metrics (0-100)."""
        scores = []
        
        # Debt to Equity (lower is better, <1 is good)
        de = data.get("debt_to_equity")
        if de is not None:
            if de < 0.5:
                scores.append(95)
            elif de < 1.0:
                scores.append(80)
            elif de < 1.5:
                scores.append(65)
            elif de < 2.0:
                scores.append(50)
            else:
                scores.append(35)
        
        # Current Ratio (>1.5 is good)
        current = data.get("current_ratio")
        if current is not None:
            if current > 2.0:
                scores.append(90)
            elif current > 1.5:
                scores.append(80)
            elif current > 1.0:
                scores.append(60)
            else:
                scores.append(40)
        
        # Free Cash Flow (positive is good)
        fcf = data.get("free_cash_flow")
        if fcf is not None:
            if fcf > 0:
                scores.append(80)
            else:
                scores.append(30)
        
        return np.mean(scores) if scores else 50
    
    def _score_momentum(self, data: Dict) -> float:
        """Score momentum and market sentiment (0-100)."""
        scores = []
        
        # Price changes (positive momentum is good)
        for period, weight in [("price_change_1m", 0.4), ("price_change_3m", 0.3), ("price_change_6m", 0.2), ("price_change_1y", 0.1)]:
            change = data.get(period)
            if change is not None:
                if change > 15:
                    scores.append(90 * weight)
                elif change > 10:
                    scores.append(80 * weight)
                elif change > 5:
                    scores.append(70 * weight)
                elif change > 0:
                    scores.append(60 * weight)
                elif change > -5:
                    scores.append(45 * weight)
                else:
                    scores.append(30 * weight)
        
        # Analyst recommendation
        rec = data.get("recommendation_key")
        if rec:
            rec_scores = {
                "strong_buy": 95,
                "buy": 80,
                "hold": 50,
                "sell": 30,
                "strong_sell": 15
            }
            scores.append(rec_scores.get(rec, 50))
        
        # Target price vs current price
        target = data.get("target_mean_price")
        current = data.get("current_price")
        if target and current and current > 0:
            upside = ((target - current) / current) * 100
            if upside > 20:
                scores.append(90)
            elif upside > 10:
                scores.append(75)
            elif upside > 0:
                scores.append(60)
            else:
                scores.append(40)
        
        return sum(scores) if scores else 50
