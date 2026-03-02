/* =========================================================
   ENVIRONMENT + BACKEND CONFIG
========================================================= */

// Production (Render backend)
const PROD_API_BASE = "https://semantic-1-bppi.onrender.com/api";
const PROD_ANALYZE_URL = "https://semantic-1-bppi.onrender.com/api/analyze";

// Local development
const LOCAL_API_BASE = "http://localhost:5000/api";
const LOCAL_ANALYZE_URL = "http://localhost:5000/api/analyze";

// Detect if running on Netlify
const IS_PROD = window.location.hostname.includes("netlify.app");

// Select correct backend
const API_BASES = IS_PROD ? [PROD_API_BASE] : [LOCAL_API_BASE];
const ANALYZE_URLS = IS_PROD ? [PROD_ANALYZE_URL] : [LOCAL_ANALYZE_URL];

// Detect page
const page = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();

/* =========================================================
   UTILITY FUNCTIONS
========================================================= */

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

/* =========================================================
   SESSION / AUTH HELPERS
========================================================= */

function getUser() {
  const raw = sessionStorage.getItem("lsi_user");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
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
    badge.textContent = user.fullName || user.email || "User";
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

/* =========================================================
   API CALL HELPERS
========================================================= */

async function postAuth(endpoint, payload) {
  let lastError = null;

  for (const base of API_BASES) {
    try {
      const response = await fetch(`${base}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await response.json().catch(() => null);
      return { response, data };
    } catch (err) {
      lastError = err;
    }
  }

  throw new Error("Cannot connect to backend server.");
}

async function runDocumentAnalysis(formData) {
  let lastError = null;

  for (const url of ANALYZE_URLS) {
    try {
      const response = await fetch(url, { method: "POST", body: formData });
      const data = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(data?.error || "Analysis failed.");
      }

      return data;
    } catch (err) {
      lastError = err;
    }
  }

  throw new Error("Cannot reach backend for analysis.");
}

/* =========================================================
   PAGE INITIALIZERS
========================================================= */

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

  authForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    setText(message, "", null);
    submitBtn.disabled = true;

    try {
      const payload =
        mode === "signup"
          ? {
              fullName: fullNameInput.value.trim(),
              email: emailInput.value.trim(),
              password: passwordInput.value,
            }
          : {
              email: emailInput.value.trim(),
              password: passwordInput.value,
            };

      const endpoint = mode === "signup" ? "/register" : "/login";
      const { response, data } = await postAuth(endpoint, payload);

      if (!response.ok) {
        throw new Error(data?.error || "Authentication failed.");
      }

      if (mode === "signup") {
        setText(message, "Account created. Please login.", "success");
        authForm.reset();
        setMode("login");
        return;
      }

      setUser(data.user || payload);
      window.location.href = "upload.html";
    } catch (err) {
      setText(message, err.message, "error");
    } finally {
      submitBtn.disabled = false;
    }
  });

  loginTab.addEventListener("click", () => setMode("login"));
  signupTab.addEventListener("click", () => setMode("signup"));
  setMode("login");

  if (getUser()) window.location.href = "upload.html";
}

function initUploadPage() {
  if (!ensureAuth()) return;

  const uploadForm = document.getElementById("uploadForm");
  const legalFile = document.getElementById("legalFile");
  const scanMode = document.getElementById("scanMode");
  const uploadMessage = document.getElementById("uploadMessage");
  const loadingState = document.getElementById("loadingState");

  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!legalFile.files.length) {
      setText(uploadMessage, "Please select a file.", "error");
      return;
    }

    uploadForm.classList.add("hidden");
    loadingState.classList.remove("hidden");

    try {
      const formData = new FormData();
      formData.append("file", legalFile.files[0]);
      formData.append("scanMode", scanMode.value);

      const result = await runDocumentAnalysis(formData);
      setAnalysisPayload(result);
      window.location.href = "issues.html";
    } catch (err) {
      loadingState.classList.add("hidden");
      uploadForm.classList.remove("hidden");
      setText(uploadMessage, err.message, "error");
    }
  });
}

/* =========================================================
   ROUTER
========================================================= */

if (page === "index.html" || page === "") {
  initIndexPage();
} else if (page === "upload.html") {
  initUploadPage();
}
