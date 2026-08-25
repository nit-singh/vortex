#!/usr/bin/env python3
"""
Setup MongoDB indexes for monthly batch processing collections.
Run this once to create the necessary indexes.
"""

import os
import sys
from pathlib import Path
from pymongo import MongoClient

# Try to load environment variables
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / "keys.env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass  # dotenv not available, use environment variables directly

# MongoDB connection
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "kyc_app")

try:
    client = MongoClient(MONGODB_URI)
    db = client[MONGODB_DB_NAME]
    
    # Create indexes for finrag_batch_scores
    batch_scores_collection = db.finrag_batch_scores
    
    print("Creating indexes for finrag_batch_scores...")
    batch_scores_collection.create_index([("year_month", 1), ("batch_date", -1)])
    batch_scores_collection.create_index([("created_at", -1)])
    batch_scores_collection.create_index([("batch_date", 1)])
    print("✓ Indexes created for finrag_batch_scores")
    
    # Create indexes for smartfolio_finetune_runs
    finetune_runs_collection = db.smartfolio_finetune_runs
    
    print("Creating indexes for smartfolio_finetune_runs...")
    finetune_runs_collection.create_index([("finetune_month", 1), ("risk_score", 1)])
    finetune_runs_collection.create_index([("created_at", -1)])
    finetune_runs_collection.create_index([("finetune_month", 1)])
    print("✓ Indexes created for smartfolio_finetune_runs")
    
    # Create indexes for smartfolio_xai_runs
    xai_runs_collection = db.smartfolio_xai_runs
    
    print("Creating indexes for smartfolio_xai_runs...")
    xai_runs_collection.create_index([("year_month", 1), ("run_date", -1)])
    xai_runs_collection.create_index([("created_at", -1)])
    xai_runs_collection.create_index([("run_date", 1)])
    xai_runs_collection.create_index([("status", 1)])
    print("✓ Indexes created for smartfolio_xai_runs")
    
    print("\n✓ All indexes created successfully!")
    
except Exception as e:
    print(f"✗ Error creating indexes: {e}")
    sys.exit(1)

