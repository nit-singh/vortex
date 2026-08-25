"""
Configuration constants for the streaming pipeline.
Supports both local development and Docker deployment via environment variables.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _detect_PORTFOLIO_root() -> Path:
    """
    Detect the PORTFOLIO root directory by walking up from this file.
    The streaming folder is expected to be at VORTEX/streaming/
    PORTFOLIO is at VORTEX/SmartFolio/
    """
    current = Path(__file__).resolve().parent
    vortex_dir = current.parent
    portfolio_dir = vortex_dir / "SmartFolio"
    if (portfolio_dir / "main.py").exists():
        return portfolio_dir
    return Path(os.getenv("PORTFOLIO_ROOT", str(portfolio_dir)))


class Config:
    """
    Configuration class that supports environment variable overrides.
    Use Config.ATTR_NAME to access configuration values.
    """
    

    PORTFOLIO_DIR = Path(os.getenv("PORTFOLIO_ROOT", str(_detect_PORTFOLIO_root())))
    BASE_DIR = Path(os.getenv("BASE_DIR", str(PORTFOLIO_DIR.parent)))
    DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
    STREAMING_DIR = Path(os.getenv("STREAMING_DIR", str(BASE_DIR / "streaming")))
    OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(STREAMING_DIR / "output")))
    
    RISK_ARTIFACTS = Path(os.getenv("RISK_ARTIFACTS", str(PORTFOLIO_DIR / "risk_artifacts")))
    RISK_ARTIFACTS_DIR = RISK_ARTIFACTS 
    

    OHLCV_RAW_PATH = Path(os.getenv("OHLCV_RAW_PATH", str(DATA_DIR / "ohlcv_raw.csv")))
    STOCK_DATA_PATH = OHLCV_RAW_PATH  
    INPUT_CSV_PATH = Path(os.getenv("INPUT_CSV_PATH", str(DATA_DIR / "input.csv")))
    USER_DATA_PATH = INPUT_CSV_PATH 
    TICKERS_PATH = Path(os.getenv("TICKERS_PATH", str(PORTFOLIO_DIR / "tickers.csv")))
    TEST_IMAGES_DIR = DATA_DIR / "test_images"



BASE_DIR = Config.BASE_DIR
DATA_DIR = Config.DATA_DIR
PORTFOLIO_DIR = Config.PORTFOLIO_DIR
STREAMING_DIR = Config.STREAMING_DIR
OUTPUT_DIR = Config.OUTPUT_DIR
RISK_ARTIFACTS_DIR = Config.RISK_ARTIFACTS_DIR


STOCK_DATA_PATH = Config.STOCK_DATA_PATH
OHLCV_RAW_PATH = Config.OHLCV_RAW_PATH
USER_DATA_PATH = Config.USER_DATA_PATH
INPUT_CSV_PATH = Config.INPUT_CSV_PATH
TICKERS_PATH = Config.TICKERS_PATH
TEST_IMAGES_DIR = Config.TEST_IMAGES_DIR


MONTHLY_STOCK_DATA_DIR = OUTPUT_DIR / "monthly_stock_data"
MONTHLY_DATA_DIR = MONTHLY_STOCK_DATA_DIR  
USER_DATABASE_DIR = OUTPUT_DIR / "user_database"
USER_RISK_DATA_DIR = USER_DATABASE_DIR  
MODELS_DIR = OUTPUT_DIR / "models"
FINETUNE_CHECKPOINTS_DIR = MODELS_DIR / "finetune_checkpoints"
DEBUG_DIR = OUTPUT_DIR / "debug"
DISPLAY_STREAM_DIR = PORTFOLIO_DIR / "display_data" / "stream"


KAFKA_BROKER_STOCK = os.getenv("KAFKA_BROKER_STOCK", "localhost:9092")
KAFKA_BROKER_USER = os.getenv("KAFKA_BROKER_USER", "localhost:9093")
KAFKA_BROKER_STOCK_1 = "localhost:9094"
KAFKA_BROKER = os.getenv("KAFKA_BROKER", KAFKA_BROKER_STOCK)
KAFKA_GROUP_ID_STOCK = os.getenv("KAFKA_GROUP_STOCK", "stock-consumer-group")
KAFKA_GROUP_ID_USER = os.getenv("KAFKA_GROUP_USER", "user-consumer-group")


STOCK_DATA_TOPIC = os.getenv("STOCK_TOPIC", "stock_stream")
USER_DATA_TOPIC = os.getenv("USER_TOPIC", "user_stream")
PROCESSED_USER_TOPIC = "processed_user_data"
STOCK_DATA_TOPIC_1 = "yf_stream"


KAFKA_GROUP_STOCK = KAFKA_GROUP_ID_STOCK  
KAFKA_GROUP_USER = KAFKA_GROUP_ID_USER  


def get_rdkafka_settings(group_id: str, broker: Optional[str] = None) -> Dict[str, str]:
    """Get rdkafka settings for Pathway Kafka connector.
    
    Args:
        group_id: Consumer group ID
        broker: Kafka broker address. If None, uses KAFKA_BROKER_STOCK.
    """
    return {
        "bootstrap.servers": broker or KAFKA_BROKER_STOCK,
        "group.id": group_id,
        "session.timeout.ms": "6000",
        "auto.offset.reset": "earliest",
    }


def get_stock_rdkafka_settings() -> Dict[str, str]:
    """Get rdkafka settings for stock data consumer."""
    return get_rdkafka_settings(KAFKA_GROUP_STOCK, KAFKA_BROKER_STOCK)


def get_user_rdkafka_settings() -> Dict[str, str]:
    """Get rdkafka settings for user data consumer."""
    return get_rdkafka_settings(KAFKA_GROUP_USER, KAFKA_BROKER_USER)


STOCK_DATA_DELAY = float(os.getenv("PRODUCER_DELAY_STOCK", "20"))
PRODUCER_DELAY_STOCK = STOCK_DATA_DELAY 
USER_DATA_DELAY = float(os.getenv("PRODUCER_DELAY_USER", "200"))
PRODUCER_DELAY_USER = USER_DATA_DELAY
FINETUNE_POLL_INTERVAL = 5.0


NUM_RISK_GROUPS = 5
RISK_BOUNDARIES: List[Tuple[float, float]] = [
    (0.0, 20.0),
    (20.0, 40.0),
    (40.0, 60.0),
    (60.0, 80.0),
    (80.0, 100.0), 
]

RISK_GROUP_NAMES: List[str] = [
    "Very Conservative",
    "Conservative", 
    "Conservative-Moderate",
    "Low-Moderate",
    "Moderate-Low",
    "Moderate",
    "Moderate-High",
    "High-Moderate",
    "Moderately Aggressive",
    "Aggressive",
    "Very Aggressive",
    "Extremely Aggressive",
]

def get_risk_group(risk_score: float) -> int:
    """
    Get the risk group index (0-11) for a given risk score (0-100).
    """
    for i, (low, high) in enumerate(RISK_BOUNDARIES):
        if low <= risk_score < high:
            return i
    return NUM_RISK_GROUPS - 1


def user_risk_to_portfolio_risk(user_risk_score: float) -> float:
    """
    Convert user risk score (0-100) to portfolio risk score (0.0-1.0).
    
    The user risk score comes from the investor risk profiling system (KYC, questionnaire).
    The portfolio risk score is used for training the PORTFOLIO model.
    
    Args:
        user_risk_score: User risk score from 0 to 100
        
    Returns:
        Portfolio risk score from 0.0 to 1.0
        
    Examples:
        user_risk_to_portfolio_risk(50) -> 0.5
        user_risk_to_portfolio_risk(10) -> 0.1
        user_risk_to_portfolio_risk(100) -> 1.0
    """
    return max(0.0, min(1.0, user_risk_score / 100.0))


def portfolio_risk_to_user_risk(portfolio_risk_score: float) -> float:
    """
    Convert portfolio risk score (0.0-1.0) to user risk score (0-100).
    
    Args:
        portfolio_risk_score: Portfolio risk score from 0.0 to 1.0
        
    Returns:
        User risk score from 0 to 100
    """
    return max(0.0, min(100.0, portfolio_risk_score * 100.0))


def get_model_path(risk_group: int) -> Path:
    """Get the model checkpoint path for a risk group."""
    return MODELS_DIR / f"model_risk_{risk_group}.zip"

def get_manifest_path(risk_group: int) -> Path:
    """Get the manifest path for a risk group."""
    return MODELS_DIR / f"manifest_risk_{risk_group}.json"


FINETUNE_STEPS = 5000
PORTFOLIO_MARKET = "custom"
PORTFOLIO_HORIZON = 1
PORTFOLIO_RELATION_TYPE = "hy"


def get_risk_score_dir(base_dir: str, risk_score: float) -> str:
    """
    Get the checkpoint directory for a specific risk score.
    Matches the convention in main.py.
    
    Args:
        base_dir: Base directory (e.g., 'checkpoints')
        risk_score: Risk score 0.0-1.0
        
    Returns:
        Directory path like 'checkpoints_risk05' for risk_score=0.5
    
    Examples:
        base_dir='checkpoints', risk_score=0.5 -> 'checkpoints_risk05'
        base_dir='./checkpoints', risk_score=0.1 -> './checkpoints_risk01'
    """
    risk_tag = str(risk_score).replace('.', '')
    return f"{str(base_dir).rstrip('/')}_risk{risk_tag}"


def get_baseline_checkpoint(risk_score: float) -> Path:
    """
    Get the baseline checkpoint path for a specific risk score.
    
    Args:
        risk_score: Risk score 0.0-1.0
        
    Returns:
        Path to baseline.zip in the appropriate risk-score directory
    """
    risk_dir = get_risk_score_dir(str(PORTFOLIO_DIR / "checkpoints"), risk_score)
    return Path(risk_dir) / "baseline.zip"


BASELINE_CHECKPOINT = get_baseline_checkpoint(0.5)


def ensure_output_dirs():
    """Create all required output directories."""
    dirs = [
        OUTPUT_DIR,
        MONTHLY_STOCK_DATA_DIR,
        USER_DATABASE_DIR,
        MODELS_DIR,
        FINETUNE_CHECKPOINTS_DIR,
        DEBUG_DIR,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

ensure_output_dirs()
