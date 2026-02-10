# eCourts Scraper v2

A production-grade, stateful scraping service for eCourts, built with FastAPI and Redis.
This project adapts the logic from the original CLI script into a scalable backend service.

## Architecture

- **FastAPI**: Handles HTTP requests and async orchestration.
- **Redis**: Stores session state, cookies, and tokens. No in-memory state in the app process.
- **Scraper Engine**:
  - `ECourtsClient`: Handles low-level HTTP requests, token injection, and session management.
  - `ScraperSession`: Redis-backed state machine (INIT -> CAPTCHA -> SEARCH -> RESULT).
  - `Processor`: Parsing logic using BeautifulSoup and Bleach (sanitization).

## Setup

1. **Prerequisites**:
   - Python 3.9+
   - Redis Server running (default: `localhost:6379`)

2. **Installation**:

   ```bash
   pip install -r requirements.txt
   ```

3. **Configuration**:
   Create a `.env` file (optional, defaults provided):

   ```env
   REDIS_URL=redis://localhost:6379
   SESSION_TTL=900  # 15 minutes
   ```

4. **Run Server**:

   ```bash
   uvicorn app.main:app --reload
   ```

5. **Access Frontend**:
   Open `http://localhost:8000` in your browser.

## API Flow

1. **Start Session** (`POST /cases/start`):
   - Accepts CNR number.
   - Initializes a session in Redis.
   - Fetches the initial `app_token` from eCourts homepage.
   - Returns `session_id`.

2. **Get Captcha** (`GET /cases/captcha/{session_id}`):
   - Returns the captcha image bytes.
   - Updates session cookies/token to keep the session alive.

3. **Submit Captcha** (`POST /cases/captcha/{session_id}`):
   - Submits the captcha code.
   - Triggers the search request (CNR or Party).
   - If successful, stores the result HTML in Redis and updates state.
   - If "Invalid Captcha", resets state to `CAPTCHA_REQUIRED`.

4. **Poll Status** (`GET /cases/status/{session_id}`):
   - Frontends should poll this to check if scraping is complete (`HISTORY_FETCHED`), failed (`FAILED`), or waiting (`CAPTCHA_REQUIRED`).

5. **Fetch Results** (`GET /cases/result/{session_id}`):
   - Returns the structured data and sanitized HTML.
   - Transitions state to `HISTORY_FETCHED`.

## CLI Adaptation Notes

The original CLI logic was adapted as follows:

- **State**: Moved from local variables to Redis (`ScraperSession` class).
- **Client**: `ECourtsClient` remains mostly the same but `requests.Session` cookies are loaded/saved to Redis for each request to ensure statelessness of the worker.
- **Parsing**: `processor.py` contains the parsing functions extracted from the CLI script, cleaned up for modular usage.
- **Flow**: The CLI's interactive loop is replaced by the State Machine pattern handled via API endpoints.

## Verification

Run the verification script to test the flow (uses `fakeredis`):

```bash
python verify_setup.py
```

> Note: The verification script mocks the eCourts website responses to test the application logic without external network dependencies.
