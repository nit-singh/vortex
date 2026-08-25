<h1 align="center">Vortex - Integrated Financial Platform for Portfolio Management</h1>

## Table of Contents
- [Introduction](#introduction)
- [Key Features](#key-features)
  - [1. Portfolio Management (SmartFolio)](#1-portfolio-management-smartfolio)
  - [2. Financial RAG (FinRAGFinal)](#2-financial-rag-finragfinal)
  - [3. KYC Verification](#3-kyc-verification)
  - [4. Real-time Streaming Pipeline](#4-real-time-streaming-pipeline)
- [Architecture Overview](#architecture-overview)
- [Installation and Setup](#installation-and-setup)
  - [1. Prerequisites](#1-prerequisites)
  - [2. Clone Repository](#2-clone-repository)
  - [3. Environment Variables](#3-environment-variables)
  - [4. Running with Docker](#4-running-with-docker)
  - [5. Local Development Setup](#5-local-development-setup)
- [API Endpoints](#api-endpoints)
- [Directory Structure](#directory-structure)

## Introduction

Vortex is an integrated financial platform that combines reinforcement learning-based portfolio optimization, retrieval-augmented generation for financial research, and comprehensive KYC verification into a unified system. Built on Pathway's real-time data processing capabilities and leveraging modern LLM architectures, Vortex addresses critical challenges in automated portfolio management including risk-adaptive allocation, explainable AI decisions, and regulatory compliance through robust KYC workflows. The platform features a Next.js dashboard for user interaction, a Flask orchestration layer, and microservices for each specialized domain.

## Key Features

### 1. **Portfolio Management (SmartFolio)**
- **Challenge:** Traditional portfolio systems lack adaptability to individual risk profiles and market dynamics.
- **Solution:** PPO-based reinforcement learning with Heterogeneous Graph Attention Networks (HGAT) enables dynamic portfolio allocation that adapts to market conditions and user risk tolerance for 
- **Monthly Fine-tuning:** Policy Transfer Regularization (PTR) enables continuous model improvement without catastrophic forgetting.
- **Explainability:** LangGraph-based agents generate human-readable explanations for portfolio decisions.

### 2. **Financial RAG (FinRAG)**
- **Challenge:** Generic retrieval systems fail to capture domain-specific nuances in financial documents.
- **Solution:** Pathway-powered vector store with real-time document ingestion and specialized retrieval tools for financial analysis.
- **Multi-Source Retrieval:** Aggregates data from news articles, SEC filings, and fundamental data sources.
- **Ensemble Scoring:** Combines sentiment analysis, technical indicators, and fundamental metrics for stock scoring.
- **MCP Server:** Model Context Protocol server enables agentic integrations with external tools.

### 3. **KYC Verification**
- **Challenge:** Manual document verification is slow, error-prone, and lacks consistency.
- **Solution:** Automated document parsing using PaddleOCR with cross-document validation and ML-based risk scoring.
- **Document Support:** PAN Card, Aadhaar Card, and ITR documents with automatic field extraction.
- **Video Verification:** Selfie video analysis with face matching (Aadhaar-to-PAN, PAN-to-Video) and liveness detection.
- **Risk Scoring:** ML model evaluates investor risk based on questionnaire responses and financial data.

### 4. **Real-time Streaming Pipeline**
- **Challenge:** Batch processing introduces latency in portfolio updates and market data ingestion.
- **Solution:** Kafka-based streaming architecture enables real-time stock data ingestion and processing.
- **Stock Data Producer:** Streams OHLCV data from multiple sources to Kafka topics.
- **Consumer Pipeline:** Calculates display features (daily change, trend, volatility) and triggers monthly fine-tuning.
- **User Stream:** Processes user onboarding data for KYC workflows.

## Installation and Setup

### 1. Prerequisites

1. Install Docker & Docker Compose:
```bash

sudo apt-get update
sudo apt-get install docker.io docker-compose

```

You can install Docker using the platform package manager (example commands below), then bring up the full stack with `docker compose up --build`.

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin

```
2. Install Node.js 18+:
```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install 18
nvm use 18

```

3. Install Python 3.10+:
```bash

sudo apt-get install python3.10 python3.10-venv python3-pip


```

4. Create and activate virtual environment:
```bash
python3.11 -m venv venv
source venv/bin/activate
```

5. Install project dependencies for each module:
```bash

pip install -r requirements.txt


cd flask_server
pip install -r requirements.txt
cd ..

cd KYC
pip install -r KYC_requirements.txt
pip install -r VV_requirements.txt
cd ..


cd SmartFolio
pip install -r requirements.txt
cd ..

cd FinRAGFinal
pip install -r requirements.txt
cd ..

cd dashboard
npm i
cd ..
```

6. Copy required data files from provided zip:

The following folders contain large data files and pre-trained models that are not included in the repository. Extract them from the provided `vortex_data.zip` file.

```bash
# Extract the data zip file (provided separately)
unzip vortex_data.zip
```

**Required folders to copy:**

| Folder | Description | Destination |
|--------|-------------|-------------|
| `finrag_tree/` | RAPTOR tree indexes and vector stores | `FinRAGFinal/finrag_tree/` |
| `dataset_default/` | Training datasets and expert cache (~920MB) | `SmartFolio/dataset_default/` |
| `checkpoints_risk*/` | Pre-trained model checkpoints for each risk level | `SmartFolio/checkpoints_risk*/` |
| `data/` | Raw OHLCV data files | `data/` |

After extraction, the folder structure should include:
```
Vortex/
├── data/
│   └── ohlcv_raw_1.csv
├── FinRAGFinal/
│   └── finrag_tree/
│       ├── chroma_vectorstore/
│       ├── pathway_vectorstore/
│       ├── tree.json
│       └── tree.pkl
└── SmartFolio/
    ├── checkpoints_risk01/
    ├── checkpoints_risk03/
    ├── checkpoints_risk05/
    ├── checkpoints_risk07/
    ├── checkpoints_risk09/
    └── dataset_default/
        ├── corr/
        ├── custom/
        ├── daily_stock_custom/
        ├── data_train_predict_custom/
        ├── expert_cache/
        └── index_data/
```

### 2. Clone Repository

```bash
git clone https://github.com/aupc2061/Vortex.git
cd Vortex
```

### 3. Environment Variables

Create a `.env` file in the root directory with the following parameters:

```
# OpenAI API Key
OPENAI_API_KEY=your_openai_api_key

# Pathway License Keys
PW_LKEY=your_pathway_license_key
PW_LIKEY=your_pathway_license_key

# Encryption Key (for sensitive data)
ENCRYPTION_KEY=your_encryption_key

# MongoDB Configuration
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?appName=AppName
MONGODB_DB_NAME=kyc_app

# Flask Configuration
FLASK_ENV=development
FLASK_HOST=0.0.0.0
FLASK_PORT=8000
FLASK_DEBUG=true

# Security
SECRET_KEY=your_secret_key

# Langfuse (Observability)
LANGFUSE_ENV=default
LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_SECRET_KEY=your_langfuse_secret_key

# Service Ports
COMBINED_API_PORT=8000
PAYLOAD_API_PORT=8001
KYCV_MCP_PORT=8123
RISK_MCP_PORT=8124

# Cloudinary Configuration (for document storage)
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# Portfolio API URL
PORTFOLIO_API_URL=http://localhost:8080
```

### 4. Running with Docker

This is the recommended method for running the complete platform.

```bash
docker-compose up --build
```

**Services Started:**

| Service | Port | Description |
|---------|------|-------------|
| Dashboard | 3000 | Next.js Frontend |
| Flask API | 8000 | Main Backend Orchestration |
| FinRAG API | 8002 | RAG Service |
| SmartFolio API | 8080 | Portfolio Service |
| KYC Combined | 8004 | KYC Verification |
| KYC Payload | 8001 | Payload Storage |
| KYC Admin | 8080 | Admin Operations |

**Access the Application:**
- Dashboard: http://localhost:3000
- API Documentation: http://localhost:8000/docs

**Docker Commands:**

```bash

docker compose up --build
```

### 5. Local Development Setup

**Important:** Always activate the virtual environment in every terminal before running any commands:

```bash
source venv/bin/activate
```

#### 5.1 Dashboard (Next.js)

```bash
cd dashboard
npm i
npm run dev
```

The dashboard will be available at http://localhost:3000

#### 5.2 Flask Server

```bash
cd flask_server
python3.11 app.py
```

The API server will be available at http://localhost:8000

#### 5.3 KYC Verification MCP Server

```bash
set -a; source keys.env; set +a
cd KYC
python3.11 MCP_Server_KYCV.py --host 0.0.0.0 --port 8123
```

#### 5.4 Risk Scoring MCP Server

```bash
set -a; source keys.env; set +a
cd KYC
python3.11 MCP_Server_RiskScore.py --host 0.0.0.0 --port 8124
```

#### 5.5 SmartFolio API

```bash
cd SmartFolio
python -m uvicorn api.server:app --host 0.0.0.0 --port 8080
```

#### 5.6 SmartFolio MCP Server

```bash
cd SmartFolio
python3.11 start_mcp.py
```

#### 5.7 FinRAG API

```bash
cd FinRAGFinal
python3.11 mcp_api.py --host 0.0.0.0 --port 8002
```

#### 5.8 FinRAG Live Indexing (Google Drive Connector)

```bash
cd FinRAGFinal/Streaming
python3.11 gdrive_connector.py
```

#### 5.9 Streaming Pipeline (Kafka)

First, start the Kafka services:

```bash
cd streaming/docker
docker-compose -f docker-compose.kafka.yml up -d
```

Then run the producers and consumers:

```bash
# From project root
python -m streaming.producer.stock_producer
python -m streaming.consumer.stock_consumer
```

## Directory Structure

```
PM_Agent/
├── dashboard/                      # Next.js Frontend
│   ├── app/
│   │   ├── (auth)/                # Authentication Pages
│   │   │   ├── login/
│   │   │   ├── register/
│   │   │   └── forgot-password/
│   │   ├── consumer/              # Consumer Dashboard
│   │   │   ├── dashboard/
│   │   │   └── questionnaire/
│   │   ├── company/               # Admin Dashboard
│   │   │   ├── dashboard/
│   │   │   └── reviews/
│   │   └── admin/                 # Admin Panel
│   ├── components/
│   │   ├── ui/                    # Reusable UI Components
│   │   └── layout/                # Layout Components
│   └── lib/
│       ├── api.ts                 # API Client
│       └── utils.ts               # Utility Functions
│
├── flask_server/                   # Main Backend API
│   ├── app.py                     # Flask Application
│   ├── config.py                  # Configuration
│   ├── models.py                  # Data Models
│   ├── orchestration_helper.py    # Portfolio Orchestration
│   ├── payload_store_mongo.py     # MongoDB Payload Storage
│   ├── alerts_store_mongo.py      # Alert Storage
│   ├── verification.py            # KYC Verification Logic
│   ├── setup_mongodb_indexes.py   # Database Indexes
│   ├── requirements.txt
│   └── Dockerfile
│
├── SmartFolio/                     # Portfolio Management (Git Submodule)
│   ├── api/
│   │   └── server.py              # FastAPI Endpoints
│   ├── model/                     # PPO Policy Networks
│   ├── trainer/
│   │   ├── irl_trainer.py         # IRL Training
│   │   └── ptr_ppo.py             # PTR-PPO Implementation
│   ├── explainibility_agents/     # XAI & Trading Agents
│   │   ├── mcp/                   # MCP Server
│   │   └── tradingagents/         # Trading Agent Logic
│   ├── gen_data/                  # Dataset Builders
│   │   ├── build_dataset_yf.py
│   │   └── update_monthly_dataset.py
│   ├── checkpoints_risk01/        # Risk 0.1 Model
│   ├── checkpoints_risk03/        # Risk 0.3 Model
│   ├── checkpoints_risk05/        # Risk 0.5 Model
│   ├── checkpoints_risk07/        # Risk 0.7 Model
│   ├── checkpoints_risk09/        # Risk 0.9 Model
│   ├── main.py                    # Training Entry Point
│   ├── Dockerfile
│   └── Dockerfile.mcp
│
├── FinRAGFinal/                    # Financial RAG (Git Submodule)
│   ├── src/
│   │   └── finrag/
│   │       ├── vectorstore/       # Pathway Vector Store
│   │       ├── retrieval/         # Multi-Source Retrieval
│   │       ├── scoring/           # Ensemble Stock Scoring
│   │       └── orchestrator/      # Query Orchestration
│   ├── api.py                     # FastAPI Endpoints
│   ├── mcp_server.py              # MCP Server
│   ├── mcp_api.py                 # MCP API
│   ├── requirements.txt
│   ├── Dockerfile
│   └── Dockerfile.mcp
│
├── KYC/                            # KYC & Risk Scoring
│   ├── combined_api.py            # Document Verification API
│   ├── payload_api.py             # Payload Storage API
│   ├── admin_api.py               # Admin Operations API
│   ├── investor_risk_scorer.py    # ML Risk Scoring
│   ├── kyc_mcp_server.py          # MCP Server
│   ├── kyc_alerts.py              # Alert Generation
│   ├── kyc_master_store.py        # Master JSON Storage
│   ├── encryption_utils.py        # Data Encryption
│   ├── Dockerfile
│   └── ENDPOINT_FLOW_EXPLANATION.md
│
├── streaming/                      # Real-time Data Pipeline
│   ├── config.py                  # Configuration
│   ├── run_all.py                 # Main Entry Point
│   ├── producer/
│   │   ├── stock_producer.py      # Stock OHLCV Producer
│   │   ├── user_producer.py       # User Data Producer
│   │   └── run_producers.py       # Producer Manager
│   ├── consumer/
│   │   ├── stock_consumer.py      # Stock Data Consumer
│   │   ├── user_consumer.py       # User Data Consumer
│   │   └── run_consumers.py       # Consumer Manager
│   ├── shared/
│   │   ├── locks.py               # Thread-safe Locks
│   │   ├── state.py               # Shared State
│   │   └── utils.py               # Utilities
│   └── docker/
│       └── docker-compose.kafka.yml
│
├── docker-compose.yml              # Full Stack Deployment
├── .env                            # Environment Variables
├── .gitmodules                     # Submodule Configuration
└── README.md                       # This File
```