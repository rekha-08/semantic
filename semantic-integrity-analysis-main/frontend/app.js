const currentHost = window.location.hostname || "127.0.0.1";

const API_BASES = [
  `http://${currentHost}:5000/api`,
  `http://${currentHost}:5001/api`,
  "http://127.0.0.1:5000/api",
  "http://localhost:5000/api",
  "http://127.0.0.1:5001/api",
  "http://localhost:5001/api",
];

const ANALYZE_URLS = [
  `http://${currentHost}:5000/api/analyze`,
  `http://${currentHost}:5000/analyze`,
  `http://${currentHost}:5001/api/analyze`,
  `http://${currentHost}:5001/analyze`,
  "http://127.0.0.1:5000/api/analyze",
  "http://127.0.0.1:5000/analyze",
  "http://localhost:5000/api/analyze",
  "http://localhost:5000/analyze",
  "http://127.0.0.1:5001/api/analyze",
  "http://127.0.0.1:5001/analyze",
  "http://localhost:5001/api/analyze",
  "http://localhost:5001/analyze",
];

const page = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setText(el, text, type = null) {
  if (!el) return;
  el.textContent = text;
  el.classList.remove("success", "error");
  if (type) el.classList.add(type);
}

function getUser() {
  const userRaw = sessionStorage.getItem("lsi_user");
  if (!userRaw) return null;
  try {
    return JSON.parse(userRaw);
  } catch {
    return null;
  }
}

function setUser(user) {
  sessionStorage.setItem("lsi_user", JSON.stringify(user));
}

function clearSession() {
  sessionStorage.removeItem("lsi_user");
  sessionStorage.removeItem("lsi_analysis_payload");
}

function getAnalysisPayload() {
  const raw = sessionStorage.getItem("lsi_analysis_payload");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function setAnalysisPayload(payload) {
  sessionStorage.setItem("lsi_analysis_payload", JSON.stringify(payload));
}

function ensureAuth() {
  const user = getUser();
  if (!user) {
    window.location.href = "index.html#home";
    return null;
  }

  const badge = document.getElementById("userBadge");
  if (badge) {
    badge.textContent = `${user.fullName || user.email || "User"}`;
  }

  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      clearSession();
      window.location.href = "index.html#home";
    });
  }

  return user;
}

async function postAuth(endpoint, payload) {
  let response = null;
  let data = null;
  let lastNetworkError = null;

  for (const base of API_BASES) {
    try {
      response = await fetch(`${base}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      data = await response.json().catch(() => null);
      lastNetworkError = null;
      break;
    } catch (error) {
      lastNetworkError = error;
    }
  }

  if (lastNetworkError) {
    throw new Error(`Cannot reach backend at ${API_BASES.join(", ")}.`);
  }

  return { response, data };
}

async function runDocumentAnalysis(formData) {
  let response = null;
  let data = null;
  let lastNetworkError = null;
  let status = null;

  for (const url of ANALYZE_URLS) {
    try {
      response = await fetch(url, { method: "POST", body: formData });
      data = await response.json().catch(() => null);
      status = response.status;
      lastNetworkError = null;
      if (response.status !== 404) break;
    } catch (error) {
      lastNetworkError = error;
    }
  }

  if (lastNetworkError) {
    throw new Error("Cannot connect to backend for analysis.");
  }

  if (!response.ok) {
    throw new Error(data?.error || `Analysis request failed with HTTP ${status || response.status}.`);
  }

  return data;
}

function buildIssueRows(lineIssues, category) {
  const rows = lineIssues
    .filter((item) => item.category === category)
    .slice(0, 80)
    .map(
      (item) => `
      <tr>
        <td>${escapeHtml(item.location || `Pg ${item.page}, Ln ${item.line}`)}</td>
        <td>${escapeHtml(item.issueType || "-")}</td>
        <td>${escapeHtml(item.confidence ?? "-")}</td>
      </tr>
    `
    )
    .join("");

  if (!rows) {
    return `<p class="result-muted">No ${category} lines detected.</p>`;
  }

  return `
    <div class="table-wrap">
      <table class="result-table">
        <thead>
          <tr>
            <th>Page/Line</th>
            <th>Issue Type</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function initIndexPage() {
  const loginTab = document.getElementById("loginTab");
  const signupTab = document.getElementById("signupTab");
  const authForm = document.getElementById("authForm");
  const nameField = document.getElementById("nameField");
  const fullNameInput = document.getElementById("fullName");
  const emailInput = document.getElementById("email");
  const passwordInput = document.getElementById("password");
  const submitBtn = document.getElementById("submitBtn");
  const formSubtitle = document.getElementById("formSubtitle");
  const message = document.getElementById("message");

  let mode = "login";

  function setMode(nextMode) {
    mode = nextMode;
    const isSignup = mode === "signup";
    signupTab.classList.toggle("active", isSignup);
    loginTab.classList.toggle("active", !isSignup);
    nameField.classList.toggle("hidden", !isSignup);
    submitBtn.textContent = isSignup ? "Create Account" : "Login";
    formSubtitle.textContent = isSignup
      ? "Create your account to start securely."
      : "Enter your credentials to access your account.";
    fullNameInput.required = isSignup;
    setText(message, "", null);
  }

  async function handleAuthSubmit(event) {
    event.preventDefault();
    setText(message, "", null);

    const email = emailInput.value.trim();
    const password = passwordInput.value;
    const fullName = fullNameInput.value.trim();

    if (!email || !password || (mode === "signup" && !fullName)) {
      setText(message, "Please fill all required fields.", "error");
      return;
    }

    submitBtn.disabled = true;

    try {
      const endpoint = mode === "signup" ? "/register" : "/login";
      const payload = mode === "signup" ? { fullName, email, password } : { email, password };
      const { response, data } = await postAuth(endpoint, payload);

      if (!response.ok) {
        throw new Error(data?.error || `Request failed with HTTP ${response.status}.`);
      }

      if (mode === "signup") {
        setText(message, "Account created. Please login now.", "success");
        authForm.reset();
        setMode("login");
        return;
      }

      const user = data?.user || { fullName: fullName || email, email };
      setUser(user);
      window.location.href = "upload.html";
    } catch (error) {
      setText(message, error.message || "Something went wrong.", "error");
    } finally {
      submitBtn.disabled = false;
    }
  }

  loginTab.addEventListener("click", () => setMode("login"));
  signupTab.addEventListener("click", () => setMode("signup"));
  authForm.addEventListener("submit", handleAuthSubmit);
  setMode("login");

  if (getUser()) {
    window.location.href = "upload.html";
  }
}

function initUploadPage() {
  if (!ensureAuth()) return;

  const uploadForm = document.getElementById("uploadForm");
  const legalFile = document.getElementById("legalFile");
  const scanMode = document.getElementById("scanMode");
  const uploadMessage = document.getElementById("uploadMessage");
  const loadingState = document.getElementById("loadingState");
  const analysisInputSummary = document.getElementById("analysisInputSummary");

  legalFile.addEventListener("change", () => {
    if (!legalFile.files || !legalFile.files[0]) return;
    const selectedFile = legalFile.files[0];
    analysisInputSummary.classList.remove("hidden");
    analysisInputSummary.innerHTML = `
      <p><strong>File:</strong> ${escapeHtml(selectedFile.name)}</p>
      <p><strong>Type:</strong> ${escapeHtml(selectedFile.type || "unknown")}</p>
      <p><strong>Size:</strong> ${escapeHtml((selectedFile.size / 1024).toFixed(2))} KB</p>
      <p><strong>Scan Mode:</strong> ${escapeHtml(scanMode.value)}</p>
    `;
    setText(uploadMessage, `Selected: ${selectedFile.name}`, "success");
  });

  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setText(uploadMessage, "", null);

    if (!legalFile.files || legalFile.files.length === 0) {
      setText(uploadMessage, "Please choose a file to continue.", "error");
      return;
    }

    const selectedFile = legalFile.files[0];
    const selectedScanMode = scanMode.value;

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("scanMode", selectedScanMode);

    uploadForm.classList.add("hidden");
    loadingState.classList.remove("hidden");

    try {
      const payload = await runDocumentAnalysis(formData);
      payload._meta = {
        fileName: selectedFile.name,
        fileType: selectedFile.type || "unknown",
        fileSizeKb: Number((selectedFile.size / 1024).toFixed(2)),
      };
      setAnalysisPayload(payload);
      window.location.href = "issues.html";
    } catch (error) {
      loadingState.classList.add("hidden");
      uploadForm.classList.remove("hidden");
      setText(uploadMessage, error.message || "Analysis failed.", "error");
    }
  });
}

function initIssuesPage() {
  if (!ensureAuth()) return;

  const payload = getAnalysisPayload();
  if (!payload) {
    window.location.href = "upload.html";
    return;
  }

  const summary = payload.summary || {};
  const lineIssues = Array.isArray(payload.lineIssues) ? payload.lineIssues : [];

  const issueStats = document.getElementById("issueStats");
  issueStats.innerHTML = `
    <article class="stat-card stat-dup">
      <h3>Duplication</h3>
      <p>${escapeHtml(summary.duplicationCount ?? 0)}</p>
    </article>
    <article class="stat-card stat-inc">
      <h3>Inconsistency</h3>
      <p>${escapeHtml(summary.inconsistencyCount ?? 0)}</p>
    </article>
    <article class="stat-card stat-con">
      <h3>Contradiction</h3>
      <p>${escapeHtml(summary.contradictionCount ?? 0)}</p>
    </article>
  `;

  const lineIssueTables = document.getElementById("lineIssueTables");
  lineIssueTables.innerHTML = `
    <section class="result-card">
      <h4>Duplication Lines</h4>
      ${buildIssueRows(lineIssues, "duplication")}
    </section>
    <section class="result-card">
      <h4>Inconsistency Lines</h4>
      ${buildIssueRows(lineIssues, "inconsistency")}
    </section>
    <section class="result-card">
      <h4>Contradiction Lines</h4>
      ${buildIssueRows(lineIssues, "contradiction")}
    </section>
  `;
}

function initSummaryPage() {
  if (!ensureAuth()) return;

  const payload = getAnalysisPayload();
  if (!payload) {
    window.location.href = "upload.html";
    return;
  }

  const summary = payload.summary || {};
  const findings = Array.isArray(payload.findings) ? payload.findings : [];
  const pageSummaries = Array.isArray(payload.pageSummaries) ? payload.pageSummaries : [];
  const lineIssues = Array.isArray(payload.lineIssues) ? payload.lineIssues : [];
  const detailedSummary = String(payload.detailedSummary || "").trim();
  const meta = payload._meta || {};

  const summaryDetails = document.getElementById("summaryDetails");
  summaryDetails.innerHTML = `
    <article class="summary-item"><span>File</span><strong>${escapeHtml(meta.fileName || "-")}</strong></article>
    <article class="summary-item"><span>Scan Mode</span><strong>${escapeHtml(summary.scanMode || "-")}</strong></article>
    <article class="summary-item"><span>Threshold</span><strong>${escapeHtml(summary.threshold ?? "-")}</strong></article>
    <article class="summary-item"><span>Vendor</span><strong>${escapeHtml(summary.vendor || "Not found")}</strong></article>
    <article class="summary-item"><span>Vendee</span><strong>${escapeHtml(summary.vendee || "Not found")}</strong></article>
    <article class="summary-item"><span>Clauses</span><strong>${escapeHtml(summary.clauses ?? 0)}</strong></article>
    <article class="summary-item"><span>Pairs Compared</span><strong>${escapeHtml(summary.pairsCompared ?? 0)}</strong></article>
    <article class="summary-item"><span>Total Issues</span><strong>${escapeHtml(summary.issuesFound ?? 0)}</strong></article>
  `;

  const findingsBoard = document.getElementById("findingsBoard");
  const pageSummaryBoard = document.getElementById("pageSummaryBoard");
  const detailedSummaryText = document.getElementById("detailedSummaryText");
  const lineErrorDashboard = document.getElementById("lineErrorDashboard");

  if (detailedSummaryText) {
    detailedSummaryText.textContent = detailedSummary || "Detailed summary is not available for this document.";
  }

  if (pageSummaryBoard) {
    if (pageSummaries.length === 0) {
      pageSummaryBoard.innerHTML =
        `<article class="result-card"><p class="result-muted">No page-wise summary available for this document.</p></article>`;
    } else {
      pageSummaryBoard.innerHTML = pageSummaries
        .map((item) => {
          const keyLines = Array.isArray(item.keyLines) ? item.keyLines : [];
          const keyLineHtml = keyLines.length
            ? keyLines.map((k) => `<li>${escapeHtml(k)}</li>`).join("")
            : "<li>No flagged lines on this page.</li>";
          return `
          <article class="result-card">
            <h4>Page ${escapeHtml(item.page)}</h4>
            <p><strong>Clauses:</strong> ${escapeHtml(item.clauseCount ?? 0)}</p>
            <p><strong>Issues:</strong> ${escapeHtml(item.issueCount ?? 0)} (Duplication: ${escapeHtml(item.duplicationCount ?? 0)}, Inconsistency: ${escapeHtml(item.inconsistencyCount ?? 0)}, Contradiction: ${escapeHtml(item.contradictionCount ?? 0)})</p>
            <p><strong>Page Snippet:</strong> ${escapeHtml(item.pageSnippet || "-")}</p>
            <p><strong>Summary:</strong> ${escapeHtml(item.summaryText || "-")}</p>
            <p><strong>Key Lines:</strong></p>
            <ul>${keyLineHtml}</ul>
          </article>
        `;
        })
        .join("");
    }
  }

  if (findings.length === 0) {
    findingsBoard.innerHTML = `<article class="result-card"><p class="result-muted">No major findings detected for this document.</p></article>`;
    return;
  }

  const topFindings = findings.slice(0, 20);
  findingsBoard.innerHTML = topFindings
    .map(
      (item) => `
      <article class="result-card">
        <h4>${escapeHtml(item.category || "issue")} - ${escapeHtml(item.issueType || "-")}</h4>
        <p><strong>Confidence:</strong> ${escapeHtml(item.confidence ?? "-")}</p>
        <p><strong>Location A:</strong> ${escapeHtml(item.location1 || "-")}</p>
        <p><strong>Location B:</strong> ${escapeHtml(item.location2 || "-")}</p>
        <p><strong>Reason:</strong> ${escapeHtml(item.reason || "-")}</p>
      </article>
    `
    )
    .join("");

  if (lineErrorDashboard) {
    if (lineIssues.length === 0) {
      lineErrorDashboard.innerHTML = `<p class="result-muted">No line-level errors detected.</p>`;
      return;
    }

    const rows = lineIssues
      .slice(0, 200)
      .map(
        (item) => `
        <tr>
          <td>${escapeHtml(item.location || `Pg ${item.page}, Ln ${item.line}`)}</td>
          <td>${escapeHtml(item.category || "-")}</td>
          <td>${escapeHtml(item.issueType || "-")}</td>
          <td>${escapeHtml(item.confidence ?? "-")}</td>
          <td>${escapeHtml(item.reason || "-")}</td>
        </tr>
      `
      )
      .join("");

    lineErrorDashboard.innerHTML = `
      <div class="table-wrap">
        <table class="result-table">
          <thead>
            <tr>
              <th>Page/Line</th>
              <th>Category</th>
              <th>Issue Type</th>
              <th>Confidence</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }
}

if (page === "index.html" || page === "") {
  initIndexPage();
} else if (page === "upload.html") {
  initUploadPage();
} else if (page === "issues.html") {
  initIssuesPage();
} else if (page === "summary.html") {
  initSummaryPage();
} else if (page === "workflow.html") {
  window.location.href = "upload.html";
}
