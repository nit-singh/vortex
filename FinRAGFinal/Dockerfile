FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --default-timeout=1000 --no-cache-dir -r requirements.txt

# Copy the entire FinRAG application
COPY . .

# Expose the API port (default 8000, but will be overridden in docker-compose)
EXPOSE 8000

# Run the MCP API server using uvicorn (mcp_api.py)
CMD ["python", "-m", "uvicorn", "mcp_api:app", "--host", "0.0.0.0", "--port", "8000"]

