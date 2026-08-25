"""
Sentiment analysis for financial text using LLM.
"""
from typing import Dict, Any, List
import re
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor


class SentimentAnalyzer:
    """Analyze sentiment of financial text using LLM."""
    
    def __init__(self, qa_model):
        """
        Initialize sentiment analyzer.
        
        Args:
            qa_model: Question-answering model (OpenAI)
        """
        self.qa_model = qa_model
    
    def analyze_multi_aspect_sentiment(
        self,
        finrag,
        aspects: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze sentiment across multiple financial aspects using parallel queries.
        
        Args:
            finrag: FinRAG instance with loaded documents
            aspects: List of aspects to analyze, each with 'name', 'question', 'weight'
        
        Returns:
            Dictionary with aspect scores and overall sentiment
        """
        # Run parallel queries using asyncio
        aspect_details = asyncio.run(self._analyze_aspects_parallel(finrag, aspects))
        
        # Calculate aspect scores
        aspect_scores = [
            detail.get("weighted_score", 0)
            for detail in aspect_details
            if "error" not in detail
        ]
        
        # Calculate overall sentiment score
        total_score = sum(aspect_scores)
        
        # Normalize to 0-100 scale
        # Assuming sentiment_score ranges from -1 to 1
        normalized_score = ((total_score + 1) / 2) * 100
        
        return {
            "overall_score": max(0, min(100, normalized_score)),
            "raw_score": total_score,
            "aspect_scores": aspect_details,
            "confidence": self._calculate_overall_confidence(aspect_details)
        }
    
    async def _analyze_aspects_parallel(
        self,
        finrag,
        aspects: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze all aspects in parallel using asyncio.
        
        Args:
            finrag: FinRAG instance
            aspects: List of aspects to analyze
            
        Returns:
            List of aspect detail dictionaries
        """
        # Create tasks for all aspects
        tasks = [
            self._analyze_single_aspect(finrag, aspect)
            for aspect in aspects
        ]
        
        # Run all tasks concurrently
        aspect_details = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results and handle exceptions
        processed_details = []
        for i, result in enumerate(aspect_details):
            if isinstance(result, Exception):
                print(f"Error analyzing aspect {aspects[i]['name']}: {str(result)}")
                processed_details.append({
                    "aspect": aspects[i]["name"],
                    "error": str(result),
                    "weighted_score": 0
                })
            else:
                processed_details.append(result)
        
        return processed_details
    
    async def _analyze_single_aspect(
        self,
        finrag,
        aspect: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze a single aspect asynchronously.
        
        Args:
            finrag: FinRAG instance
            aspect: Aspect dictionary with 'name', 'question', 'weight'
            
        Returns:
            Aspect detail dictionary
        """
        # Run blocking finrag.query in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            result = await loop.run_in_executor(
                executor,
                lambda: finrag.query(
                    aspect["question"],
                    retrieval_method="tree_traversal"
                )
            )
        
        # Analyze sentiment of the answer
        sentiment_score = self._extract_sentiment_score(
            result["answer"],
            aspect["name"]
        )
        
        # Get retrieval confidence
        retrieval_confidence = self._calculate_retrieval_confidence(
            result.get("retrieved_nodes", [])
        )
        
        # Weighted score
        weighted_score = sentiment_score * aspect["weight"] * retrieval_confidence
        
        return {
            "aspect": aspect["name"],
            "question": aspect["question"],
            "sentiment_score": sentiment_score,
            "retrieval_confidence": retrieval_confidence,
            "weighted_score": weighted_score,
            "weight": aspect["weight"],
            "answer_preview": result["answer"][:200] + "..."
        }
    
    def _extract_sentiment_score(self, text: str, aspect: str) -> float:
        """
        Extract sentiment score from text using keyword analysis and LLM.
        Returns score from -1 (bearish) to +1 (bullish).
        """
        # Use LLM to extract sentiment
        prompt = f"""Analyze the following text about {aspect} and provide a sentiment score.

Text: {text[:1000]}

Provide a sentiment score from -1 (very bearish) to +1 (very bullish) based on:
- Positive indicators: growth, improvement, success, expansion, strength
- Negative indicators: decline, loss, risk, challenge, weakness

Respond with ONLY a number between -1 and 1."""

        try:
            response = self.qa_model.answer_question("", prompt)
            answer = response.get("answer", "0")
            
            # Extract number from response
            match = re.search(r'-?\d+\.?\d*', answer)
            if match:
                score = float(match.group())
                return max(-1, min(1, score))  # Clamp to [-1, 1]
            
        except Exception as e:
            print(f"Error in sentiment extraction: {str(e)}")
        
        # Fallback: keyword-based sentiment
        return self._keyword_sentiment(text)
    
    def _keyword_sentiment(self, text: str) -> float:
        """Fallback keyword-based sentiment analysis."""
        text_lower = text.lower()
        
        positive_keywords = [
            'growth', 'increase', 'profit', 'strong', 'positive', 'expansion',
            'improvement', 'success', 'gain', 'revenue', 'up', 'higher', 'exceed',
            'robust', 'solid', 'momentum', 'optimistic', 'opportunity'
        ]
        
        negative_keywords = [
            'decline', 'decrease', 'loss', 'weak', 'negative', 'risk',
            'challenge', 'concern', 'down', 'lower', 'miss', 'pressure',
            'uncertainty', 'headwind', 'volatility', 'difficult'
        ]
        
        positive_count = sum(1 for kw in positive_keywords if kw in text_lower)
        negative_count = sum(1 for kw in negative_keywords if kw in text_lower)
        
        total = positive_count + negative_count
        if total == 0:
            return 0.0
        
        sentiment = (positive_count - negative_count) / total
        return sentiment
    
    def _calculate_retrieval_confidence(self, nodes: List[Dict]) -> float:
        """Calculate confidence from retrieval scores."""
        if not nodes:
            return 0.5  # Default confidence
        
        # Average of top retrieval scores
        scores = [node.get("score", 0) for node in nodes[:5]]
        if not scores:
            return 0.5
        
        avg_score = sum(scores) / len(scores)
        return max(0.3, min(1.0, avg_score))  # Clamp to [0.3, 1.0]
    
    def _calculate_overall_confidence(self, aspect_details: List[Dict]) -> float:
        """Calculate overall confidence from aspect details."""
        confidences = [
            aspect.get("retrieval_confidence", 0.5)
            for aspect in aspect_details
            if "error" not in aspect
        ]
        
        if not confidences:
            return 50.0
        
        return (sum(confidences) / len(confidences)) * 100
