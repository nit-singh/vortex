# KYC Endpoint Flow Explanation

## Overview

This document explains each endpoint in the order they're typically called during a KYC verification flow.

---

## 🔄 Complete KYC Flow

```
Dashboard → Flask API → MCP Servers → Database/Storage
```

---

## 📋 Endpoint Flow (Step by Step)

### **STEP 1: Document Verification & Parsing**

#### **Endpoint:** `POST /api/v1/kyc/verify-complete`

**File:** `combined_api.py`  
**Port:** 8000

**What it expects:**

- **Files (multipart/form-data):**
  - `pan_document`: PAN card image or PDF
  - `aadhaar_document`: Aadhaar card image or PDF
  - `itr_document`: ITR document image or PDF
  - `selfie_video`: Selfie video file (MP4, etc.)
- **Form fields (JSON strings):**
  - `questionnaire`: JSON with Q1-Q6 answers (A/B/C/D)
  - `additional_details`: JSON with amount_to_invest, address, occupation, marital_status, dependents, citizenship

**Who it interacts with:**

1. **Parser functions** (`parser_paddleocr`, `parser_docling`) - Extract text from documents
2. **Extractors:**
   - `PANCardExtractor` - Extracts PAN number, name, father's name, DOB
   - `AadhaarExtractor` - Extracts Aadhaar number, name, DOB, gender
   - `extract_itr_details()` - Extracts ITR details (PAN, income, taxes, etc.)
3. **Video Verification Service** (`VideoVerificationService`) - Verifies selfie video:
   - Face matching (Aadhaar↔PAN, PAN↔Video)
   - Liveness detection (blinks, head movement)
4. **Cross-verification** (`cross_verify_documents()`) - Compares data across all 3 documents
5. **Alert system** (`build_alert_signal`, `plan_alert_from_signal`) - Generates alerts if needed
6. **Master JSON store** (`register_master_json`) - Stores the master JSON

**What it returns:**

```json
{
  "success": true,
  "master_verification": {
    "verification_status": {...},
    "personal_details": {...},
    "financial_details": {...},
    "family_details": {...},
    "questionnaire_responses": {...},
    "document_verification_details": {...},
    "video_verification_details": {...},
    "alerting": {...}
  },
  "ml_model_input": {
    "age": 35,
    "dependents": 2,
    "gross_income": 500000,
    "tax_paid": 50000,
    "gender": "Male",
    "main_occupation": "Engineer",
    "marital_status": "Married",
    "filing_timeliness": "On time",
    "Q1": "A", "Q2": "B", ...
  },
  "master_json_id": "uuid-here",
  "alert_signal": {...},
  "alert_plan": {...}
}
```

**Key Processing:**

- Converts PDFs to images if needed
- Runs document parsing in parallel (async)
- Runs video verification in thread pool (blocking operation)
- Cross-verifies all extracted data
- Resolves conflicts between documents (prioritizes PAN > Aadhaar > ITR)
- Generates master JSON and simplified ML input JSON

---

### **STEP 2: Store Payload for Orchestration**

#### **Endpoint:** `POST /payloads/{user_id}`

**File:** `payload_api.py`  
**Port:** 8001

**What it expects:**

- **Path parameter:** `user_id` (string)
- **Body (JSON):**
  ```json
  {
    "master_json": {...},  // Full verification data from Step 1
    "ml_input_json": {...}, // ML features from Step 1
    "metadata": {...}       // Optional metadata
  }
  ```

**Who it interacts with:**

1. **PayloadStore** (`payload_store.py`) - SQLite database storage
2. **Encryption utilities** (`encryption_utils.py`) - Encrypts sensitive fields (Aadhaar, PAN, DOB) before storage

**What it returns:**

```json
{
  "user_id": "user123",
  "master_json": {...},  // Decrypted version
  "ml_input_json": {...},
  "status": "pending",
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:00",
  "metadata": {...}
}
```

**Key Processing:**

- Encrypts sensitive PII fields (Aadhaar, PAN, DOB) before storing
- Stores in SQLite database
- Returns decrypted version for immediate use

---

### **STEP 3: Trigger Orchestration (Background Process)**

#### **Endpoint:** `POST /orchestrate`

**File:** `payload_api.py`  
**Port:** 8001

**What it expects:**

- **Body (JSON):**
  ```json
  {
    "user_id": "user123",
    "run_kycv": true, // Run KYCV MCP server
    "run_risk_score": true, // Run RiskScore MCP server
    "generate_report": true, // Generate KYC report
    "plan_alerts": true // Plan and dispatch alerts
  }
  ```

**Who it interacts with:**

1. **PayloadStore** - Fetches stored payload by user_id
2. **Unified Orchestrator** (`unified_orchestrator.py`) - Runs in background:
   - **KYCV MCP Server** (port 8123) - Receives `master_json`:
     - `generate_report()` - Generates human-readable KYC report
     - `plan_alert()` - Plans alerts based on verification results
     - Other tools based on LLM tool selector
   - **RiskScore MCP Server** (port 8124) - Receives `ml_input_json`:
     - `score_investor_risk()` - Calculates risk score
     - Returns risk score and cluster assignment
3. **LLM Tool Selector** (`llm_tool_selector.py`) - Decides which MCP tools to call
4. **PayloadStore** - Updates payload with orchestration results

**What it returns:**

```json
{
  "task_id": "task-uuid-here",
  "user_id": "user123",
  "status": "processing",
  "message": "Orchestration started. Check payload status for results."
}
```

**Key Processing:**

- Runs orchestration in background (non-blocking)
- Fetches payload from database
- Calls both MCP servers asynchronously
- Uses LLM to intelligently select which tools to execute
- Updates payload status and results in database

---

### **STEP 4: Check Orchestration Status**

#### **Endpoint:** `GET /payloads/{user_id}`

**File:** `payload_api.py`  
**Port:** 8001

**What it expects:**

- **Path parameter:** `user_id` (string)

**Who it interacts with:**

1. **PayloadStore** - Retrieves payload from SQLite database
2. **Encryption utilities** - Decrypts sensitive fields

**What it returns:**

```json
{
  "user_id": "user123",
  "master_json": {...},  // Updated with orchestration results
  "ml_input_json": {...},
  "status": "completed",  // pending, processing, completed, failed
  "created_at": "...",
  "updated_at": "...",
  "metadata": {
    "task_id": "...",
    "kycv_report": "...",      // Generated report
    "risk_score": {...},        // Risk score result
    "alert_plan": {...}         // Alert plan
  }
}
```

**Key Processing:**

- Retrieves latest payload state
- Decrypts sensitive fields for display
- Status indicates if orchestration is complete

---

## 🔀 Alternative Flow: Direct Risk Scoring

### **Endpoint:** `POST /api/v1/risk-score`

**File:** `risk_api_service.py`  
**Port:** (Not specified, likely 8000 or separate)

**What it expects:**

- **Body (JSON):**
  ```json
  {
    "features": {
      "age": 35,
      "dependents": 2,
      "gross_income": 500000,
      "tax_paid": 50000,
      "gender": "Male",
      "main_occupation": "Engineer",
      "marital_status": "Married",
      "filing_timeliness": "On time",
      "Q1": "A", "Q2": "B", ...
    },
    "trace_id": "optional-trace-id",
    "online_update": true  // Optional: allow model to learn
  }
  ```

**Who it interacts with:**

1. **OnlineRiskScorer** (`investor_risk_scorer.py`) - ML model:
   - Uses River KMeans for online clustering
   - Autoencoder for feature encoding
   - Calculates risk score based on cluster distance
2. **ServiceState** - Manages model artifacts:
   - Loads pre-trained models from `risk_artifacts/`
   - Manages online/offline centroid toggle
   - Handles model updates
3. **Session Store** - In-memory storage of results by trace_id

**What it returns:**

```json
{
  "trace_id": "trace-uuid",
  "online_result": {
    "risk_score": 0.65,
    "cluster_id": 2,
    "cluster_distance": 0.12,
    "confidence": 0.88,
    "recommendation": "Moderate Risk"
  }
}
```

**Key Processing:**

- Loads ML models from disk
- Encodes features using autoencoder
- Finds nearest cluster using KMeans
- Calculates risk score based on distance
- Optionally updates model with new data (online learning)

---

## 🔀 Alternative Flow: Simple KYC Submission (Legacy)

### **Endpoint:** `POST /api/v1/kyc/submit`

**File:** `kyc_api.py`  
**Port:** 8080

**What it expects:**

- **Files (multipart/form-data):**
  - `aadhaar`: Image file
  - `pan`: Image file
  - `itr`: Image file
  - `selfie_video`: Video file
- **Form field:**
  - `user_id`: String

**Who it interacts with:**

1. **KYC Verifier** (`kyc_verifier.py`) - `run_pipeline()` function:
   - Face matching between documents
   - Video liveness detection
   - Returns verification result
2. **SubmissionStore** - In-memory storage (thread-safe dictionary)

**What it returns:**

```json
{
  "submission_id": "uuid",
  "status": "accepted" | "manual_review_pending" | "rejected",
  "final_decision": "accept" | "reject",
  "risk_score": 0.45,
  "user_message": "Verification successful...",
  "manual_review_id": "uuid-or-null"
}
```

**Key Processing:**

- Simpler than `/verify-complete` - doesn't parse document text
- Only does face matching and liveness
- Stores in memory (not database)
- Returns immediately

---

### **Endpoint:** `GET /api/v1/kyc/status/{submission_id}`

**File:** `kyc_api.py`  
**Port:** 8080

**What it expects:**

- **Path parameter:** `submission_id` (string)

**Who it interacts with:**

1. **SubmissionStore** - Retrieves from in-memory storage

**What it returns:**

```json
{
  "submission_id": "uuid",
  "status": "accepted",
  "final_decision": "accept",
  "risk_score": 0.45,
  "user_message": "...",
  "manual_review_id": null,
  "created_at": "2024-01-01T00:00:00Z",
  "decision_source": "automated"
}
```

---

## 🎛️ Admin Endpoints

### **Endpoint:** `GET /api/v1/admin/settings`

**File:** `risk_api_service.py` or `admin_api.py`

**What it expects:** Nothing (GET request)

**Who it interacts with:**

1. **ServiceState** - Current model configuration

**What it returns:**

```json
{
  "artifact_dir": "./risk_artifacts",
  "use_offline_centroids": true,
  "allow_online_updates": true
}
```

---

### **Endpoint:** `PATCH /api/v1/admin/settings`

**File:** `risk_api_service.py` or `admin_api.py`

**What it expects:**

```json
{
  "use_offline_centroids": true, // Optional
  "allow_online_updates": false // Optional
}
```

**Who it interacts with:**

1. **ServiceState** - Updates configuration
2. **Model loader** - Reloads models if centroids changed

**What it returns:** Updated settings

---

## 📊 Summary Table

| Endpoint                      | Method | Port | Purpose                              | Returns                    |
| ----------------------------- | ------ | ---- | ------------------------------------ | -------------------------- |
| `/api/v1/kyc/verify-complete` | POST   | 8000 | Full document parsing + verification | master_json, ml_input_json |
| `/payloads/{user_id}`         | POST   | 8001 | Store payload for orchestration      | Stored payload             |
| `/orchestrate`                | POST   | 8001 | Trigger MCP orchestration            | task_id                    |
| `/payloads/{user_id}`         | GET    | 8001 | Get orchestration results            | Updated payload            |
| `/api/v1/risk-score`          | POST   | 8000 | Direct risk scoring                  | Risk score                 |
| `/api/v1/kyc/submit`          | POST   | 8080 | Simple KYC (legacy)                  | Submission result          |
| `/api/v1/kyc/status/{id}`     | GET    | 8080 | Check submission status              | Status info                |

---

## 🔗 MCP Server Interaction

### **KYCV MCP Server** (Port 8123)

- **Receives:** `master_json` (full verification data)
- **Tools:**
  - `generate_report()` - Creates human-readable report
  - `plan_alert()` - Plans alerts based on verification
  - `validate_master_json()` - Validates data structure
- **Returns:** Report text, alert plans, validation results

### **RiskScore MCP Server** (Port 8124)

- **Receives:** `ml_input_json` (simplified features)
- **Tools:**
  - `score_investor_risk()` - Calculates risk score
  - `get_risk_distribution()` - Gets risk distribution stats
- **Returns:** Risk score, cluster assignment, confidence

---

## 🗄️ Database/Storage

### **PayloadStore** (SQLite)

- **Stores:** Encrypted payloads by user_id
- **Fields:** master_json, ml_input_json, status, metadata
- **Encryption:** Sensitive fields (Aadhaar, PAN, DOB) encrypted at rest

### **SubmissionStore** (In-Memory)

- **Stores:** KYC submissions by submission_id
- **Fields:** Files, results, status, risk_score
- **Note:** Data lost on server restart

---

## 🔄 Typical User Journey

1. **User uploads documents** → `POST /api/v1/kyc/verify-complete`
2. **System stores payload** → `POST /payloads/{user_id}`
3. **System triggers orchestration** → `POST /orchestrate`
4. **Orchestration calls MCP servers** (background):
   - KYCV MCP generates report
   - RiskScore MCP calculates risk
5. **User checks status** → `GET /payloads/{user_id}`
6. **Dashboard displays results** with report and risk score
