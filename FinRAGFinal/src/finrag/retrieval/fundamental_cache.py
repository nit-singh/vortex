"""Fundamental Data Cache - Cache fundamental analysis data."""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class FundamentalDataCache:
    """
    Cache fundamental analysis data for stocks.
    
    Data is cached with TTL (time-to-live) to balance freshness and performance.
    Default TTL: 24 hours for daily updates.
    """
    
    def __init__(
        self,
        cache_dir: str = "data/fundamentals",
        ttl_hours: int = 24
    ):
        """
        Initialize fundamental data cache.
        
        Args:
            cache_dir: Directory to store cached data
            ttl_hours: Time-to-live for cached data in hours
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_hours = ttl_hours
    
    def get(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get cached fundamental data for ticker.
        
        Args:
            ticker: Stock ticker
            
        Returns:
            Fundamental data dictionary or None if not cached/expired
        """
        cache_file = self._get_cache_file(ticker)
        
        if not cache_file.exists():
            logger.debug(f"No cache found for {ticker}")
            return None
        
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            
            # Check if cache is expired
            cached_time = datetime.fromisoformat(data['cached_at'])
            age_hours = (datetime.now() - cached_time).total_seconds() / 3600
            
            if age_hours > self.ttl_hours:
                logger.debug(f"Cache expired for {ticker} (age: {age_hours:.1f}h)")
                return None
            
            logger.debug(f"Cache hit for {ticker} (age: {age_hours:.1f}h)")
            return data['fundamental_data']
        
        except Exception as e:
            logger.error(f"Error reading cache for {ticker}: {e}")
            return None
    
    def set(self, ticker: str, fundamental_data: Dict[str, Any]) -> bool:
        """
        Cache fundamental data for ticker.
        
        Args:
            ticker: Stock ticker
            fundamental_data: Data to cache
            
        Returns:
            True if successful
        """
        cache_file = self._get_cache_file(ticker)
        
        try:
            cache_entry = {
                'ticker': ticker,
                'cached_at': datetime.now().isoformat(),
                'fundamental_data': fundamental_data
            }
            
            with open(cache_file, 'w') as f:
                json.dump(cache_entry, f, indent=2)
            
            logger.debug(f"Cached fundamental data for {ticker}")
            return True
        
        except Exception as e:
            logger.error(f"Error caching data for {ticker}: {e}")
            return False
    
    def delete(self, ticker: str) -> bool:
        """
        Delete cached data for ticker.
        
        Args:
            ticker: Stock ticker
            
        Returns:
            True if successful
        """
        cache_file = self._get_cache_file(ticker)
        
        if cache_file.exists():
            try:
                cache_file.unlink()
                logger.debug(f"Deleted cache for {ticker}")
                return True
            except Exception as e:
                logger.error(f"Error deleting cache for {ticker}: {e}")
                return False
        
        return False
    
    def clear_all(self) -> int:
        """
        Clear all cached data.
        
        Returns:
            Number of files deleted
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except Exception as e:
                logger.error(f"Error deleting {cache_file}: {e}")
        
        logger.info(f"Cleared {count} cached entries")
        return count
    
    def _get_cache_file(self, ticker: str) -> Path:
        """Get cache file path for ticker."""
        # Sanitize ticker for filename
        safe_ticker = ticker.replace('/', '_').replace('\\', '_')
        return self.cache_dir / f"{safe_ticker}.json"
    
    def get_cache_info(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata about cached entry.
        
        Args:
            ticker: Stock ticker
            
        Returns:
            Cache metadata or None
        """
        cache_file = self._get_cache_file(ticker)
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            
            cached_time = datetime.fromisoformat(data['cached_at'])
            age_hours = (datetime.now() - cached_time).total_seconds() / 3600
            is_expired = age_hours > self.ttl_hours
            
            return {
                'ticker': ticker,
                'cached_at': data['cached_at'],
                'age_hours': age_hours,
                'is_expired': is_expired,
                'file_size': cache_file.stat().st_size
            }
        
        except Exception as e:
            logger.error(f"Error getting cache info for {ticker}: {e}")
            return None
