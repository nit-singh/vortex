# Streaming Pipeline for SmartFolio Portfolio Management

A Kafka-Pathway based streaming system for real-time portfolio management with risk-adaptive fine-tuning.

## Quick Start

### 1. Start Kafka Services

```bash
cd streaming/docker
docker-compose -f docker-compose.kafka.yml up
```

This will start:
- Zookeeper (port 2181)
- Kafka brokers (ports 9092, 9093, 9094)

### 2. Run Stock Data Producer

From the project root (`/home/mksilver30/VORTEX/`):

```bash
cd streaming
python -m streaming.producer.stock_producer
```

This will stream stock OHLCV data from `/data/ohlcv_raw.csv` to the `stock_stream` topic.

### 3. Run Stock Data Consumer

From the project root:

```bash
cd streaming
python -m streaming.consumer.stock_consumer
```

This will:
- Consume stock data from Kafka
- Calculate display features (daily_change, trend_1m, volatility, risk_label)
- Save daily CSVs to `/portfolio_agent/display_data/stream/`
- Buffer monthly data and trigger fine-tuning on month changes

### 4. Run User Data Producer (Optional)

```bash
cd streaming
python -m streaming.producer.user_producer
```

Streams user KYC documents from `/data/input.csv` to the `user_stream` topic.

### 5. Run User Data Consumer (Optional)

```bash
cd streaming
python -m streaming.consumer.kyc_consumer
```

Processes user documents with OCR, extracts information, and calculates risk scores.

## File Structure

```
streaming/
├── __init__.py
├── config.py                 # Configuration constants
├── run_all.py               # Main entry point
├── shared/
│   ├── __init__.py
│   ├── locks.py             # Thread-safe locks
│   ├── state.py             # Shared state management
│   └── utils.py             # Utility functions
├── producer/
│   ├── __init__.py
│   ├── stock_producer.py    # OHLCV data producer
│   ├── user_producer.py     # User data producer
│   └── run_producers.py     # Producer manager
└── consumer/
    ├── __init__.py
    ├── schemas.py           # Pathway schemas
    ├── stock_consumer.py    # Stock data consumer
    ├── user_consumer.py     # User data consumer
    ├── finetune_manager.py  # 12 fine-tuning threads
    └── run_consumers.py     # Consumer manager
```