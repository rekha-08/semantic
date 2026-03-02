# Semantic Integrity Analysis

Legal document analysis web app with authentication, upload, line-level issue detection, and final narrative summary.

## Current Architecture

- `backend/`: Flask API + SQLite auth + document analysis pipeline
- `frontend/`: Multi-page static UI
- `ui/`: Streamlit path (separate from current web flow)
- `analysis/`: Core analyzer logic

## Active User Flow

1. `index.html` -> Login / Sign up
2. `upload.html` -> Upload file + run analysis
3. `issues.html` -> Line-level issue analysis (duplication, inconsistency, contradiction)
4. `summary.html` ->
   - Detailed document summary (Page 1, Page 2, ... style)
   - Page-wise summary cards
   - Top findings
   - Line Error Dashboard (exact page/line)

## Features

- Auth endpoints (`register`, `login`) with SQLite
- Upload support: `PDF`, `DOCX`, `TXT`
- Detection categories:
  - Duplication
  - Inconsistency
  - Contradiction
- Vendor/Vendee extraction
- Narrative `detailedSummary` + page summaries + line-level dashboard

## Backend Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Backend default: `http://127.0.0.1:5000`

## Frontend Setup

```bash
cd frontend
python3 -m http.server 8080
```

Open: `http://127.0.0.1:8080/index.html`

## API Endpoints

- `GET /api/health`
- `POST /api/register`
- `POST /api/login`
- `POST /api/analyze`

Alias routes also available:

- `GET /health`
- `POST /register`
- `POST /login`
- `POST /analyze`

## Analyze Response (important keys)

- `summary`
- `pageSummaries`
- `detailedSummary`
- `findings`
- `lineIssues`

## Deployment (GitHub + Render)

### 1) Push repository

```bash
git add .
git commit -m "Project setup and web flow"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

### 2) Deploy backend on Render (Web Service)

- Root directory: `backend`
- Build command:

```bash
pip install -r requirements.txt
```

- Start command:

```bash
gunicorn app:app
```

### 3) Deploy frontend (static)

- Option A: Render Static Site (root `frontend`)
- Option B: GitHub Pages for `frontend/`

## Notes

- Current `frontend + backend` flow does **not** require `merged_tinyllama_instruction`.
- Streamlit path under `ui/` may use local TinyLlama model path.
- If analysis output changes are not visible, restart backend and re-run upload.
