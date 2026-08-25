FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY KYC_requirements.txt requirements.txt
RUN pip install --upgrade pip && \
    pip install --default-timeout=1000 --no-cache-dir -r requirements.txt

# Copy the entire KYC directory
COPY . .

# Expose ports (will be overridden by docker-compose for different services)
EXPOSE 8000 8001 8080

# Default command (can be overridden in docker-compose)
CMD ["python", "combined_api.py"]

