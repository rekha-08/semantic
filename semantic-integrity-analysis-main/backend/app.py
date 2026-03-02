from __future__ import annotations

import io
import os
import sqlite3
import sys
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "app.db"))

app = Flask(__name__)
CORS(app)


def _bootstrap_site_packages() -> None:
    """
    Make backend resilient when dependencies are split across:
    - project venv site-packages
    - user local site-packages (~/.local)
    """
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidate_paths = [
        PROJECT_ROOT / "venv" / "lib" / f"python{py_ver}" / "site-packages",
        Path.home() / ".local" / "lib" / f"python{py_ver}" / "site-packages",
    ]
    for path in candidate_paths:
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.append(path_str)


_bootstrap_site_packages()


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _extract_text_data(file_bytes: bytes, file_ext: str):
    if file_ext == "txt":
        return [{"text": file_bytes.decode("utf-8", errors="ignore"), "page": 1}]

    if file_ext == "pdf":
        import pdfplumber

        extracted = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if text.strip():
                    extracted.append({"text": text, "page": i + 1})
        return extracted

    if file_ext == "docx":
        import docx

        doc = docx.Document(io.BytesIO(file_bytes))
        text = "\n".join(p.text for p in doc.paragraphs if p.text is not None)
        return [{"text": text, "page": 1}] if text.strip() else []

    raise ValueError("Unsupported file type. Use PDF, DOCX, or TXT.")


def _extract_clauses(text_data):
    import re

    clauses = []
    clause_id = 0

    for chunk in text_data:
        raw_text = chunk.get("text", "")
        page_num = chunk.get("page", 1)
        pattern = re.compile(r".+?(?:[.!?](?:\s+|$)|$)", re.DOTALL)

        for match in pattern.finditer(raw_text):
            cleaned = " ".join(match.group(0).split())
            if len(cleaned) < 30:
                continue

            start_idx = match.start()
            line_no = raw_text[:start_idx].count("\n") + 1
            clauses.append(
                {
                    "id": clause_id,
                    "text": cleaned,
                    "page": page_num,
                    "line": line_no,
                }
            )
            clause_id += 1

    return clauses


def _normalize_person_name(raw: str) -> str:
    import re

    if not raw:
        return ""

    cleaned = " ".join(str(raw).split())
    cleaned = re.sub(r"[^A-Za-z.\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\b(mr|mrs|ms|miss|shri|smt)\.?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    stop_words = {
        "the",
        "vendor",
        "vendee",
        "party",
        "agreement",
        "hereinafter",
        "called",
        "referred",
        "to",
        "as",
        "and",
        "or",
        "by",
        "of",
    }
    parts = [p for p in cleaned.split(" ") if p and p.lower() not in stop_words]
    if not parts:
        return ""

    parts = parts[:4]
    name = " ".join(p.capitalize() for p in parts if len(p) > 1)
    return name[:80].strip()


def _extract_party_name(text: str, role: str) -> str:
    import re

    if not text:
        return "Not found"

    compact = " ".join(str(text).split())
    role_l = role.lower()

    patterns = [
        # Role -> Name (e.g., "vendor: suresh kumar")
        rf"\b{role_l}\b\s*[:,-]?\s*(?:is\s+)?(?:mr\.?|mrs\.?|ms\.?|shri|smt\.?)?\s*([A-Za-z][A-Za-z.\s]{{1,80}}?)(?=,|\.|;|\bson of\b|\bwife of\b|\bresiding\b|\baged\b|$)",
        rf"\bthe\s+{role_l}\b\s*[:,-]?\s*(?:is\s+)?(?:mr\.?|mrs\.?|ms\.?|shri|smt\.?)?\s*([A-Za-z][A-Za-z.\s]{{1,80}}?)(?=,|\.|;|\bson of\b|\bwife of\b|\bresiding\b|\baged\b|$)",
        # Name -> role via legal wording
        rf"(?:mr\.?|mrs\.?|ms\.?|shri|smt\.?)?\s*([A-Za-z][A-Za-z.\s]{{1,80}}?)\s+(?:hereinafter\s+(?:called|referred\s+to\s+as)|called)\s+(?:the\s+)?{role_l}\b",
        # Name (role)
        rf"\b([A-Za-z][A-Za-z.\s]{{1,60}}?)\s*\(\s*{role_l}\s*\)",
    ]

    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _normalize_person_name(match.group(1))
        if candidate:
            return candidate

    if re.search(rf"\b{role_l}\b", compact, flags=re.IGNORECASE):
        return f"{role.title()} mentioned (name not parsed)"
    return "Not found"


def _extract_document_parties(text_data):
    full_text = "\n".join(chunk.get("text", "") for chunk in (text_data or []))
    vendor = _extract_party_name(full_text, "vendor")
    vendee = _extract_party_name(full_text, "vendee")
    return {"vendor": vendor, "vendee": vendee}


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _threshold_for_mode(scan_mode: str) -> float:
    mode = (scan_mode or "").lower()
    if "deep" in mode:
        return 0.50
    if "strict" in mode:
        return 0.85
    return 0.60


def _normalized_clause_text(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _token_set(text: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z]{3,}", _normalized_clause_text(text)))


def _numeric_tokens(text: str) -> set[str]:
    import re

    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", str(text or "")))


def _rule_based_category(text_a: str, text_b: str, similarity: float):
    a_norm = _normalized_clause_text(text_a)
    b_norm = _normalized_clause_text(text_b)
    tokens_a = _token_set(text_a)
    tokens_b = _token_set(text_b)
    common = len(tokens_a & tokens_b)
    denom = max(len(tokens_a | tokens_b), 1)
    jaccard = common / denom

    if a_norm and b_norm and a_norm == b_norm:
        return ("duplication", "DUPLICATION_EXACT", 0.99, "Exact repeated clause text.")

    if similarity >= 0.94 and jaccard >= 0.88:
        return ("duplication", "DUPLICATION_NEAR", 0.94, "Near-duplicate clause wording.")

    nums_a = _numeric_tokens(text_a)
    nums_b = _numeric_tokens(text_b)
    if jaccard >= 0.45 and nums_a and nums_b and nums_a != nums_b:
        return (
            "inconsistency",
            "NUMERIC_INCONSISTENCY",
            0.9,
            f"Numeric mismatch detected: {sorted(nums_a)} vs {sorted(nums_b)}.",
        )

    neg_words = ("shall not", "will not", "not", "never", "prohibited", "forbidden")
    pos_words = ("shall", "will", "must", "required", "permitted", "allowed")
    a_has_neg = any(w in a_norm for w in neg_words)
    b_has_neg = any(w in b_norm for w in neg_words)
    a_has_pos = any(w in a_norm for w in pos_words)
    b_has_pos = any(w in b_norm for w in pos_words)
    if jaccard >= 0.5 and ((a_has_neg and b_has_pos) or (b_has_neg and a_has_pos)):
        return ("contradiction", "LEGAL_CONFLICT", 0.9, "Opposite obligation/negation polarity.")

    return (None, None, 0.0, "")


def _analyze_clauses(clauses, threshold: float):
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.append(str(PROJECT_ROOT))

    try:
        from analysis.common_analyzer import analyze_pair
    except Exception as exc:
        raise RuntimeError(f"Analyzer import failed: {exc}") from exc

    findings = []
    line_issues = []
    counts = {"duplication": 0, "inconsistency": 0, "contradiction": 0}
    compared_pairs = 0
    max_pairs = 15000
    seen_findings = set()
    seen_line_issues = set()

    def normalize_category(label: str, reason: str, similarity: float) -> str | None:
        lbl = (label or "").upper()
        rsn = (reason or "").lower()
        if lbl in {"NUMERIC_INCONSISTENCY"}:
            return "inconsistency"
        if lbl in {"LEGAL_CONFLICT", "CONTRADICTION"}:
            return "contradiction"
        if lbl in {"DUPLICATION", "ENTAILMENT"}:
            return "duplication"
        if lbl in {"CANDIDATE", "QUALIFICATION"} and similarity >= 0.92:
            return "duplication"
        if "negation" in rsn or "conflict" in rsn:
            return "contradiction"
        return None

    for i in range(len(clauses)):
        for j in range(i + 1, len(clauses)):
            compared_pairs += 1
            if compared_pairs > max_pairs:
                break

            clause_a = clauses[i]
            clause_b = clauses[j]
            similarity = _similarity(clause_a["text"], clause_b["text"])

            category, label, confidence, reason = _rule_based_category(
                clause_a["text"], clause_b["text"], similarity
            )

            if category is None:
                label, confidence, reason = analyze_pair(
                    clause_a["text"],
                    clause_b["text"],
                    similarity,
                    threshold=threshold,
                )
                if not label or label == "NO_CONFLICT":
                    continue

                category = normalize_category(label, reason, similarity)
                if category is None:
                    continue

            finding_key = (
                category,
                clause_a["page"],
                clause_a["line"],
                clause_b["page"],
                clause_b["line"],
                label,
            )
            if finding_key in seen_findings:
                continue
            seen_findings.add(finding_key)

            findings.append(
                {
                    "issueType": label,
                    "category": category,
                    "confidence": round(float(confidence), 4),
                    "reason": reason,
                    "clause1": clause_a["text"],
                    "clause2": clause_b["text"],
                    "location1": f"Pg {clause_a['page']}, Ln {clause_a['line']}",
                    "location2": f"Pg {clause_b['page']}, Ln {clause_b['line']}",
                    "page1": clause_a["page"],
                    "line1": clause_a["line"],
                    "page2": clause_b["page"],
                    "line2": clause_b["line"],
                }
            )
            counts[category] += 1
            for clause in (clause_a, clause_b):
                line_key = (category, clause["page"], clause["line"], label)
                if line_key in seen_line_issues:
                    continue
                seen_line_issues.add(line_key)
                line_issues.append(
                    {
                        "category": category,
                        "issueType": label,
                        "confidence": round(float(confidence), 4),
                        "page": clause["page"],
                        "line": clause["line"],
                        "location": f"Pg {clause['page']}, Ln {clause['line']}",
                        "reason": reason,
                    }
                )

        if compared_pairs > max_pairs:
            break

    findings.sort(key=lambda item: item["confidence"], reverse=True)
    line_issues.sort(key=lambda item: (item["page"], item["line"]))
    return findings, line_issues, counts, compared_pairs


def _build_page_summaries(clauses, line_issues, text_data):
    pages = {}
    page_text_map = {}

    for chunk in text_data or []:
        page = int(chunk.get("page", 1))
        if page in page_text_map:
            continue
        raw = str(chunk.get("text", "") or "")
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        page_text_map[page] = " ".join(lines[:2])[:260]

    for clause in clauses:
        page = int(clause.get("page", 1))
        pages.setdefault(
            page,
            {
                "page": page,
                "clauseCount": 0,
                "duplicationCount": 0,
                "inconsistencyCount": 0,
                "contradictionCount": 0,
                "issueCount": 0,
                "keyLines": [],
                "pageSnippet": page_text_map.get(page, ""),
            },
        )
        pages[page]["clauseCount"] += 1

    for issue in line_issues:
        page = int(issue.get("page", 1))
        pages.setdefault(
            page,
            {
                "page": page,
                "clauseCount": 0,
                "duplicationCount": 0,
                "inconsistencyCount": 0,
                "contradictionCount": 0,
                "issueCount": 0,
                "keyLines": [],
                "pageSnippet": page_text_map.get(page, ""),
            },
        )
        category = issue.get("category")
        if category in {"duplication", "inconsistency", "contradiction"}:
            pages[page][f"{category}Count"] += 1
        pages[page]["issueCount"] += 1
        if len(pages[page]["keyLines"]) < 6:
            line_ref = f"Ln {issue.get('line', '-')}: {issue.get('issueType', '-')}"
            if line_ref not in pages[page]["keyLines"]:
                pages[page]["keyLines"].append(line_ref)

    page_summaries = []
    for page in sorted(pages.keys()):
        item = pages[page]
        item["summaryText"] = (
            f"Page {page} contains {item['clauseCount']} clauses and {item['issueCount']} flagged lines "
            f"(duplication: {item['duplicationCount']}, inconsistency: {item['inconsistencyCount']}, "
            f"contradiction: {item['contradictionCount']})."
        )
        page_summaries.append(item)

    return page_summaries


def _shorten_text(text: str, limit: int = 220) -> str:
    s = " ".join(str(text or "").split())
    if len(s) <= limit:
        return s
    return s[: limit - 3].rstrip() + "..."


def _clause_label(text: str, fallback_id: int) -> str:
    import re

    raw = str(text or "")
    m = re.search(r"\bclause\s*(\d+)\s*(?:\(([^)]+)\))?", raw, flags=re.IGNORECASE)
    if m:
        num = m.group(1)
        title = (m.group(2) or "").strip()
        return f"Clause {num}" + (f" ({title})" if title else "")
    return f"Clause {fallback_id}"


def _build_detailed_summary(clauses, page_summaries, findings):
    from collections import defaultdict

    clauses_by_page = defaultdict(list)
    for clause in clauses:
        clauses_by_page[int(clause.get("page", 1))].append(clause)

    lines = ["Here is the detailed summary of the document content:", ""]

    for page_item in page_summaries:
        page = int(page_item.get("page", 1))
        page_clauses = sorted(clauses_by_page.get(page, []), key=lambda c: (c.get("line", 0), c.get("id", 0)))
        lines.append(f"Page {page} Summary:")
        if not page_clauses:
            lines.append(f"- No clauses extracted for Page {page}.")
            lines.append("")
            continue

        for idx, clause in enumerate(page_clauses[:12], start=1):
            label = _clause_label(clause.get("text", ""), idx)
            summary = _shorten_text(clause.get("text", ""), 210)
            lines.append(f"- {label}: {summary} (Page {page}, Line {clause.get('line', '-')})")

        if len(page_clauses) > 12:
            lines.append(f"- Additional clauses on this page: {len(page_clauses) - 12}")
        lines.append("")

    contradictions = [f for f in findings if f.get("category") == "contradiction"]
    inconsistencies = [f for f in findings if f.get("category") == "inconsistency"]
    duplicates = [f for f in findings if f.get("category") == "duplication"]

    lines.append("Summary of Key Contradictions Noted:")
    if contradictions:
        for idx, item in enumerate(contradictions[:10], start=1):
            lines.append(
                f"- {idx}. {item.get('issueType', 'LEGAL_CONFLICT')}: "
                f"{_shorten_text(item.get('reason', ''), 170)} "
                f"({item.get('location1', '-') } vs {item.get('location2', '-')})"
            )
    else:
        lines.append("- No strong contradiction pair detected.")
    lines.append("")

    lines.append("Summary of Key Inconsistencies Noted:")
    if inconsistencies:
        for idx, item in enumerate(inconsistencies[:10], start=1):
            lines.append(
                f"- {idx}. {item.get('issueType', 'INCONSISTENCY')}: "
                f"{_shorten_text(item.get('reason', ''), 170)} "
                f"({item.get('location1', '-') } vs {item.get('location2', '-')})"
            )
    else:
        lines.append("- No strong inconsistency pair detected.")
    lines.append("")

    lines.append("Summary of Key Duplications Noted:")
    if duplicates:
        for idx, item in enumerate(duplicates[:10], start=1):
            lines.append(
                f"- {idx}. {item.get('issueType', 'DUPLICATION')}: "
                f"{_shorten_text(item.get('reason', ''), 170)} "
                f"({item.get('location1', '-') } vs {item.get('location2', '-')})"
            )
    else:
        lines.append("- No major duplication pair detected.")

    return "\n".join(lines)


# Ensure schema exists even when started via `flask run`.
init_db()


@app.get("/api/health")
def health_check():
    return jsonify({"status": "ok"}), 200


@app.get("/")
def root():
    return (
        jsonify(
            {
                "message": "Backend is running.",
                "endpoints": [
                    "GET /api/health",
                    "POST /api/register",
                    "POST /api/login",
                    "POST /api/analyze",
                    "GET /health",
                    "POST /register",
                    "POST /login",
                    "POST /analyze",
                ],
            }
        ),
        200,
    )


@app.get("/health")
def health_check_alias():
    return health_check()


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}

    full_name = str(data.get("fullName", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not full_name or not email or not password:
        return jsonify({"error": "fullName, email, and password are required."}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    password_hash = generate_password_hash(password)
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO users (full_name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (full_name, email, password_hash, created_at),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email already registered."}), 409

    return jsonify({"message": "User created successfully."}), 201


@app.post("/register")
def register_alias():
    return register()


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}

    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not email or not password:
        return jsonify({"error": "email and password are required."}), 400

    with get_db_connection() as conn:
        user = conn.execute(
            "SELECT id, full_name, email, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()

    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    return (
        jsonify(
            {
                "message": "Login successful.",
                "user": {
                    "id": user["id"],
                    "fullName": user["full_name"],
                    "email": user["email"],
                },
            }
        ),
        200,
    )


@app.post("/api/analyze")
def analyze():
    uploaded = request.files.get("file")
    scan_mode = request.form.get("scanMode", "Standard Scan (Recommended)")
    threshold = _threshold_for_mode(scan_mode)

    if uploaded is None or uploaded.filename is None or uploaded.filename.strip() == "":
        return jsonify({"error": "Please upload a file."}), 400

    file_ext = uploaded.filename.rsplit(".", 1)[-1].lower() if "." in uploaded.filename else ""
    if file_ext not in {"pdf", "docx", "txt"}:
        return jsonify({"error": "Unsupported file type. Use PDF, DOCX, or TXT."}), 400

    try:
        file_bytes = uploaded.read()
        text_data = _extract_text_data(file_bytes=file_bytes, file_ext=file_ext)
        if not text_data:
            return jsonify({"error": "Could not extract text from file."}), 400

        clauses = _extract_clauses(text_data)
        if len(clauses) < 2:
            return jsonify({"error": "Not enough clauses found for analysis."}), 400

        parties = _extract_document_parties(text_data)
        findings, line_issues, counts, compared_pairs = _analyze_clauses(
            clauses=clauses, threshold=threshold
        )
        page_summaries = _build_page_summaries(
            clauses=clauses, line_issues=line_issues, text_data=text_data
        )
        detailed_summary = _build_detailed_summary(
            clauses=clauses,
            page_summaries=page_summaries,
            findings=findings,
        )
    except Exception as exc:
        return jsonify({"error": f"Analysis failed: {exc}"}), 500

    return (
        jsonify(
            {
                "message": "Analysis completed.",
                "summary": {
                    "scanMode": scan_mode,
                    "threshold": threshold,
                    "vendor": parties["vendor"],
                    "vendee": parties["vendee"],
                    "clauses": len(clauses),
                    "pairsCompared": compared_pairs,
                    "issuesFound": len(findings),
                    "duplicationCount": counts["duplication"],
                    "inconsistencyCount": counts["inconsistency"],
                    "contradictionCount": counts["contradiction"],
                },
                "pageSummaries": page_summaries,
                "detailedSummary": detailed_summary,
                "findings": findings[:50],
                "lineIssues": line_issues[:200],
            }
        ),
        200,
    )


@app.post("/login")
def login_alias():
    return login()


@app.post("/analyze")
def analyze_alias():
    return analyze()


if __name__ == "__main__":
    # Keep defaults production-safe and compatible with restricted environments.
    debug_mode = os.getenv("FLASK_DEBUG", "0") == "1"
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port, debug=debug_mode, use_reloader=False)
