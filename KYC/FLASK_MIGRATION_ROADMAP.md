# Flask Server Migration Roadmap

## Current State Analysis

### Existing API Servers (FastAPI)

1. **`kyc_api.py`** (Port 8080)

   - `/api/v1/kyc/submit` - Submit KYC documents
   - `/api/v1/kyc/status/{submission_id}` - Get submission status
   - `/api/v1/kyc/review/pending` - List pending reviews
   - `/api/v1/kyc/review/{review_id}` - Get review details
   - `/api/v1/kyc/review/{review_id}/decision` - Submit review decision

2. **`risk_api_service.py`** (Port not specified)

   - `/api/v1/risk-score` - Get risk score
   - `/api/v1/admin/settings` - Get/update admin settings
   - `/api/v1/admin/offline-score` - Get offline risk score
   - `/api/v1/mcp/risk-score/{trace_id}` - MCP risk score endpoint

3. **`combined_api.py`** (Port 8000)

   - `/api/v1/kyc/verify-complete` - Complete integrated KYC verification
   - `/parse` - Parse individual document (legacy)
   - `/health` - Health check

4. **`payload_api.py`** (Port 8001)

   - `/payloads/{user_id}` - Store/get payloads
   - `/payloads/{user_id}/master` - Get master JSON
   - `/payloads/{user_id}/ml` - Get ML input JSON
   - `/orchestrate` - Trigger orchestration

5. **`admin_api.py`** (Port 8080)
   - Admin controls for risk model management

### MCP Servers

1. **`MCP_Server_KYCV.py`** (Port 8123)

   - KYC Verification MCP Server
   - Tools for document verification, report generation, alert planning

2. **`MCP_Server_RiskScore.py`** (Port 8124)
   - Risk Scoring MCP Server
   - Tools for investor risk scoring

### Dashboard Requirements

Based on `dashboard/lib/api.ts`, the dashboard expects:

- `POST /api/v1/kyc/submit` - Submit KYC with FormData
- `GET /api/v1/kyc/status/{submissionId}` - Get submission status
- `POST /api/v1/risk-score` - Get risk score

Default API base URL: `http://localhost:8000`

---

## Migration Roadmap

### Phase 1: Flask Server Setup & Core Structure

#### 1.1 Create Flask Application Structure

```
KYC/
├── flask_app/
│   ├── __init__.py              # Flask app factory
│   ├── app.py                   # Main Flask application
│   ├── config.py                # Configuration management
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── kyc_routes.py        # KYC endpoints
│   │   ├── risk_routes.py       # Risk scoring endpoints
│   │   ├── payload_routes.py    # Payload management
│   │   └── admin_routes.py      # Admin endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   ├── kyc_service.py      # KYC business logic
│   │   ├── risk_service.py      # Risk scoring logic
│   │   └── orchestration_service.py  # Orchestration logic
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── file_handlers.py     # File upload/processing
│   │   └── response_helpers.py  # Response formatting
│   └── requirements.txt          # Flask-specific dependencies
```

#### 1.2 Install Flask Dependencies

- Flask
- Flask-CORS (for CORS support)
- Flask-RESTful (optional, for RESTful API structure)
- python-multipart (for file uploads)
- Werkzeug (for file handling)

#### 1.3 Create Flask App Factory

- Initialize Flask app
- Configure CORS
- Register blueprints
- Set up error handlers

---

### Phase 2: Migrate KYC Endpoints

#### 2.1 Document Upload & Verification

**From:** `combined_api.py` → `/api/v1/kyc/verify-complete`
**To:** Flask route handling:

- File uploads (PAN, Aadhaar, ITR, selfie video)
- JSON form data (questionnaire, additional details)
- Call existing parser functions from `combined_api.py`
- Return master_json and ml_input_json

**Key Functions to Reuse:**

- `parser_()` from `combined_api.py`
- `VideoVerificationService` from `combined_api.py`
- `cross_verify_documents()` from `combined_api.py`
- `resolve_field_value()` from `combined_api.py`

#### 2.2 KYC Submission (Dashboard Compatible)

**From:** `kyc_api.py` → `/api/v1/kyc/submit`
**To:** Flask route that:

- Accepts multipart/form-data
- Processes documents using existing pipeline
- Stores submission in memory/database
- Returns submission response

**Key Functions to Reuse:**

- `run_pipeline()` from `kyc_verifier` (if exists)
- Submission storage logic from `kyc_api.py`

#### 2.3 Status Check

**From:** `kyc_api.py` → `/api/v1/kyc/status/{submission_id}`
**To:** Flask route that retrieves submission status

---

### Phase 3: Migrate Risk Scoring Endpoints

#### 3.1 Risk Score Calculation

**From:** `risk_api_service.py` → `/api/v1/risk-score`
**To:** Flask route that:

- Accepts features JSON
- Calls `OnlineRiskScorer` from `investor_risk_scorer`
- Returns risk score

**Key Functions to Reuse:**

- `ServiceState` class from `risk_api_service.py`
- `load_deployment_pipeline()` from `investor_risk_scorer`
- Risk scoring logic

#### 3.2 Admin Settings

**From:** `admin_api.py` and `risk_api_service.py`
**To:** Flask routes for:

- Get/update model settings
- Toggle offline/online centroids
- Reload model artifacts

---

### Phase 4: Integrate Payload Management

#### 4.1 Payload Storage

**From:** `payload_api.py`
**To:** Flask routes for:

- Store payloads by user_id
- Retrieve payloads (decrypted/masked/encrypted)
- Update payload status

**Key Functions to Reuse:**

- `PayloadStore` from `payload_store.py`
- `OverallPayload` from `payload_store.py`
- Encryption utilities from `encryption_utils.py`

#### 4.2 Orchestration Trigger

**From:** `payload_api.py` → `/orchestrate`
**To:** Flask route that:

- Triggers `unified_orchestrator.py`
- Runs orchestration in background
- Returns task_id

---

### Phase 5: MCP Server Integration

#### 5.1 MCP Server Communication

- Keep MCP servers running as separate processes
- Flask app communicates with MCP servers via HTTP
- Use `unified_orchestrator.py` for coordination

**MCP Server URLs:**

- KYCV: `http://127.0.0.1:8123/mcp/`
- RiskScore: `http://127.0.0.1:8124/mcp/`

#### 5.2 Orchestration Service

- Create Flask service that wraps `unified_orchestrator.py`
- Handle async orchestration tasks
- Store results back to payload store

---

### Phase 6: Error Handling & Middleware

#### 6.1 Error Handlers

- Global error handler for 404, 500, etc.
- Custom error responses matching FastAPI format
- Logging integration

#### 6.2 Middleware

- Request logging
- CORS configuration
- Authentication middleware (if needed)

---

### Phase 7: Testing & Validation

#### 7.1 Endpoint Testing

- Test all migrated endpoints
- Verify compatibility with dashboard
- Test file uploads
- Test error scenarios

#### 7.2 Integration Testing

- Test full KYC flow
- Test orchestration flow
- Test MCP server communication

---

## Implementation Steps (Detailed)

### Step 1: Create Flask App Structure

```bash
cd KYC
mkdir -p flask_app/{routes,services,utils}
touch flask_app/__init__.py flask_app/app.py flask_app/config.py
touch flask_app/routes/__init__.py
touch flask_app/services/__init__.py
touch flask_app/utils/__init__.py
```

### Step 2: Create Flask Requirements File

Create `flask_app/requirements.txt`:

```
Flask==3.0.0
Flask-CORS==4.0.0
python-multipart==0.0.6
Werkzeug==3.0.1
```

### Step 3: Create Main Flask App (`flask_app/app.py`)

- Initialize Flask app
- Configure CORS for dashboard
- Register blueprints
- Set up error handlers

### Step 4: Create Route Blueprints

- `kyc_routes.py` - All KYC-related endpoints
- `risk_routes.py` - Risk scoring endpoints
- `payload_routes.py` - Payload management
- `admin_routes.py` - Admin controls

### Step 5: Create Service Layer

- Extract business logic from existing FastAPI files
- Create service classes that wrap existing functions
- Handle file processing, validation, etc.

### Step 6: Update Dashboard API Client

- Verify API endpoints match
- Test with Flask server
- Update if needed

---

## Key Considerations

### 1. File Upload Handling

- Flask uses `request.files` instead of FastAPI's `UploadFile`
- Need to handle multipart/form-data properly
- Temporary file storage for processing

### 2. Async Operations

- Flask doesn't have native async support like FastAPI
- Use threading or background tasks for long-running operations
- Consider using Celery for complex orchestration

### 3. Response Format

- Ensure JSON responses match FastAPI format
- Maintain compatibility with dashboard expectations

### 4. Error Handling

- Convert FastAPI HTTPException to Flask error responses
- Maintain consistent error format

### 5. Dependencies

- Reuse existing Python modules
- Import functions from existing files
- Don't duplicate code

### 6. Configuration

- Environment variables for ports, URLs
- MCP server URLs
- Database paths
- Artifact directories

---

## Migration Checklist

- [ ] Create Flask app structure
- [ ] Set up Flask app factory and configuration
- [ ] Migrate KYC verification endpoint (`/api/v1/kyc/verify-complete`)
- [ ] Migrate KYC submission endpoint (`/api/v1/kyc/submit`)
- [ ] Migrate KYC status endpoint (`/api/v1/kyc/status/{id}`)
- [ ] Migrate risk score endpoint (`/api/v1/risk-score`)
- [ ] Migrate payload storage endpoints
- [ ] Migrate orchestration endpoint
- [ ] Migrate admin endpoints
- [ ] Add CORS support
- [ ] Add error handling
- [ ] Add logging
- [ ] Test with dashboard
- [ ] Update documentation
- [ ] Create startup script
- [ ] Add health check endpoint

---

## Next Steps

1. **Start with Flask app setup** - Create basic structure
2. **Migrate dashboard-critical endpoints first** - `/api/v1/kyc/submit`, `/api/v1/kyc/status`, `/api/v1/risk-score`
3. **Test with dashboard** - Ensure compatibility
4. **Migrate remaining endpoints** - Complete the migration
5. **Add orchestration** - Integrate MCP servers
6. **Production readiness** - Error handling, logging, monitoring

---

## Questions to Resolve

1. **Database/Storage**: Should we use the existing `payload_store.py` SQLite database or migrate to a different solution?
2. **Session Management**: How should we handle user sessions and authentication?
3. **Background Tasks**: Should we use Flask's threading, Celery, or another solution for orchestration?
4. **MCP Server Management**: Should MCP servers be started automatically or run separately?
5. **Port Configuration**: What port should the Flask server run on? (Dashboard expects 8000)

---

## Estimated Timeline

- **Phase 1-2**: 2-3 days (Flask setup + KYC endpoints)
- **Phase 3**: 1-2 days (Risk scoring)
- **Phase 4**: 1 day (Payload management)
- **Phase 5**: 1-2 days (MCP integration)
- **Phase 6-7**: 1-2 days (Testing & polish)

**Total: ~7-10 days**
