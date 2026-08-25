# Dockerization & Deployment Guide

## Overview

This guide covers dockerizing the Flask backend, Next.js frontend, and deploying the complete KYC system.

---

## 📦 Phase 1: Dockerizing Components

### 1.1 Flask Backend Dockerfile

**Location:** `KYC/flask_app/Dockerfile`

```dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY flask_app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy KYC directory (all Python files)
COPY KYC/ ./KYC/

# Copy risk artifacts if they exist
COPY KYC/risk_artifacts/ ./KYC/risk_artifacts/ 2>/dev/null || true

# Set Python path
ENV PYTHONPATH=/app/KYC:$PYTHONPATH

# Create uploads directory
RUN mkdir -p /app/uploads /app/KYC/uploads

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Run Flask app
CMD ["python", "-m", "flask_app.app"]
```

---

### 1.2 Flask Requirements File

**Location:** `KYC/flask_app/requirements.txt`

```txt
Flask==3.0.0
Flask-CORS==4.0.0
python-multipart==0.0.6
Werkzeug==3.0.1
gunicorn==21.2.0

# Existing KYC dependencies
-r ../KYC_requirements.txt
-r ../VV_requirements.txt

# Additional production dependencies
python-dotenv==1.0.0
```

---

### 1.3 Next.js Frontend Dockerfile

**Location:** `dashboard/Dockerfile`

```dockerfile
# Stage 1: Build
FROM node:18-alpine AS builder

WORKDIR /app

# Copy package files
COPY dashboard/package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY dashboard/ .

# Build Next.js app
RUN npm run build

# Stage 2: Production
FROM node:18-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

# Copy built application
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Create non-root user
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs
USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
```

**Note:** Update `next.config.js` for standalone output:

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // ... other config
};

module.exports = nextConfig;
```

---

### 1.4 Docker Compose for Development

**Location:** `docker-compose.dev.yml`

```yaml
version: "3.8"

services:
  # Flask Backend
  flask-api:
    build:
      context: .
      dockerfile: KYC/flask_app/Dockerfile
    container_name: flask-kyc-api
    ports:
      - "8000:8000"
    environment:
      - FLASK_ENV=development
      - FLASK_DEBUG=1
      - KYC_MCP_HOST=0.0.0.0
      - KYC_MCP_PORT=8123
      - RISK_MCP_URL=http://risk-mcp:8124/mcp/
      - RISK_ARTIFACT_DIR=/app/KYC/risk_artifacts
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - DATABASE_PATH=/app/KYC/payloads.db
    volumes:
      - ./KYC:/app/KYC
      - flask-uploads:/app/uploads
      - flask-db:/app/KYC
    networks:
      - kyc-network
    depends_on:
      - kycv-mcp
      - risk-mcp
    restart: unless-stopped

  # KYCV MCP Server
  kycv-mcp:
    build:
      context: ./KYC
      dockerfile: Dockerfile.mcp.kycv
    container_name: kycv-mcp-server
    ports:
      - "8123:8123"
    environment:
      - KYC_MCP_HOST=0.0.0.0
      - KYC_MCP_PORT=8123
    networks:
      - kyc-network
    restart: unless-stopped

  # RiskScore MCP Server
  risk-mcp:
    build:
      context: ./KYC
      dockerfile: Dockerfile.mcp.risk
    container_name: risk-mcp-server
    ports:
      - "8124:8124"
    environment:
      - RISK_MCP_HOST=0.0.0.0
      - RISK_MCP_PORT=8124
      - RISK_ARTIFACT_DIR=/app/risk_artifacts
    volumes:
      - ./KYC/risk_artifacts:/app/risk_artifacts:ro
    networks:
      - kyc-network
    restart: unless-stopped

  # Next.js Frontend
  nextjs-dashboard:
    build:
      context: .
      dockerfile: dashboard/Dockerfile
    container_name: nextjs-dashboard
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
      - NODE_ENV=production
    depends_on:
      - flask-api
    networks:
      - kyc-network
    restart: unless-stopped

volumes:
  flask-uploads:
  flask-db:

networks:
  kyc-network:
    driver: bridge
```

---

### 1.5 Docker Compose for Production

**Location:** `docker-compose.prod.yml`

```yaml
version: "3.8"

services:
  # Flask Backend with Gunicorn
  flask-api:
    build:
      context: .
      dockerfile: KYC/flask_app/Dockerfile.prod
    container_name: flask-kyc-api
    ports:
      - "8000:8000"
    environment:
      - FLASK_ENV=production
      - FLASK_DEBUG=0
      - KYC_MCP_HOST=kycv-mcp
      - KYC_MCP_PORT=8123
      - RISK_MCP_URL=http://risk-mcp:8124/mcp/
      - RISK_ARTIFACT_DIR=/app/KYC/risk_artifacts
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - DATABASE_PATH=/app/KYC/payloads.db
      - SECRET_KEY=${SECRET_KEY}
      - ENCRYPTION_KEY=${ENCRYPTION_KEY}
    volumes:
      - flask-uploads:/app/uploads
      - flask-db:/app/KYC
    networks:
      - kyc-network
    depends_on:
      - kycv-mcp
      - risk-mcp
    restart: always
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: 4G
        reservations:
          cpus: "1"
          memory: 2G

  # KYCV MCP Server
  kycv-mcp:
    build:
      context: ./KYC
      dockerfile: Dockerfile.mcp.kycv
    container_name: kycv-mcp-server
    environment:
      - KYC_MCP_HOST=0.0.0.0
      - KYC_MCP_PORT=8123
    networks:
      - kyc-network
    restart: always

  # RiskScore MCP Server
  risk-mcp:
    build:
      context: ./KYC
      dockerfile: Dockerfile.mcp.risk
    container_name: risk-mcp-server
    environment:
      - RISK_MCP_HOST=0.0.0.0
      - RISK_MCP_PORT=8124
      - RISK_ARTIFACT_DIR=/app/risk_artifacts
    volumes:
      - ./KYC/risk_artifacts:/app/risk_artifacts:ro
    networks:
      - kyc-network
    restart: always

  # Next.js Frontend
  nextjs-dashboard:
    build:
      context: .
      dockerfile: dashboard/Dockerfile
    container_name: nextjs-dashboard
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_BASE_URL=http://flask-api:8000
      - NODE_ENV=production
    depends_on:
      - flask-api
    networks:
      - kyc-network
    restart: always

  # Nginx Reverse Proxy (Optional but recommended)
  nginx:
    image: nginx:alpine
    container_name: nginx-proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      - flask-api
      - nextjs-dashboard
    networks:
      - kyc-network
    restart: always

volumes:
  flask-uploads:
  flask-db:

networks:
  kyc-network:
    driver: bridge
```

---

### 1.6 Production Flask Dockerfile with Gunicorn

**Location:** `KYC/flask_app/Dockerfile.prod`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc g++ libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY flask_app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY KYC/ ./KYC/
COPY KYC/risk_artifacts/ ./KYC/risk_artifacts/ 2>/dev/null || true

ENV PYTHONPATH=/app/KYC:$PYTHONPATH

# Create directories
RUN mkdir -p /app/uploads /app/KYC/uploads

# Use Gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2", "--timeout", "120", "--worker-class", "sync", "flask_app.app:app"]
```

---

### 1.7 MCP Server Dockerfiles

**Location:** `KYC/Dockerfile.mcp.kycv`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY KYC_requirements.txt .
RUN pip install --no-cache-dir -r KYC_requirements.txt

COPY MCP_Server_KYCV.py .
COPY kyc_mcp_orchestrator.py .
COPY kyc_mcp_pipeline.py .
COPY kyc_alerts.py .
COPY kyc_observability.py .
COPY kyc_master_store.py .
COPY master_payload.json .

ENV KYC_MCP_HOST=0.0.0.0
ENV KYC_MCP_PORT=8123

EXPOSE 8123

CMD ["python", "MCP_Server_KYCV.py"]
```

**Location:** `KYC/Dockerfile.mcp.risk`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY KYC_requirements.txt .
RUN pip install --no-cache-dir -r KYC_requirements.txt

COPY MCP_Server_RiskScore.py .
COPY risk_mcp_orchestrator.py .
COPY investor_risk_scorer.py .

ENV RISK_MCP_HOST=0.0.0.0
ENV RISK_MCP_PORT=8124

EXPOSE 8124

CMD ["python", "MCP_Server_RiskScore.py"]
```

---

## 🌐 Phase 2: Nginx Configuration

### 2.1 Nginx Config

**Location:** `nginx/nginx.conf`

```nginx
events {
    worker_connections 1024;
}

http {
    upstream flask_backend {
        server flask-api:8000;
    }

    upstream nextjs_frontend {
        server nextjs-dashboard:3000;
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=upload_limit:10m rate=2r/s;

    server {
        listen 80;
        server_name _;

        # Security headers
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-XSS-Protection "1; mode=block" always;

        # Frontend (Next.js)
        location / {
            proxy_pass http://nextjs_frontend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_cache_bypass $http_upgrade;
        }

        # Backend API
        location /api/ {
            limit_req zone=api_limit burst=20 nodelay;

            proxy_pass http://flask_backend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Timeouts for long-running requests
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 300s;
        }

        # File upload endpoint (larger limits)
        location /api/v1/kyc/verify-complete {
            limit_req zone=upload_limit burst=5 nodelay;

            client_max_body_size 100M;
            proxy_pass http://flask_backend;
            proxy_request_buffering off;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_read_timeout 600s;
        }

        # Health check
        location /health {
            proxy_pass http://flask_backend;
            access_log off;
        }
    }
}
```

---

## 🚀 Phase 3: Deployment Options

### 3.1 AWS Deployment (EC2/ECS)

#### Option A: AWS EC2 with Docker Compose

**Steps:**

1. **Launch EC2 Instance:**

   ```bash
   # Ubuntu 22.04 LTS, t3.medium or larger
   # Security Group: Allow ports 22, 80, 443, 8000, 3000
   ```

2. **SSH into instance and install Docker:**

   ```bash
   sudo apt-get update
   sudo apt-get install -y docker.io docker-compose
   sudo usermod -aG docker $USER
   ```

3. **Clone repository:**

   ```bash
   git clone <your-repo>
   cd PM_Agent
   ```

4. **Create `.env` file:**

   ```bash
   cp .env.example .env
   # Edit with production values
   ```

5. **Deploy:**
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

#### Option B: AWS ECS (Elastic Container Service)

**Steps:**

1. **Build and push images to ECR:**

   ```bash
   # Login to ECR
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

   # Create repositories
   aws ecr create-repository --repository-name kyc-flask-api
   aws ecr create-repository --repository-name kyc-nextjs-dashboard
   aws ecr create-repository --repository-name kyc-kycv-mcp
   aws ecr create-repository --repository-name kyc-risk-mcp

   # Build and push
   docker build -t kyc-flask-api -f KYC/flask_app/Dockerfile.prod .
   docker tag kyc-flask-api:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/kyc-flask-api:latest
   docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/kyc-flask-api:latest
   ```

2. **Create ECS Task Definition** (JSON):

   ```json
   {
     "family": "kyc-app",
     "networkMode": "awsvpc",
     "containerDefinitions": [
       {
         "name": "flask-api",
         "image": "<account-id>.dkr.ecr.us-east-1.amazonaws.com/kyc-flask-api:latest",
         "portMappings": [{"containerPort": 8000}],
         "environment": [...],
         "memory": 4096,
         "cpu": 2048
       }
     ]
   }
   ```

3. **Create ECS Service** with Application Load Balancer

---

### 3.2 Google Cloud Platform (GCP)

#### Option A: Cloud Run (Serverless)

**Steps:**

1. **Build and push to GCR:**

   ```bash
   gcloud builds submit --tag gcr.io/<project-id>/kyc-flask-api
   ```

2. **Deploy to Cloud Run:**

   ```bash
   gcloud run deploy kyc-flask-api \
     --image gcr.io/<project-id>/kyc-flask-api \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated \
     --memory 4Gi \
     --cpu 2 \
     --timeout 600s \
     --max-instances 10
   ```

3. **Deploy Next.js:**
   ```bash
   gcloud run deploy kyc-dashboard \
     --image gcr.io/<project-id>/kyc-nextjs-dashboard \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated
   ```

#### Option B: GKE (Google Kubernetes Engine)

**Steps:**

1. **Create GKE cluster:**

   ```bash
   gcloud container clusters create kyc-cluster \
     --num-nodes=3 \
     --machine-type=e2-medium \
     --zone=us-central1-a
   ```

2. **Deploy using Kubernetes manifests** (see Phase 4)

---

### 3.3 Azure Deployment

#### Option A: Azure Container Instances (ACI)

**Steps:**

1. **Build and push to ACR:**

   ```bash
   az acr build --registry <registry-name> --image kyc-flask-api:latest .
   ```

2. **Deploy container group:**
   ```bash
   az container create \
     --resource-group <resource-group> \
     --name kyc-flask-api \
     --image <registry-name>.azurecr.io/kyc-flask-api:latest \
     --cpu 2 \
     --memory 4 \
     --registry-login-server <registry-name>.azurecr.io
   ```

#### Option B: Azure Kubernetes Service (AKS)

Similar to GKE - use Kubernetes manifests

---

### 3.4 DigitalOcean App Platform

**Steps:**

1. **Connect GitHub repository**
2. **Configure build settings:**
   - Build command: `docker build -t app .`
   - Run command: `docker-compose -f docker-compose.prod.yml up`
3. **Set environment variables**
4. **Deploy**

---

## ☸️ Phase 4: Kubernetes Deployment (Advanced)

### 4.1 Kubernetes Manifests

**Location:** `k8s/flask-api-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flask-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: flask-api
  template:
    metadata:
      labels:
        app: flask-api
    spec:
      containers:
        - name: flask-api
          image: <registry>/kyc-flask-api:latest
          ports:
            - containerPort: 8000
          env:
            - name: FLASK_ENV
              value: "production"
            - name: DATABASE_PATH
              value: "/data/payloads.db"
          volumeMounts:
            - name: data
              mountPath: /data
          resources:
            requests:
              memory: "2Gi"
              cpu: "1000m"
            limits:
              memory: "4Gi"
              cpu: "2000m"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 5
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: flask-data-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: flask-api-service
spec:
  selector:
    app: flask-api
  ports:
    - protocol: TCP
      port: 8000
      targetPort: 8000
  type: LoadBalancer
```

**Location:** `k8s/nextjs-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nextjs-dashboard
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nextjs-dashboard
  template:
    metadata:
      labels:
        app: nextjs-dashboard
    spec:
      containers:
        - name: nextjs
          image: <registry>/kyc-nextjs-dashboard:latest
          ports:
            - containerPort: 3000
          env:
            - name: NEXT_PUBLIC_API_BASE_URL
              value: "http://flask-api-service:8000"
          resources:
            requests:
              memory: "512Mi"
              cpu: "500m"
            limits:
              memory: "1Gi"
              cpu: "1000m"
---
apiVersion: v1
kind: Service
metadata:
  name: nextjs-service
spec:
  selector:
    app: nextjs-dashboard
  ports:
    - protocol: TCP
      port: 3000
      targetPort: 3000
  type: LoadBalancer
```

**Deploy:**

```bash
kubectl apply -f k8s/
```

---

## 🔐 Phase 5: Environment Variables & Secrets

### 5.1 Environment File Template

**Location:** `.env.example`

```bash
# Flask Configuration
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=your-secret-key-here
PORT=8000

# Database
DATABASE_PATH=/app/KYC/payloads.db

# MCP Servers
KYC_MCP_HOST=kycv-mcp
KYC_MCP_PORT=8123
RISK_MCP_URL=http://risk-mcp:8124/mcp/
RISK_ARTIFACT_DIR=/app/KYC/risk_artifacts

# OpenAI (for LLM tool selector)
OPENAI_API_KEY=sk-...

# Encryption
ENCRYPTION_KEY=your-encryption-key-32-chars

# Next.js
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NODE_ENV=production

# Optional: Monitoring
SENTRY_DSN=...
DATADOG_API_KEY=...
```

### 5.2 Secrets Management

**For Production:**

- **AWS:** Use AWS Secrets Manager or Parameter Store
- **GCP:** Use Secret Manager
- **Azure:** Use Key Vault
- **Kubernetes:** Use Secrets

**Example (Kubernetes Secret):**

```bash
kubectl create secret generic kyc-secrets \
  --from-literal=openai-api-key='sk-...' \
  --from-literal=encryption-key='...' \
  --from-literal=secret-key='...'
```

---

## 🔄 Phase 6: CI/CD Pipeline

### 6.1 GitHub Actions Workflow

**Location:** `.github/workflows/deploy.yml`

```yaml
name: Build and Deploy

on:
  push:
    branches: [main]

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v2

      - name: Login to Container Registry
        uses: docker/login-action@v2
        with:
          registry: <your-registry>
          username: ${{ secrets.REGISTRY_USERNAME }}
          password: ${{ secrets.REGISTRY_PASSWORD }}

      - name: Build and push Flask API
        uses: docker/build-push-action@v4
        with:
          context: .
          file: ./KYC/flask_app/Dockerfile.prod
          push: true
          tags: <registry>/kyc-flask-api:latest,<registry>/kyc-flask-api:${{ github.sha }}

      - name: Build and push Next.js
        uses: docker/build-push-action@v4
        with:
          context: .
          file: ./dashboard/Dockerfile
          push: true
          tags: <registry>/kyc-nextjs-dashboard:latest,<registry>/kyc-nextjs-dashboard:${{ github.sha }}

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to production
        run: |
          # SSH to server and pull latest images
          ssh user@server "cd /app && docker-compose pull && docker-compose up -d"
```

---

## 📊 Phase 7: Monitoring & Logging

### 7.1 Health Check Endpoint

Already included in Flask app:

```python
@app.route('/health')
def health():
    return {"status": "healthy", "service": "KYC Flask API"}
```

### 7.2 Logging Configuration

**Add to Flask app:**

```python
import logging
from logging.handlers import RotatingFileHandler

if not app.debug:
    file_handler = RotatingFileHandler('logs/kyc.log', maxBytes=10240000, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
```

### 7.3 Monitoring Tools

- **Prometheus + Grafana:** For metrics
- **ELK Stack:** For log aggregation
- **Sentry:** For error tracking
- **Datadog/New Relic:** APM

---

## ✅ Deployment Checklist

- [ ] All Dockerfiles created and tested locally
- [ ] Docker Compose files configured
- [ ] Environment variables documented
- [ ] Secrets management set up
- [ ] Database backups configured
- [ ] SSL/TLS certificates configured (Let's Encrypt)
- [ ] Domain name configured
- [ ] Health checks implemented
- [ ] Logging configured
- [ ] Monitoring set up
- [ ] CI/CD pipeline configured
- [ ] Load testing completed
- [ ] Security scan completed
- [ ] Documentation updated

---

## 🚀 Quick Start Commands

### Local Development

```bash
docker-compose -f docker-compose.dev.yml up -d
```

### Production

```bash
docker-compose -f docker-compose.prod.yml up -d
```

### View Logs

```bash
docker-compose logs -f flask-api
```

### Stop Services

```bash
docker-compose down
```

### Rebuild After Changes

```bash
docker-compose build --no-cache
docker-compose up -d
```

---

## 📝 Notes

1. **Database Persistence:** Use volumes for SQLite database
2. **File Uploads:** Store in persistent volume or S3
3. **MCP Servers:** Can run in same container or separate
4. **Scaling:** Use load balancer for multiple Flask instances
5. **Security:** Always use HTTPS in production
6. **Backups:** Regular backups of database and uploaded files
