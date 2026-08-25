# Flask Server - User Signup

Simple Flask server with MongoDB user signup functionality.

## Setup

1. **Install dependencies:**

   ```bash
   pip install -r flask_server/requirements.txt
   ```

2. **Set MongoDB connection string:**

   Edit the `.env` file in the project root and set your MongoDB URI:

   ```
   MONGODB_URI=mongodb://localhost:27017/
   # Or for MongoDB Atlas:
   # MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/
   ```

   The `.env` file is already created with default values. Just update `MONGODB_URI` with your connection string.

3. **Run the server:**
   ```bash
   python flask_server/app.py
   ```

## Endpoints

### POST /api/v1/auth/signup

Create a new user account.

**Request:**

```json
{
  "email": "user@example.com",
  "password": "password123",
  "name": "John Doe",
  "userType": "consumer"
}
```

**Response (201):**

```json
{
  "success": true,
  "message": "User created successfully",
  "userId": "...",
  "email": "user@example.com",
  "userType": "consumer"
}
```

### GET /health

Health check endpoint.

## Environment Variables

- `MONGODB_URI` - MongoDB connection string (required)
- `MONGODB_DB_NAME` - Database name (default: "kyc_app")
- `FLASK_PORT` - Server port (default: 8000)
- `FLASK_HOST` - Server host (default: 0.0.0.0)
- `FLASK_DEBUG` - Debug mode (default: false)
