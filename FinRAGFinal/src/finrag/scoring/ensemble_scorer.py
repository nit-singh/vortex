"""Ensemble scoring system combining RAG analysis with financial metrics."""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime
import json
import logging

from .financial_data_fetcher import FinancialDataFetcher
from .sentiment_analyzer import SentimentAnalyzer
from .quantitative_scorer import QuantitativeScorer


logger = logging.getLogger(__name__)


@dataclass
class ScoringConfig:
    """Configuration for ensemble scoring."""
    
    sentiment_weight: float = 0.25
    yoy_trend_weight: float = 0.20
    risk_adjusted_weight: float = 0.20
    quantitative_weight: float = 0.20
    llm_judge_weight: float = 0.15
    
    sentiment_aspects: List[Dict[str, Any]] = field(default_factory=lambda: [
        {
            "name": "Strategic Initiatives",
            "question": "What strategic initiatives, innovations, and future plans are mentioned?",
            "weight": 0.30
        },
        {
            "name": "Market Position",
            "question": "What is the company's competitive position, market share, and industry standing?",
            "weight": 0.30
        },
        {
            "name": "Financial Health",
            "question": "What is the company's financial stability, cash flow, and debt situation?",
            "weight": 0.25
        },
        {
            "name": "Corporate Governance",
            "question": "What are the management quality indicators and governance practices?",
            "weight": 0.15
        }
    ])
    
    time_horizon: str = "6-12 months"
    verbose: bool = False
    
    def __post_init__(self):
        """Validate configuration."""
        total_weight = (
            self.sentiment_weight + 
            self.yoy_trend_weight + 
            self.risk_adjusted_weight + 
            self.quantitative_weight + 
            self.llm_judge_weight
        )
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Component weights must sum to 1.0 (got {total_weight})")


@dataclass
class ScoringResult:
    """Result from ensemble scoring."""
    
    score: float
    direction: str
    confidence: float
    
    sentiment_score: float
    yoy_trend_score: float
    risk_adjusted_score: float
    quantitative_score: float
    llm_judge_score: float
    
    breakdown: Dict[str, Any]
    key_drivers: List[str]
    risk_factors: List[str]
    
    ticker: str
    company_name: str
    time_horizon: str
    generated_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "score": self.score,
            "direction": self.direction,
            "confidence": self.confidence,
            "component_scores": {
                "sentiment": self.sentiment_score,
                "yoy_trend": self.yoy_trend_score,
                "risk_adjusted": self.risk_adjusted_score,
                "quantitative": self.quantitative_score,
                "llm_judge": self.llm_judge_score
            },
            "breakdown": self.breakdown,
            "key_drivers": self.key_drivers,
            "risk_factors": self.risk_factors,
            "metadata": {
                "ticker": self.ticker,
                "company_name": self.company_name,
                "time_horizon": self.time_horizon,
                "generated_at": self.generated_at
            }
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        lines = [
            f"Stock Prediction Score - {self.ticker}",
            f"Company: {self.company_name}",
            f"Generated: {self.generated_at}",
            "",
            f"Overall score: {self.score:.1f}/100",
            f"Direction: {self.direction.upper()}",
            f"Confidence: {self.confidence:.1f}%",
            f"Time horizon: {self.time_horizon}",
            "",
            "Component scores:",
            f"  Sentiment analysis:   {self.sentiment_score:.1f}/100",
            f"  Year-over-year trend: {self.yoy_trend_score:.1f}/100",
            f"  Risk-adjusted score:  {self.risk_adjusted_score:.1f}/100",
            f"  Quantitative metrics: {self.quantitative_score:.1f}/100",
            f"  LLM judge:            {self.llm_judge_score:.1f}/100",
            "",
            "Key drivers:",
            self._format_list(self.key_drivers),
            "",
            "Risk factors:",
            self._format_list(self.risk_factors),
        ]
        return "\n".join(lines)
    
    def _format_list(self, items: List[str]) -> str:
        """Format list for display."""
        if not items:
            return "  None identified"
        return "\n".join(f"  - {item}" for item in items)


class EnsembleScorer:
    """
    Ensemble scoring system that combines:
    1. Multi-aspect sentiment analysis from annual reports
    2. Year-over-Year trend analysis
    3. Risk-adjusted scoring
    4. Quantitative metrics from yfinance
    5. LLM-as-judge assessment
    """
    
    def __init__(self, config: ScoringConfig = None):
        """
        Initialize ensemble scorer.
        
        Args:
            config: Scoring configuration
        """
        self.config = config or ScoringConfig()
        self.financial_fetcher = FinancialDataFetcher()
        self.quantitative_scorer = QuantitativeScorer()
    
    def score_company(
        self,
        finrag,
        ticker: str,
        company_name: str = None,
        ticker_suffix: str = ""
    ) -> ScoringResult:
        """
        Generate comprehensive stock prediction score.
        
        Args:
            finrag: FinRAG instance with loaded annual report(s)
            ticker: Stock ticker symbol
            company_name: Company name (optional, will fetch from yfinance)
            ticker_suffix: Suffix for yfinance (e.g., ".NS" for NSE, ".BO" for BSE)
        
        Returns:
            ScoringResult with comprehensive analysis
        """
        self._log(f"Scoring workflow started for {ticker}")
        
        # Construct full ticker for yfinance
        yf_ticker = f"{ticker}{ticker_suffix}"
        
        # 1. Fetch quantitative financial data
        self._log("Step 1/5: Fetching financial data from yfinance...")
        financial_data = self.financial_fetcher.get_company_data(yf_ticker)
        
        if not company_name:
            company_name = financial_data.get("company_name", ticker)
        
        self._log(
            f"Retrieved data for {company_name} (completeness {financial_data.get('data_completeness', 0):.1f}%)"
        )
        
        # 2. Sentiment Analysis
        self._log("Step 2/5: Analyzing sentiment from annual report...")
        sentiment_analyzer = SentimentAnalyzer(finrag.qa_model)
        sentiment_result = sentiment_analyzer.analyze_multi_aspect_sentiment(
            finrag,
            self.config.sentiment_aspects
        )
        sentiment_score = sentiment_result["overall_score"]
        self._log(f"Sentiment score: {sentiment_score:.1f}/100")
        
        # 3. Year-over-Year Trend Analysis
        self._log("Step 3/5: Analyzing year-over-year trends...")
        yoy_result = self._analyze_yoy_trends(finrag, financial_data)
        yoy_score = yoy_result["score"]
        self._log(f"Year-over-year score: {yoy_score:.1f}/100")
        
        # 4. Risk-Adjusted Scoring
        self._log("Step 4/5: Calculating risk-adjusted score...")
        risk_result = self._calculate_risk_adjusted_score(finrag, sentiment_result)
        risk_score = risk_result["score"]
        self._log(f"Risk-adjusted score: {risk_score:.1f}/100")
        
        # 5. Quantitative Scoring
        self._log("Step 5/5: Scoring quantitative metrics...")
        quant_result = self.quantitative_scorer.score_financial_data(financial_data)
        quant_score = quant_result["score"]
        self._log(f"Quantitative score: {quant_score:.1f}/100")
        
        # 6. LLM Judge (uses combination of all above)
        self._log("Generating LLM judge assessment...")
        llm_result = self._llm_judge_score(
            finrag,
            financial_data,
            sentiment_result,
            yoy_result,
            quant_result
        )
        llm_score = llm_result["score"]
        self._log(f"LLM judge score: {llm_score:.1f}/100")
        
        # Calculate ensemble score
        self._log("Calculating ensemble score...")
        final_score = (
            sentiment_score * self.config.sentiment_weight +
            yoy_score * self.config.yoy_trend_weight +
            risk_score * self.config.risk_adjusted_weight +
            quant_score * self.config.quantitative_weight +
            llm_score * self.config.llm_judge_weight
        )
        
        # Determine direction
        if final_score >= 65:
            direction = "bullish"
        elif final_score <= 45:
            direction = "bearish"
        else:
            direction = "neutral"
        
        # Calculate overall confidence
        confidence = self._calculate_ensemble_confidence(
            sentiment_result,
            yoy_result,
            risk_result,
            quant_result,
            llm_result,
            [sentiment_score, yoy_score, risk_score, quant_score, llm_score]
        )
        
        # Extract key drivers and risks
        key_drivers = self._extract_key_drivers(
            sentiment_result,
            quant_result,
            llm_result
        )
        
        risk_factors = self._extract_risk_factors(
            sentiment_result,
            financial_data,
            llm_result
        )
        
        # Create result
        result = ScoringResult(
            score=final_score,
            direction=direction,
            confidence=confidence,
            sentiment_score=sentiment_score,
            yoy_trend_score=yoy_score,
            risk_adjusted_score=risk_score,
            quantitative_score=quant_score,
            llm_judge_score=llm_score,
            breakdown={
                "sentiment_analysis": sentiment_result,
                "yoy_trends": yoy_result,
                "risk_adjusted": risk_result,
                "quantitative": quant_result,
                "llm_judge": llm_result,
                "financial_data": financial_data
            },
            key_drivers=key_drivers,
            risk_factors=risk_factors,
            ticker=ticker,
            company_name=company_name,
            time_horizon=self.config.time_horizon,
            generated_at=datetime.now().isoformat()
        )
        
        self._log(f"Scoring complete for {ticker}")
        
        return result
    
    def _analyze_yoy_trends(self, finrag, financial_data: Dict) -> Dict[str, Any]:
        """Analyze year-over-year trends."""
        # Get growth metrics from yfinance
        revenue_growth = financial_data.get("revenue_growth")
        earnings_growth = financial_data.get("earnings_growth")
        
        # Query RAG for historical trends
        trend_query = "What are the revenue and profit trends over the past years? Compare year-over-year performance."
        
        try:
            result = finrag.query(trend_query, retrieval_method="tree_traversal")
            trend_text = result["answer"]
            
            # Calculate trend score
            score = 50  # Base score
            
            # Add points for positive growth
            if revenue_growth and revenue_growth > 0:
                score += min(20, revenue_growth * 100)
            elif revenue_growth and revenue_growth < 0:
                score += max(-20, revenue_growth * 100)
            
            if earnings_growth and earnings_growth > 0:
                score += min(20, earnings_growth * 100)
            elif earnings_growth and earnings_growth < 0:
                score += max(-20, earnings_growth * 100)
            
            # Analyze text for trend indicators
            trend_lower = trend_text.lower()
            if any(word in trend_lower for word in ['accelerating', 'increasing', 'strong growth']):
                score += 10
            if any(word in trend_lower for word in ['declining', 'decreasing', 'slowing']):
                score -= 10
            
            score = max(0, min(100, score))
            
            return {
                "score": score,
                "revenue_growth": revenue_growth,
                "earnings_growth": earnings_growth,
                "trend_analysis": trend_text[:500] + "..."
            }
            
        except Exception as e:
            self._log(f"Error in YoY analysis: {str(e)}", level=logging.WARNING)
            return {"score": 50, "error": str(e)}
    
    def _calculate_risk_adjusted_score(
        self,
        finrag,
        sentiment_result: Dict
    ) -> Dict[str, Any]:
        """Calculate risk-adjusted score."""
        # Query for risks
        risk_query = "What are the key risks, challenges, and uncertainties facing the company?"
        
        try:
            result = finrag.query(risk_query, retrieval_method="tree_traversal")
            risk_text = result["answer"]
            
            # Base score from sentiment
            base_score = sentiment_result["overall_score"]
            
            # Adjust for risk severity
            risk_keywords = {
                'high': ['significant risk', 'major concern', 'substantial uncertainty', 'critical'],
                'medium': ['moderate risk', 'some concern', 'potential challenge'],
                'low': ['minimal risk', 'manageable', 'mitigated']
            }
            
            risk_lower = risk_text.lower()
            risk_adjustment = 0
            
            high_risk_count = sum(1 for phrase in risk_keywords['high'] if phrase in risk_lower)
            medium_risk_count = sum(1 for phrase in risk_keywords['medium'] if phrase in risk_lower)
            low_risk_count = sum(1 for phrase in risk_keywords['low'] if phrase in risk_lower)
            
            risk_adjustment = -high_risk_count * 5 - medium_risk_count * 2 + low_risk_count * 2
            
            adjusted_score = base_score + risk_adjustment
            adjusted_score = max(0, min(100, adjusted_score))
            
            return {
                "score": adjusted_score,
                "base_score": base_score,
                "risk_adjustment": risk_adjustment,
                "risk_analysis": risk_text[:500] + "..."
            }
            
        except Exception as e:
            self._log(f"Error in risk adjustment: {str(e)}", level=logging.WARNING)
            return {"score": sentiment_result["overall_score"], "error": str(e)}
    
    def _llm_judge_score(
        self,
        finrag,
        financial_data: Dict,
        sentiment_result: Dict,
        yoy_result: Dict,
        quant_result: Dict
    ) -> Dict[str, Any]:
        """Get LLM judge assessment."""
        # Retrieve comprehensive context
        context_query = "Provide a comprehensive overview of the company's financial performance, strategic position, and future outlook."
        
        try:
            result = finrag.query(context_query, retrieval_method="collapsed_tree", top_k=15)
            context = result["answer"]
            
            # Create scoring prompt
            prompt = f"""You are an expert financial analyst. Based on the following information, provide a stock prediction score.

ANNUAL REPORT ANALYSIS:
{context[:2000]}

QUANTITATIVE METRICS:
- Revenue Growth: {financial_data.get('revenue_growth', 'N/A')}
- Profit Margin: {financial_data.get('profit_margin', 'N/A')}
- ROE: {financial_data.get('roe', 'N/A')}
- Debt to Equity: {financial_data.get('debt_to_equity', 'N/A')}
- PE Ratio: {financial_data.get('pe_ratio', 'N/A')}

PRELIMINARY SCORES:
- Sentiment Score: {sentiment_result['overall_score']:.1f}
- Trend Score: {yoy_result['score']:.1f}
- Quantitative Score: {quant_result['score']:.1f}

Provide a final score from 0-100 considering:
1. Growth trajectory and sustainability
2. Competitive positioning
3. Risk factors
4. Management quality
5. Industry trends

Respond ONLY with a number between 0 and 100."""

            judge_result = finrag.qa_model.answer_question("", prompt)
            answer = judge_result.get("answer", "50")
            
            # Extract score
            import re
            match = re.search(r'\d+(?:\.\d+)?', answer)
            if match:
                score = float(match.group())
                score = max(0, min(100, score))
            else:
                score = 50
            
            return {
                "score": score,
                "reasoning": answer,
                "context_preview": context[:500] + "..."
            }
            
        except Exception as e:
            self._log(f"Error in LLM judge: {str(e)}", level=logging.WARNING)
            # Fallback: average of other scores
            avg = (sentiment_result["overall_score"] + yoy_result["score"] + quant_result["score"]) / 3
            return {"score": avg, "error": str(e)}
    
    def _calculate_ensemble_confidence(
        self,
        sentiment_result: Dict,
        yoy_result: Dict,
        risk_result: Dict,
        quant_result: Dict,
        llm_result: Dict,
        scores: List[float]
    ) -> float:
        """Calculate overall confidence."""
        import numpy as np
        
        # Agreement score (lower std dev = higher confidence)
        score_std = np.std(scores)
        agreement = max(0, 100 - score_std * 2)
        
        # Data quality
        data_quality = quant_result.get("confidence", 50)
        
        # Sentiment confidence
        sentiment_conf = sentiment_result.get("confidence", 50)
        
        # Overall confidence
        confidence = (agreement * 0.4 + data_quality * 0.3 + sentiment_conf * 0.3)
        
        return max(0, min(100, confidence))
    
    def _extract_key_drivers(
        self,
        sentiment_result: Dict,
        quant_result: Dict,
        llm_result: Dict
    ) -> List[str]:
        """Extract key positive drivers."""
        drivers = []
        
        # From sentiment analysis
        for aspect in sentiment_result.get("aspect_scores", []):
            if aspect.get("sentiment_score", 0) > 0.5:
                drivers.append(f"{aspect['aspect']}: Strong performance")
        
        # From quantitative
        breakdown = quant_result.get("breakdown", {})
        for category, score in breakdown.items():
            if score > 75:
                drivers.append(f"{category.replace('_', ' ').title()}: Excellent metrics")
        
        return drivers[:5]  # Top 5
    
    def _extract_risk_factors(
        self,
        sentiment_result: Dict,
        financial_data: Dict,
        llm_result: Dict
    ) -> List[str]:
        """Extract key risk factors."""
        risks = []
        
        # From sentiment
        for aspect in sentiment_result.get("aspect_scores", []):
            if aspect.get("sentiment_score", 0) < -0.3:
                risks.append(f"{aspect['aspect']}: Concerns identified")
        
        # From financial data
        debt_equity = financial_data.get("debt_to_equity")
        if debt_equity and debt_equity > 2.0:
            risks.append(f"High debt-to-equity ratio: {debt_equity:.2f}")
        
        profit_margin = financial_data.get("profit_margin")
        if profit_margin and profit_margin < 0.05:
            risks.append(f"Low profit margin: {profit_margin*100:.1f}%")
        
        return risks[:5]  # Top 5

    def _log(self, message: str, level: int = logging.INFO) -> None:
        """Log helper that respects the verbose flag while surfacing warnings."""
        if level >= logging.WARNING or self.config.verbose:
            logger.log(level, message)
