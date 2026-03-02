# Backend (Flask + SQLite)

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Server runs on `http://127.0.0.1:5000`.

## APIs

- `GET /api/health`
- `POST /api/register`
- `POST /api/login`
- `POST /api/analyze` (multipart form: `file`, `scanMode`)

SQLite database file is created at `backend/app.db`.
