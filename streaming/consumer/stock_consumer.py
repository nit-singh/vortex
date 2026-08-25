"""
Stock Data Consumer with Pathway-Kafka Integration.

Uses Pathway's Kafka connector to consume stock OHLCV data,
detect month changes, buffer data, and save to CSV for fine-tuning.
"""

import json
import logging
import os
import threading
from argparse import Namespace
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pathway as pw
from pathway.io import kafka as pw_kafka

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from streaming.config import (
    KAFKA_BROKER_STOCK,
    STOCK_DATA_TOPIC,
    KAFKA_GROUP_STOCK,
    MONTHLY_DATA_DIR,
    PORTFOLIO_DIR,
    DISPLAY_STREAM_DIR,
)
from streaming.shared.state import SharedState
from streaming.consumer.schemas import StockDataSchema

from SmartFolio.gen_data.display_data import  get_sector_map

logger = logging.getLogger(__name__)

# Constants for display data calculation
DISPLAY_WINDOW_SIZE = 22  # 22 days window (21 days lookback + current day)
TREND_LOOKBACK_DAYS = 21
TRADING_DAYS_PER_YEAR = 252

# Sector map cache (loaded once)
_sector_map: Optional[Dict[str, str]] = None
_industry_map: Optional[Dict[str, str]] = None
_sector_map_lock = threading.Lock()


def _load_sector_map(tickers):
    """
    Load sector map from cache file.
    Returns empty dict if not found.
    """
    global _sector_map, _industry_map
    
    with _sector_map_lock:
        if _sector_map is not None and _industry_map is not None:
            return _sector_map, _industry_map   
        else:
            _sector_map, _industry_map = get_sector_map(tickers)
            return _sector_map, _industry_map
        


class DisplayDataBuffer:
    """
    Sliding window buffer for calculating display features.
    
    Maintains a 22-day window of raw OHLCV data across all tickers.
    When a new day arrives with enough history, calculates display features
    (daily_change, trend_1m, volatility, risk_label) and saves to daily CSV.
    """
    
    def __init__(self, window_size: int = DISPLAY_WINDOW_SIZE):
        self.window_size = window_size
        # OrderedDict: date -> {ticker: {open, high, low, close, volume, prev_close}}
        self._window: OrderedDict[str, Dict[str, Dict[str, float]]] = OrderedDict()
        self._lock = threading.Lock()
        
        # Ensure output directory exists
        DISPLAY_STREAM_DIR.mkdir(parents=True, exist_ok=True)
    
    def add_day(self, date: str, stock_data: Dict[str, Dict[str, float]]) -> Optional[str]:
        """
        Add a day's data to the sliding window.
        
        Args:
            date: Date string (YYYY-MM-DD)
            stock_data: Dict mapping ticker -> {open, high, low, close, volume, ...}
            
        Returns:
            Path to saved display CSV if features were calculated, None otherwise
        """
        with self._lock:
            # Skip if date already exists
            if date in self._window:
                # logger.debug(f"Date {date} already in display buffer, skipping")
                return None
            
            # Add new day
            self._window[date] = stock_data
            
            # Slide window if exceeded
            while len(self._window) > self.window_size:
                oldest_date = next(iter(self._window))
                del self._window[oldest_date]
                logger.debug(f"Removed {oldest_date} from display window")
            
            # Calculate and save if we have enough data
            if len(self._window) >= self.window_size:
                return self._calculate_and_save_display(date)
            else:
                logger.info(f"Display buffer warming up: {len(self._window)}/{self.window_size} days")
                return None
    
    def _calculate_and_save_display(self, current_date: str) -> Optional[str]:
        """
        Calculate display features for the current date and save to CSV.
        
        Returns:
            Path to saved CSV file
        """
        try:
            # Get all dates in order
            dates = list(self._window.keys())
            
            # Get all tickers that appear in the current day
            current_data = self._window[current_date]
            tickers = list(current_data.keys())
            
            if not tickers:
                # logger.warning(f"No tickers found for {current_date}")
                return None
            
            # Load sector map
            sector_map, industry_map = _load_sector_map(tickers)
            
            # Build DataFrame for calculations
            rows = []
            for ticker in tickers:
                # Collect data for this ticker across the window
                ticker_closes = []
                ticker_returns = []
                
                prev_close = None
                for d in dates:
                    day_data = self._window.get(d, {})
                    ticker_data = day_data.get(ticker)
                    
                    if ticker_data is not None:
                        close = ticker_data.get("close", ticker_data.get("Close", 0))
                        ticker_closes.append(close)
                        
                        if prev_close is not None and prev_close > 0:
                            daily_ret = (close / prev_close) - 1
                            ticker_returns.append(daily_ret)
                        
                        prev_close = close
                
                # Skip ticker if insufficient data
                if len(ticker_closes) < self.window_size:
                    # logger.debug(f"Skipping {ticker}: only {len(ticker_closes)} days of data")
                    continue
                
                # Get current day's OHLCV
                curr = current_data[ticker]
                close = curr.get("close", curr.get("Close", 0))
                open_price = curr.get("open", curr.get("Open", 0))
                high = curr.get("high", curr.get("High", 0))
                low = curr.get("low", curr.get("Low", 0))
                volume = curr.get("volume", curr.get("Volume", 0))
                prev_close_val = curr.get("prev_close", curr.get("Prev Close", ticker_closes[-2] if len(ticker_closes) >= 2 else close))
                
                # Calculate features
                # 1. Daily Change
                daily_change = (close / prev_close_val - 1) if prev_close_val and prev_close_val > 0 else 0.0
                
                # 2. Trend 1M (21-day trend)
                if len(ticker_closes) >= TREND_LOOKBACK_DAYS:
                    first_close = ticker_closes[-(TREND_LOOKBACK_DAYS + 1)]
                    trend_1m = (close - first_close) / first_close if first_close > 0 else 0.0
                else:
                    trend_1m = 0.0
                
                # 3. Volatility (annualized std of daily returns)
                if len(ticker_returns) >= 2:
                    volatility = np.std(ticker_returns) * np.sqrt(TRADING_DAYS_PER_YEAR)
                else:
                    volatility = 0.0
                
                # Get sector
                sector = sector_map.get(ticker, "Unknown")
                insustry = industry_map.get(ticker, "Unknown")
                
                rows.append({
                    "dt": current_date,
                    "kdcode": ticker,
                    "sector": sector,
                    "industry": insustry,
                    "close": close,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "prev_close": prev_close_val,
                    "volume": volume,
                    "daily_change": daily_change,
                    "trend_1m": trend_1m,
                    "volatility": volatility,
                })
            
            if not rows:
                # logger.warning(f"No valid rows to save for {current_date}")
                return None
            
            df = pd.DataFrame(rows)
            
            # Calculate sector volatility and risk labels
            sector_vol = df.groupby("sector")["volatility"].mean().to_dict()
            df["sector_volatility"] = df["sector"].map(sector_vol)
            
            # Risk ratio and label
            df["risk_ratio"] = df["volatility"] / (df["sector_volatility"] + 1e-6)
            
            def assign_risk_label(ratio):
                if ratio >= 1.2:
                    return "High"
                elif ratio <= 0.8:
                    return "Low"
                else:
                    return "Medium"
            
            df["risk_label"] = df["risk_ratio"].apply(assign_risk_label)
            
            # Drop intermediate column
            df = df.drop(columns=["risk_ratio"])
            
            # Save to CSV
            csv_path = DISPLAY_STREAM_DIR / f"{current_date}.csv"
            df.to_csv(csv_path, index=False)
            
            logger.info(f"Saved display data for {current_date}: {len(df)} tickers")
            return str(csv_path)
            
        except Exception as e:
            # logger.error(f"Error calculating display features for {current_date}: {e}", exc_info=True)
            return None
    
    def get_window_size(self) -> int:
        """Get current number of days in window."""
        with self._lock:
            return len(self._window)
    
    def get_dates_in_window(self) -> List[str]:
        """Get list of dates currently in the window."""
        with self._lock:
            return list(self._window.keys())


# Global display buffer instance
_display_buffer: Optional[DisplayDataBuffer] = None
_display_buffer_lock = threading.Lock()


def get_display_buffer() -> DisplayDataBuffer:
    """Get or create the global display buffer instance."""
    global _display_buffer
    with _display_buffer_lock:
        if _display_buffer is None:
            _display_buffer = DisplayDataBuffer()
        return _display_buffer

# Track active fine-tuning threads
_finetune_lock = threading.Lock()
_finetune_thread: Optional[threading.Thread] = None


def _build_default_args(risk_score: float = 0.5) -> Namespace:
    """
    Build default arguments for fine-tuning, matching main.py defaults.
    
    Args:
        risk_score: Risk score (0.0-1.0) to configure checkpoint paths
        
    Returns:
        Namespace with all required arguments
    """
    # Import here to avoid circular imports
    from streaming.config import get_risk_score_dir, get_baseline_checkpoint
    
    args = Namespace()
    
    # Basic settings
    args.market = "custom"
    args.horizon = "1"
    args.relation_type = "hy"
    args.policy = "HGAT"
    args.model_name = "SmartFolio"
    args.seed = 123
    
    # Device
    import torch
    args.device = "cuda:0" if torch.cuda.is_available() else "cpu"
    
    # Graph relation flags
    args.ind_yn = True
    args.pos_yn = True
    args.neg_yn = True
    args.multi_reward = True
    
    # Training parameters
    args.irl_epochs = 50
    args.rl_timesteps = 10000
    args.fine_tune_steps = 5000
    args.batch_size = 512
    args.n_steps = 2048
    args.max_epochs = 10
    args.num_expert_trajectories = 700
    args.lookback = 20
    
    # Risk settings - use the provided risk_score
    args.risk_score = risk_score
    args.dd_base_weight = 1.0
    args.dd_risk_factor = 1.0
    
    # PTR settings
    args.ptr_mode = True
    args.ptr_coef = 0.3
    args.ptr_memory_size = 1000
    args.ptr_priority_type = "max"
    
    # Paths - use dynamic risk-score-based directories (matching main.py convention)
    args.save_dir = get_risk_score_dir(str(PORTFOLIO_DIR / "checkpoints"), risk_score)
    args.baseline_checkpoint = str(get_baseline_checkpoint(risk_score))
    args.tickers_file = str(PORTFOLIO_DIR / "tickers.csv")
    args.expert_cache_path = str(PORTFOLIO_DIR / "dataset_default" / "expert_cache")
    args.finrag_weights_path = None
    args.finrag_prior = None
    
    # Promotion criteria
    args.promotion_min_sharpe = 0.5
    args.promotion_max_drawdown = 0.2
    
    # Resume settings
    args.resume_model_path = None
    args.reward_net_path = None
    
    # Streaming settings
    args.stream = None  # Will be set by caller if using streaming
    
    # Input dimension (will be auto-detected)
    args.input_dim = 6
    
    return args


def _run_monthly_finetune(saved_csv_path: str, year_month: str):
    """
    Run monthly fine-tuning in the current thread.
    This function is called from a separate thread.
    
    Args:
        saved_csv_path: Path to the saved monthly CSV file
        year_month: The year-month string (e.g., "2024-12")
    """
    try:
        # logger.info(f"Starting monthly fine-tune for {year_month} using data from {saved_csv_path}")
        
        # Change to SmartFolio directory for imports
        original_cwd = os.getcwd()
        os.chdir(str(PORTFOLIO_DIR))
        
        # Add SmartFolio to path
        if str(PORTFOLIO_DIR) not in sys.path:
            sys.path.insert(0, str(PORTFOLIO_DIR))
        
        # Import required modules from SmartFolio
        from SmartFolio.main import fine_tune_month
        from SmartFolio.utils.risk_profile import build_risk_profile
        from streaming.shared.locks import StreamingLocks
        import pickle
        
        # Build default args
        args = _build_default_args()
        
        # Build risk profile
        args.risk_profile = build_risk_profile(args.risk_score)
        
        # Auto-detect num_stocks from existing pkl files
        data_dir = PORTFOLIO_DIR / "dataset_default" / f"data_train_predict_{args.market}" / f"{args.horizon}_{args.relation_type}"
        sample_files = [f for f in os.listdir(data_dir) if f.endswith('.pkl')] if data_dir.exists() else []
        
        if sample_files:
            sample_path = data_dir / sample_files[0]
            with open(sample_path, 'rb') as f:
                sample_data = pickle.load(f)
            args.num_stocks = sample_data['features'].shape[0]
            # logger.info(f"Auto-detected num_stocks: {args.num_stocks}")
        else:
            # logger.warning("No existing pkl files found, cannot determine num_stocks")
            os.chdir(original_cwd)
            return
        
        # Set resume model path if baseline exists
        if os.path.exists(args.baseline_checkpoint):
            args.resume_model_path = args.baseline_checkpoint
            # logger.info(f"Using baseline checkpoint: {args.resume_model_path}")
        
        # Load replay buffer if available
        replay_buffer = []
        buffer_path = os.path.join(args.save_dir, f"replay_buffer_{args.market}.pkl")
        if os.path.exists(buffer_path):
            with open(buffer_path, "rb") as f:
                replay_buffer = pickle.load(f)
            # logger.info(f"Loaded replay buffer with {len(replay_buffer)} samples")
        
        # Get the streaming lock for CSV access
        try:
            stream_lock = StreamingLocks().csv_write_lock
        except Exception as e:
            # logger.warning(f"Could not get streaming lock: {e}, proceeding without lock")
            stream_lock = None
        
        # Run fine-tuning with stream parameter for reading from streaming CSV
        checkpoint, new_samples = fine_tune_month(
            args,
            replay_buffer=replay_buffer,
            fetch_new_data=True,  # This will fetch data and build pkl files
            stream=stream_lock,   # Pass the lock for streaming CSV access
        )
        
        # logger.info(f"Monthly fine-tuning complete. Checkpoint: {checkpoint}")
        
        # Update replay buffer
        if new_samples:
            replay_buffer.extend(new_samples)
            max_buffer = args.ptr_memory_size
            if len(replay_buffer) > max_buffer:
                replay_buffer = replay_buffer[-max_buffer:]
            with open(buffer_path, "wb") as f:
                pickle.dump(replay_buffer, f)
            # logger.info(f"Persisted replay buffer ({len(replay_buffer)} samples) to {buffer_path}")
        
        os.chdir(original_cwd)
        
    except Exception as e:
        # logger.error(f"Error during monthly fine-tuning: {e}", exc_info=True)
        try:
            os.chdir(original_cwd)
        except:
            pass


def trigger_finetune_async(saved_csv_path: str, year_month: str):
    """
    Trigger monthly fine-tuning in an independent thread.
    Only one fine-tuning can run at a time.
    """
    global _finetune_thread
    # logger.info(f"Triggering fine-tune for {year_month} with data from {saved_csv_path}")
    with _finetune_lock:
        # Check if a fine-tuning is already running
        if _finetune_thread is not None and _finetune_thread.is_alive():
            # logger.warning(f"Fine-tuning already in progress, skipping trigger for {year_month}")
            return False
        
        # Start new fine-tuning thread
        _finetune_thread = threading.Thread(
            target=_run_monthly_finetune,
            args=(saved_csv_path, year_month),
            name=f"finetune-{year_month}",
            daemon=True,
        )
        _finetune_thread.start()
        # logger.info(f"Started fine-tuning thread for {year_month}")
        return True


@pw.udf
def extract_date(data_str: str) -> str:
    """Extract date from stock data JSON string."""
    try:
        data = json.loads(data_str)
        return data.get("date", "")
    except:
        return ""


@pw.udf
def extract_year_month(date_str: str) -> str:
    """Extract year-month (YYYY-MM) from date string."""
    
    print("RECEIVED STOCK DATA FOR DATE: ", date_str)
    try:
        if not date_str:
            return ""
        # Handle various date formats
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"]:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m")
            except ValueError:
                continue
        return ""
    except:
        return ""


@pw.udf
def process_stock_row(date: str, data_str: str) -> str:
    """
    Process a stock data row and buffer it.
    Returns status message.
    """
    try:
        # Parse the data
        data = json.loads(data_str)
        
        # Get shared state
        state = SharedState()
        buffer = state.stock_buffer
        
        # Add to buffer
        month_changed, saved_path = buffer.add_row(date, data)
        
        # Add to display buffer for daily feature calculation
        display_buffer = get_display_buffer()
        display_csv_path = display_buffer.add_day(date, data)
        
        status_parts = []
        
        if month_changed and saved_path:
            # Trigger fine-tuning with the saved month's data
            # Extract year_month from saved_path (e.g., "/path/to/2024-12.csv" -> "2024-12")
            saved_filename = os.path.basename(saved_path)  # "2024-12.csv"
            saved_year_month = saved_filename.replace(".csv", "")  # "2024-12"
            
            # Trigger fine-tuning in an independent thread
            trigger_finetune_async(saved_path, saved_year_month)
            
            status_parts.append(f"Month changed. Saved to {saved_path}. Fine-tune triggered for {saved_year_month}.")
        else:
            status_parts.append(f"Buffered data for {date}")
        
        if display_csv_path:
            status_parts.append(f"Display data saved to {display_csv_path}")
        
        return " | ".join(status_parts)
        
    except Exception as e:
        # logger.error(f"Error processing stock row: {e}")
        return f"Error: {str(e)}"


class StockConsumer:
    """
    Pathway-based Kafka consumer for stock OHLCV data.
    
    Consumes from stock_data topic, detects month changes,
    buffers data, and triggers fine-tuning on month boundaries.
    """
    
    def __init__(
        self,
        broker: str = KAFKA_BROKER_STOCK,
        topic: str = STOCK_DATA_TOPIC,
        group_id: str = KAFKA_GROUP_STOCK,
    ):
        self.broker = broker
        self.topic = topic
        self.group_id = group_id
        self._state = SharedState()
    
    def build_pipeline(self) -> pw.Table:
        """
        Build the Pathway pipeline for stock data consumption.
        
        Returns:
            Pathway Table with processed stock data
        """
        # Kafka input connector
        input_table = pw_kafka.read(
            rdkafka_settings={
                "bootstrap.servers": self.broker,
                "group.id": self.group_id,
                "auto.offset.reset": "earliest",
            },
            topic=self.topic,
            format="json",
            schema=StockDataSchema,
        )
        
        # Process each row
        processed = input_table.select(
            date=pw.this.date,
            year_month=extract_year_month(pw.this.date),
            data=pw.this.data,
            status=process_stock_row(pw.this.date, pw.this.data),
        )
        
        return processed
    
    def run(self):
        """Start the Pathway runtime for stock consumption."""
        # logger.info(f"Starting Stock Consumer on {self.topic}")
        
        # Build pipeline
        processed = self.build_pipeline()
        
        # Optional: Output to console for debugging
        pw.io.null.write(processed)  # Suppress output, side effects handled in UDF
        
        # Run Pathway
        pw.run(monitoring_level=pw.MonitoringLevel.NONE)


def create_stock_consumer_pipeline() -> pw.Table:
    """
    Create and return the stock consumer pipeline.
    
    This is useful for integration with other Pathway pipelines.
    """
    consumer = StockConsumer()
    return consumer.build_pipeline()


def run_stock_consumer():
    """Main entry point for stock consumer."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    consumer = StockConsumer()
    consumer.run()


if __name__ == "__main__":
    run_stock_consumer()
