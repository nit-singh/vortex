FROM python:3.10-slim


RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libffi-dev \
    libssl-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    poppler-utils \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"


WORKDIR /app


COPY requirements.txt /app/requirements.txt


RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    kafka-python \
    "pathway[xpack-llm-docs]" \
    pandas \
    numpy \
    torch \
    torchvision \
    scikit-learn \
    stable-baselines3 \
    torch-geometric \
    yfinance \
    pillow \
    requests \
    gym \
    gymnasium \
    paddleocr \
    paddlepaddle \
    pdf2image \
    docling \
    opencv-python \
    facenet-pytorch \
    fastapi \
    uvicorn \
    python-multipart \
    pydantic


RUN if [ -f /app/requirements.txt ]; then pip install --no-cache-dir -r /app/requirements.txt || true; fi


ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1


CMD ["python", "-m", "streaming.run_all"]
