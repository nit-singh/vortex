# SmartFolio

Reinforcement learning-based portfolio optimization using PPO with Heterogeneous Graph Attention Networks (HGAT).

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Extract Data from Zip

The following folders contain large data files and pre-trained models. Extract them from the provided `vortex_data.zip` file:

```bash
# Extract the data zip file (provided separately)
unzip vortex_data.zip -d SmartFolio/
```

**Required folders:**

| Folder | Description |
|--------|-------------|
| `checkpoints_risk01/` | Pre-trained PPO model for risk level 0.1 |
| `checkpoints_risk03/` | Pre-trained PPO model for risk level 0.3 |
| `checkpoints_risk05/` | Pre-trained PPO model for risk level 0.5 |
| `checkpoints_risk07/` | Pre-trained PPO model for risk level 0.7 |
| `checkpoints_risk09/` | Pre-trained PPO model for risk level 0.9 |
| `dataset_default/` | Training datasets and expert cache (~920MB) |
| `display_data/` | Pre-computed visualization data for dashboard |

Each checkpoint folder contains:
- `baseline.zip` - PPO model checkpoint
- `replay_buffer_custom.pkl` - Experience replay buffer
- `reward_net_*.pt` - Reward network (if IRL training was used)

The `dataset_default/` folder contains:
- `data_train_predict_custom/` - Daily pkl files for training
- `corr/custom/` - Monthly correlation matrices
- `index_data/custom_index.csv` - Benchmark returns
- `expert_cache/` - Cached expert trajectories

The `display_data/` folder contains:
- Pre-computed portfolio weights and returns for visualization
- Used by the dashboard for displaying historical performance

### 3. Build Dataset (Optional)

Generate the dataset from Yahoo Finance:

```bash
python gen_data/build_dataset_yf.py \
    --tickers_file tickers.csv \
    --start 2016-01-01 \
    --end 2024-12-31 \
    --market custom \
    --lookback 30
    --industry_mode sector
```

This creates the `dataset_default/` folder with:
- `data_train_predict_custom/` - Daily pkl files for training
- `corr/custom/` - Monthly correlation matrices
- `index_data/custom_index.csv` - Benchmark returns

### 4. Run API Server

```bash
python -m api.server --host 0.0.0.0 --port 8080
```

Endpoints:
- `POST /inference` - Run model inference
- `POST /finetune` - Monthly fine-tuning
