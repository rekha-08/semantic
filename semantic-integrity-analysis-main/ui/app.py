import os
import sys
from pathlib import Path

import importlib
import json
import base64
import re

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from preprocessing.text_extractor import extract_text_from_file
from preprocessing.clause_extraction import extract_clauses
from embeddings.sbert_encoder import generate_embeddings
from storage.faiss_index import create_faiss_index
from analysis.similarity_search import get_similar

import analysis.common_analyzer
importlib.reload(analysis.common_analyzer)
from analysis.common_analyzer import analyze_pair

from analysis.nli_verifier import NLIVerifier
from analysis.llama_legal_verifier import LlamaLegalVerifier
from output.pdf_generator import generate_pdf_report
from auth.user_store import authenticate_user, create_user


APP_TITLE = "Legal Semantic Integrity"
DEFAULT_MODEL_PATH = "merged_tinyllama_instruction"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def init_state():
    st.session_state.setdefault("is_authenticated", False)
    st.session_state.setdefault("username", "")
    st.session_state.setdefault("analysis_done", False)
    st.session_state.setdefault("results", [])
    st.session_state.setdefault("line_issues", [])
    st.session_state.setdefault("uploaded_name", "")
    st.session_state.setdefault("uploaded_ext", "")
    st.session_state.setdefault("uploaded_bytes", b"")


def _extract_party_name(text: str, role: str) -> str:
    """
    Try to extract a nearby party name for vendor/vendee from clause text.
    Falls back to role-present markers when exact name is not available.
    """
    if not text:
        return "Not found"

    t = " ".join(str(text).split())
    role_l = role.lower()

    # Pattern examples:
    # "Vendor Mr. Ravi Kumar", "Vendee: Sita Devi", "the vendor, John Doe"
    patterns = [
        rf"\b{role_l}\b\s*[:,-]?\s*(?:mr\.?|mrs\.?|ms\.?)?\s*([A-Z][A-Za-z.\s]{{2,60}}?)(?=,|\.|;|\bson of\b|\bwife of\b|\bresiding\b|\baged\b|$)",
        rf"\bthe\s+{role_l}\b\s*[:,-]?\s*(?:is\s+)?(?:mr\.?|mrs\.?|ms\.?)?\s*([A-Z][A-Za-z.\s]{{2,60}}?)(?=,|\.|;|\bson of\b|\bwife of\b|\bresiding\b|\baged\b|$)",
    ]

    for pat in patterns:
        m = re.search(pat, t, flags=re.IGNORECASE)
        if m:
            name = " ".join(m.group(1).split())
            # Filter generic captures like "hereinafter called"
            if name and not re.search(r"hereinafter|called|referred|party|agreement", name, re.IGNORECASE):
                return name[:80]

    if re.search(rf"\b{role_l}\b", t, flags=re.IGNORECASE):
        return f"{role.title()} mentioned (name not parsed)"
    return "Not found"


def _clean_candidate_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name)).strip(" ,.;:-")
    if not name:
        return ""
    banned = r"hereinafter|called|referred|party|agreement|vendor|vendee|purchaser|buyer|seller"
    if re.search(banned, name, flags=re.IGNORECASE):
        return ""
    return name[:80]


def _extract_document_parties(text_data):
    full_text = "\n".join(chunk.get("text", "") for chunk in (text_data or []))
    compact = " ".join(full_text.split())
    parties = {"Vendor": "Not found", "Vendee": "Not found"}

    # Common legal intro patterns:
    # "Mr. X ... hereinafter called the VENDOR"
    # "Y ... hereinafter called the VENDEE"
    role_patterns = {
        "Vendor": [
            r"(Mr\.?|Mrs\.?|Ms\.?)?\s*([A-Z][A-Za-z.\s]{2,80}?)\s+(?:son of|wife of|daughter of|residing at|aged about|hereinafter)\b[^.]{0,120}\bvendor\b",
            r"\bvendor\b\s*[:,-]?\s*(?:is\s+)?(?:Mr\.?|Mrs\.?|Ms\.?)?\s*([A-Z][A-Za-z.\s]{2,80})(?=,|\.|;|\bson of\b|\bwife of\b|\bresiding\b|\baged\b|$)",
        ],
        "Vendee": [
            r"(Mr\.?|Mrs\.?|Ms\.?)?\s*([A-Z][A-Za-z.\s]{2,80}?)\s+(?:son of|wife of|daughter of|residing at|aged about|hereinafter)\b[^.]{0,120}\bvendee\b",
            r"\bvendee\b\s*[:,-]?\s*(?:is\s+)?(?:Mr\.?|Mrs\.?|Ms\.?)?\s*([A-Z][A-Za-z.\s]{2,80})(?=,|\.|;|\bson of\b|\bwife of\b|\bresiding\b|\baged\b|$)",
        ],
    }

    for role, patterns in role_patterns.items():
        for pat in patterns:
            m = re.search(pat, compact, flags=re.IGNORECASE)
            if not m:
                continue
            candidate = m.group(2) if (m.lastindex or 0) >= 2 else m.group(1)
            cleaned = _clean_candidate_name(candidate)
            if cleaned:
                parties[role] = cleaned
                break
        # Secondary fallback: explicit role in text without name
        if parties[role] == "Not found" and re.search(rf"\b{role.lower()}\b", compact, flags=re.IGNORECASE):
            parties[role] = f"{role} mentioned (name not parsed)"

    return parties


def _extract_parties(text1: str, text2: str, doc_parties=None):
    vendor = _extract_party_name(text1, "vendor")
    if vendor == "Not found":
        vendor = _extract_party_name(text2, "vendor")

    vendee = _extract_party_name(text1, "vendee")
    if vendee == "Not found":
        vendee = _extract_party_name(text2, "vendee")

    if doc_parties:
        if vendor in ["Not found", "Vendor mentioned (name not parsed)"] and doc_parties.get("Vendor"):
            vendor = doc_parties.get("Vendor")
        if vendee in ["Not found", "Vendee mentioned (name not parsed)"] and doc_parties.get("Vendee"):
            vendee = doc_parties.get("Vendee")

    return vendor, vendee


@st.cache_resource
def load_verifier(backend: str, llama_model_path: str):
    if backend == "llama":
        return LlamaLegalVerifier(model_path=llama_model_path)
    return NLIVerifier(model_name="cross-encoder/nli-distilroberta-base")


def apply_theme():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&display=swap');

        :root {
            --bg-soft: #f6fbff;
            --ink-900: #0b2f4a;
            --ink-700: #21506f;
            --accent-500: #0a84c6;
            --accent-700: #005b88;
            --mint-500: #2aa198;
            --warn-500: #c57b00;
            --danger-500: #c44736;
            --card-border: #dbeaf4;
        }

        html, body, [class*="css"] {
            font-family: 'Space Grotesk', sans-serif;
        }

        .stApp {
            background:
                radial-gradient(900px 420px at -15% -25%, #d7f0ff 0%, rgba(215,240,255,0) 62%),
                radial-gradient(900px 420px at 115% -20%, #fff2d8 0%, rgba(255,242,216,0) 62%),
                linear-gradient(180deg, #f8fcff 0%, #ffffff 55%);
        }

        .hero {
            border: 1px solid var(--card-border);
            background: linear-gradient(145deg, #f0f8ff 0%, #fffdf8 95%);
            border-radius: 18px;
            padding: 20px 22px;
            margin-bottom: 14px;
            box-shadow: 0 10px 24px rgba(9, 59, 102, 0.07);
            animation: fadeIn .45s ease-out;
        }

        .hero h2 {
            margin: 0;
            color: var(--ink-900);
            letter-spacing: .2px;
            font-weight: 700;
        }

        .hero p {
            margin: 8px 0 0 0;
            color: var(--ink-700);
        }

        .step {
            border-left: 4px solid var(--accent-500);
            background: #ffffff;
            border-radius: 8px;
            padding: 8px 12px;
            margin-bottom: 8px;
            font-weight: 500;
            color: #12344d;
            box-shadow: 0 6px 16px rgba(12, 53, 88, 0.05);
        }

        .mini-card {
            border: 1px solid var(--card-border);
            border-radius: 14px;
            background: #ffffff;
            padding: 14px 14px;
            margin-bottom: 10px;
            box-shadow: 0 6px 16px rgba(12, 53, 88, 0.04);
            animation: fadeIn .55s ease-out;
        }

        .mini-label {
            color: #43627c;
            font-size: 0.78rem;
            letter-spacing: .02em;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        .mini-value {
            color: #082d48;
            font-size: 1.45rem;
            font-weight: 700;
            line-height: 1.2;
        }

        .mono {
            font-family: 'IBM Plex Mono', monospace;
        }

        .tag {
            display: inline-block;
            border-radius: 999px;
            padding: 5px 10px;
            font-size: 0.75rem;
            font-weight: 600;
            margin-right: 6px;
            margin-top: 5px;
            border: 1px solid;
        }

        .tag-info { color: var(--accent-700); border-color: #b7def4; background: #ecf7ff; }
        .tag-ok { color: #186b64; border-color: #bceae5; background: #ecfffc; }
        .tag-warn { color: #8c5c00; border-color: #f2d9a4; background: #fff7e8; }
        .tag-risk { color: #9f3124; border-color: #efb5ad; background: #fff1ee; }

        [data-testid="stDataFrame"] div[role="table"] {
            border-radius: 12px;
            border: 1px solid #d6e8f4;
            overflow: hidden;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def login_page():
    col_intro, col_auth = st.columns([1.15, 1], gap="large")
    with col_intro:
        st.markdown(
            """
            <div class="hero">
                <h2>Legal Semantic Integrity Portal</h2>
                <p>Interactive contract diagnostics with line-level visibility and legal conflict tracing.</p>
                <div>
                    <span class="tag tag-info">Step 1: Secure Login</span>
                    <span class="tag tag-ok">Step 2: Upload & Analyze</span>
                    <span class="tag tag-warn">Step 3: Error-Line Dashboard</span>
                </div>
            </div>
            <div class="mini-card">
                <div class="mini-label">What You Get</div>
                <div class="mono">Duplicate clauses, legal contradictions, and exact page/line issue map.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_auth:
        st.markdown('<div class="step">Step 1 of 3: Login</div>', unsafe_allow_html=True)
        tab_login, tab_signup = st.tabs(["Sign In", "Create Account"])

        with tab_login:
            with st.form("login_form", clear_on_submit=False):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submit = st.form_submit_button("Login")

            if submit:
                ok, message = authenticate_user(username, password)
                if ok:
                    st.session_state.is_authenticated = True
                    st.session_state.username = username.strip().lower()
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

        with tab_signup:
            with st.form("signup_form", clear_on_submit=True):
                new_username = st.text_input("New Username")
                new_password = st.text_input("New Password", type="password")
                confirm_password = st.text_input("Confirm Password", type="password")
                create_submit = st.form_submit_button("Create Account")

            if create_submit:
                if new_password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    ok, message = create_user(new_username, new_password)
                    if ok:
                        st.success(message)
                    else:
                        st.error(message)

    st.caption("Local accounts are saved in data/users.db")


def run_analysis(uploaded_file, sensitivity: float, backend: str, llama_model_path: str):
    file_ext = uploaded_file.name.split(".")[-1].lower()

    with st.spinner("Extracting text..."):
        text_data = extract_text_from_file(uploaded_file, file_ext)

    if not text_data:
        st.error("Could not extract text from this file.")
        return [], []

    with st.spinner("Extracting clauses..."):
        clauses = extract_clauses(text_data)
    doc_parties = _extract_document_parties(text_data)

    if not clauses:
        st.warning("No valid clauses were detected.")
        return [], []

    with st.spinner("Building semantic index..."):
        embeddings = generate_embeddings(clauses)
        index = create_faiss_index(embeddings)

    resolved_model_path = Path(llama_model_path)
    if not resolved_model_path.is_absolute():
        resolved_model_path = PROJECT_ROOT / resolved_model_path
    verifier = load_verifier(backend=backend, llama_model_path=str(resolved_model_path))

    results = []
    seen_pairs = set()

    progress = st.progress(0)
    total = len(embeddings)

    for i, emb in enumerate(embeddings):
        idxs, dists = get_similar(index, emb, k=5)

        for j, dist in zip(idxs, dists):
            if i >= j:
                continue
            if (i, j) in seen_pairs:
                continue
            seen_pairs.add((i, j))

            similarity = 1 / (1 + dist)
            label, confidence, reason = analyze_pair(
                clauses[i]["text"],
                clauses[j]["text"],
                similarity,
                threshold=sensitivity,
            )

            if not label:
                continue

            result = {
                "Label": label,
                "Confidence": float(confidence),
                "Reason": reason,
                "Clause 1": clauses[i]["text"],
                "Clause 2": clauses[j]["text"],
                "Page 1": clauses[i]["page"],
                "Line 1": clauses[i]["line"],
                "Page 2": clauses[j]["page"],
                "Line 2": clauses[j]["line"],
                "Location 1": f"Pg {clauses[i]['page']}, Ln {clauses[i]['line']}",
                "Location 2": f"Pg {clauses[j]['page']}, Ln {clauses[j]['line']}",
            }
            vendor_name, vendee_name = _extract_parties(
                result["Clause 1"], result["Clause 2"], doc_parties=doc_parties
            )
            result["Vendor"] = vendor_name
            result["Vendee"] = vendee_name

            if backend == "llama":
                _, llm_conf, llm_label, llm_reason = verifier.predict(result["Clause 1"], result["Clause 2"])
            else:
                _, llm_conf, llm_label = verifier.predict(result["Clause 1"], result["Clause 2"])
                llm_reason = f"NLI label: {llm_label}"

            if llm_label == "Neutral":
                # Do not erase strong rule-based findings just because LLM is neutral.
                if result["Label"] in ["NUMERIC_INCONSISTENCY", "LEGAL_CONFLICT"]:
                    result["Reason"] = f"{result['Reason']} | LLM neutral review"
                else:
                    result["Label"] = "NO_CONFLICT"
                    result["Reason"] = "LLM marked as neutral"
            elif llm_label == "Entailment":
                result["Label"] = "DUPLICATION"
                result["Reason"] = "LLM marked as entailment"
            elif llm_label == "Contradiction":
                if result["Label"] in ["CANDIDATE", "QUALIFICATION"]:
                    result["Label"] = "LEGAL_CONFLICT"
                result["Reason"] = llm_reason

            result["Confidence"] = float(llm_conf)
            results.append(result)

        progress.progress((i + 1) / total)

    progress.empty()

    line_issues = []
    for r in results:
        if r["Label"] == "NO_CONFLICT":
            continue
        line_issues.append(
            {
                "Issue Type": r["Label"],
                "Confidence": round(r["Confidence"], 4),
                "Page": r["Page 1"],
                "Line": r["Line 1"],
                "Snippet": r["Clause 1"][:160],
                "Reason": r["Reason"],
                "Vendor": r.get("Vendor", "Not found"),
                "Vendee": r.get("Vendee", "Not found"),
            }
        )
        line_issues.append(
            {
                "Issue Type": r["Label"],
                "Confidence": round(r["Confidence"], 4),
                "Page": r["Page 2"],
                "Line": r["Line 2"],
                "Snippet": r["Clause 2"][:160],
                "Reason": r["Reason"],
                "Vendor": r.get("Vendor", "Not found"),
                "Vendee": r.get("Vendee", "Not found"),
            }
        )

    line_issues.sort(key=lambda item: (item["Page"], item["Line"]))

    return results, line_issues


def upload_page():
    st.markdown(
        """
        <div class="hero">
            <h2>Upload And Scan</h2>
            <p>Drop your legal document, choose model/backend, and run full semantic integrity analysis.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="step">Step 2 of 3: Upload Document</div>', unsafe_allow_html=True)

    with st.sidebar:
        st.header("Scan Settings")
        scan_mode = st.radio(
            "Select scan mode",
            (
                "Standard Scan (Recommended)",
                "Deep Search (Fuzzy)",
                "Strict (Duplicates Only)",
            ),
            index=0,
        )

        if "Standard" in scan_mode:
            sensitivity = 0.60
        elif "Deep" in scan_mode:
            sensitivity = 0.50
        else:
            sensitivity = 0.85

        # Locked configuration requested by user:
        # always use local fine-tuned Llama verifier and hide controls.
        model_backend = "llama"
        llama_model_path = DEFAULT_MODEL_PATH
        st.caption("Verifier backend: llama (fixed)")
        st.caption("Local model: merged_tinyllama_instruction (fixed)")
        st.markdown(
            f"""
            <div class="mini-card">
                <div class="mini-label">Active Mode</div>
                <div class="mini-value">{scan_mode.split('(')[0].strip()}</div>
                <div class="mono">Sensitivity: {sensitivity} | Backend: {model_backend}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    col_left, col_right = st.columns([1.35, 1], gap="large")
    with col_left:
        uploaded_file = st.file_uploader(
            "Upload a legal document",
            type=["pdf", "docx", "txt"],
            help="Supported files: PDF, DOCX, TXT",
        )
    with col_right:
        st.markdown(
            """
            <div class="mini-card">
                <div class="mini-label">Supported Inputs</div>
                <div class="mono">PDF / DOCX / TXT</div>
            </div>
            <div class="mini-card">
                <div class="mini-label">Output</div>
                <div class="mono">Pair Findings + Error-Line Dashboard + PDF/JSON Export</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if uploaded_file is None:
        st.info("Upload a file to continue.")
        return

    st.session_state.uploaded_name = uploaded_file.name
    st.session_state.uploaded_ext = uploaded_file.name.split(".")[-1].lower()
    st.session_state.uploaded_bytes = uploaded_file.getvalue()
    st.success(f"File ready: {uploaded_file.name}")

    if st.button("Run Full Analysis", type="primary"):
        try:
            results, line_issues = run_analysis(
                uploaded_file=uploaded_file,
                sensitivity=sensitivity,
                backend=model_backend,
                llama_model_path=llama_model_path,
            )
            st.session_state.results = results
            st.session_state.line_issues = line_issues
            st.session_state.analysis_done = True
            st.rerun()
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")


def dashboard_page():
    st.markdown(
        """
        <div class="hero">
            <h2>Interactive Findings Dashboard</h2>
            <p>Trace conflicts by issue type, confidence, and exact line location.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="step">Step 3 of 3: Dashboard</div>', unsafe_allow_html=True)

    results = st.session_state.results
    line_issues = st.session_state.line_issues

    if not results:
        st.warning("No results found.")
        return

    df = pd.DataFrame(results)
    df["Confidence"] = df["Confidence"].astype(float)

    issues_df = df[~df["Label"].isin(["NO_CONFLICT"])].copy()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f"""
            <div class="mini-card">
                <div class="mini-label">User</div>
                <div class="mini-value">{st.session_state.username or "N/A"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
            <div class="mini-card">
                <div class="mini-label">Pairs Reviewed</div>
                <div class="mini-value">{len(df)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"""
            <div class="mini-card">
                <div class="mini-label">Detected Issues</div>
                <div class="mini-value">{len(issues_df)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col4:
        max_conf = float(df["Confidence"].max()) if not df.empty else 0.0
        st.markdown(
            f"""
            <div class="mini-card">
                <div class="mini-label">Max Confidence</div>
                <div class="mini-value">{max_conf:.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("Issue Analytics Dashboard")
    if line_issues:
        line_df = pd.DataFrame(line_issues).copy()
        line_df["Page"] = line_df["Page"].astype(int)
        line_df["Line"] = line_df["Line"].astype(int)
        line_df["Confidence"] = line_df["Confidence"].astype(float)

        filter_col1, filter_col2, filter_col3 = st.columns([1.2, 1, 1], gap="large")
        with filter_col1:
            issue_types = sorted(line_df["Issue Type"].dropna().unique().tolist())
            issue_sel = st.multiselect("Issue Types", issue_types, default=issue_types)
        with filter_col2:
            conf_min = st.slider("Min Confidence (analytics)", 0.0, 1.0, 0.0, 0.01)
            page_min, page_max = int(line_df["Page"].min()), int(line_df["Page"].max())
            if page_min == page_max:
                st.caption(f"Single issue page: {page_min}")
                page_sel = (page_min, page_max)
            else:
                page_sel = st.slider("Page Range (analytics)", page_min, page_max, (page_min, page_max))
        with filter_col3:
            vendors = ["All"] + sorted(line_df["Vendor"].dropna().astype(str).unique().tolist())
            vendees = ["All"] + sorted(line_df["Vendee"].dropna().astype(str).unique().tolist())
            vendor_sel = st.selectbox("Vendor", vendors, index=0)
            vendee_sel = st.selectbox("Vendee", vendees, index=0)

        filtered = line_df.copy()
        if issue_sel:
            filtered = filtered[filtered["Issue Type"].isin(issue_sel)]
        filtered = filtered[filtered["Confidence"] >= conf_min]
        filtered = filtered[(filtered["Page"] >= page_sel[0]) & (filtered["Page"] <= page_sel[1])]
        if vendor_sel != "All":
            filtered = filtered[filtered["Vendor"] == vendor_sel]
        if vendee_sel != "All":
            filtered = filtered[filtered["Vendee"] == vendee_sel]

        total_issues = len(filtered)
        conflict_rate = (len(issues_df) / len(df) * 100.0) if len(df) else 0.0
        top_issue = filtered["Issue Type"].mode().iloc[0] if not filtered.empty else "N/A"
        highest_risk_page = (
            int(filtered.groupby("Page")["Confidence"].mean().idxmax()) if not filtered.empty else "N/A"
        )
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Filtered Issues", total_issues)
        k2.metric("Conflict Rate", f"{conflict_rate:.1f}%")
        k3.metric("Top Issue Type", top_issue)
        k4.metric("Highest Risk Page", highest_risk_page)

        if filtered.empty:
            st.warning("No analytics data for current filter.")
        else:
            pie_df = filtered["Issue Type"].value_counts().reset_index()
            pie_df.columns = ["Issue Type", "Count"]
            pie_fig = px.pie(
                pie_df,
                names="Issue Type",
                values="Count",
                title="Issue Type Split",
                hole=0.35,
            )
            pie_fig.update_layout(margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(pie_fig, use_container_width=True)

            top_lines = filtered.sort_values(by=["Confidence"], ascending=False).head(10)
            st.markdown("**Top 10 High-Risk Lines**")
            st.dataframe(
                top_lines[["Issue Type", "Confidence", "Page", "Line", "Vendor", "Vendee", "Snippet", "Reason"]],
                use_container_width=True,
            )
    else:
        st.info("No issue analytics data available.")

    tab_findings, tab_line_map, tab_export = st.tabs(
        ["Findings Table", "Error Line Map", "Export"]
    )

    with tab_findings:
        st.subheader("Detected Issues")
        left, right = st.columns([1, 1.1])
        with left:
            display_mode = st.radio(
                "Display mode",
                ["Issues Only", "All Analyzed Pairs"],
                horizontal=True,
            )
        with right:
            conf_threshold = st.slider("Minimum confidence", 0.0, 1.0, 0.0, 0.01)

        display_df = issues_df if display_mode == "Issues Only" else df
        display_df = display_df[display_df["Confidence"] >= conf_threshold]

        if display_mode == "Issues Only" and display_df.empty:
            st.warning("No issues match this filter.")
            st.info("Try lower confidence or switch to 'All Analyzed Pairs'.")
        elif display_df.empty:
            st.info("No analyzed pairs match this filter.")
        else:
            display_df = display_df.copy().reset_index(drop=True)
            display_df.insert(0, "S.No", range(1, len(display_df) + 1))
            cols = [
                "S.No",
                "Label",
                "Confidence",
                "Reason",
                "Location 1",
                "Location 2",
                "Clause 1",
                "Clause 2",
            ]
            st.dataframe(display_df[cols], use_container_width=True)

    with tab_line_map:
        st.subheader("Error Line Dashboard")
        if line_issues:
            line_df = pd.DataFrame(line_issues)
            labels = sorted(line_df["Issue Type"].dropna().unique().tolist())
            selected = st.multiselect("Filter issue types", labels, default=labels)
            page_min = int(line_df["Page"].min()) if not line_df.empty else 1
            page_max = int(line_df["Page"].max()) if not line_df.empty else 1
            if page_min == page_max:
                st.caption(f"Only one page with issues: Page {page_min}")
                page_range = (page_min, page_max)
            else:
                page_range = st.slider("Page range", page_min, page_max, (page_min, page_max))

            if selected:
                line_df = line_df[line_df["Issue Type"].isin(selected)]
            line_df = line_df[(line_df["Page"] >= page_range[0]) & (line_df["Page"] <= page_range[1])]

            st.dataframe(line_df, use_container_width=True)

            st.markdown("**Issue Occurrence By Line With Parties**")
            by_line = line_df.copy()
            by_line = by_line.sort_values(by=["Page", "Line", "Confidence"], ascending=[True, True, False])
            st.dataframe(
                by_line[["Issue Type", "Page", "Line", "Vendor", "Vendee", "Confidence", "Reason"]],
                use_container_width=True,
            )

            st.subheader("Jump To Error Line")
            if not line_df.empty:
                line_df = line_df.reset_index(drop=True)
                line_df.insert(0, "Item", range(1, len(line_df) + 1))
                line_df["Jump"] = line_df.apply(
                    lambda r: f"#{r['Item']} | Pg {int(r['Page'])}, Ln {int(r['Line'])} | {r['Issue Type']}",
                    axis=1,
                )
                selected_jump = st.selectbox("Select issue line", line_df["Jump"].tolist())
                chosen = line_df[line_df["Jump"] == selected_jump].iloc[0]

                c1, c2 = st.columns([1.1, 1], gap="large")
                with c1:
                    st.markdown(
                        f"""
                        <div class="mini-card">
                            <div class="mini-label">Selected Line</div>
                            <div class="mini-value">Pg {int(chosen['Page'])} · Ln {int(chosen['Line'])}</div>
                            <div class="mono">{chosen['Issue Type']} | Confidence: {float(chosen['Confidence']):.2f}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    st.caption("Snippet")
                    st.code(str(chosen["Snippet"]), language="text")
                    st.caption("Reason")
                    st.write(str(chosen["Reason"]))

                with c2:
                    is_pdf = st.session_state.uploaded_ext == "pdf"
                    if is_pdf and st.session_state.uploaded_bytes:
                        st.caption("PDF Preview (jumped to selected page)")
                        page_number = int(chosen["Page"])
                        pdf_b64 = base64.b64encode(st.session_state.uploaded_bytes).decode("utf-8")
                        pdf_html = f"""
                        <iframe
                            src="data:application/pdf;base64,{pdf_b64}#page={page_number}&zoom=110"
                            width="100%"
                            height="520"
                            style="border:1px solid #d6e8f4; border-radius: 10px;"
                        ></iframe>
                        """
                        st.markdown(pdf_html, unsafe_allow_html=True)
                    else:
                        st.info("Inline PDF preview is available for PDF uploads. Current file is not PDF.")
        else:
            st.info("No line-level issues to display.")

    with tab_export:
        st.subheader("Download Reports")
        json_payload = json.dumps(results, indent=2)
        st.download_button(
            label="Download JSON Report",
            data=json_payload,
            file_name="semantic_integrity_report.json",
            mime="application/json",
        )
        pdf_bytes = generate_pdf_report([r for r in results if r["Label"] != "NO_CONFLICT"])
        st.download_button(
            label="Download PDF Report",
            data=pdf_bytes,
            file_name="semantic_integrity_report.pdf",
            mime="application/pdf",
        )

    if st.button("Analyze Another Document"):
        st.session_state.analysis_done = False
        st.session_state.results = []
        st.session_state.line_issues = []
        st.rerun()


def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    apply_theme()
    init_state()

    top_col1, top_col2 = st.columns([5, 1])
    with top_col1:
        st.title(APP_TITLE)
    with top_col2:
        if st.session_state.is_authenticated and st.button("Logout"):
            st.session_state.is_authenticated = False
            st.session_state.username = ""
            st.session_state.analysis_done = False
            st.session_state.results = []
            st.session_state.line_issues = []
            st.rerun()

    if not st.session_state.is_authenticated:
        login_page()
        return

    if not st.session_state.analysis_done:
        upload_page()
    else:
        dashboard_page()


if __name__ == "__main__":
    main()
