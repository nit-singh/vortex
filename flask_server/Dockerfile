FROM python:3.11-slim

WORKDIR /app

# 1. Install System Dependencies (Poppler & GL)
# FIX: Replaced 'libgl1-mesa-glx' (deprecated) with 'libgl1'
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 2. Install Python Dependencies
COPY flask_server/requirements.txt flask_server/

# Upgrade pip and install dependencies
# Added --default-timeout to prevent network errors on large files
RUN pip install --upgrade pip && \
    pip install --default-timeout=1000 --no-cache-dir -r flask_server/requirements.txt

# 3. Copy the folders to match your local structure
COPY flask_server/ flask_server/
COPY KYC/ KYC/

# 4. Move "inside" the flask folder to run the app
WORKDIR /app/flask_server

# 5. Open the port and run
EXPOSE 8000
CMD ["python", "app.py"]