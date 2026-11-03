const API_BASE = import.meta.env.VITE_API_BASE || "/api";

// One id per mock interview. The backend forwards it to Otari as
// Otari-Conversation-Id, so each interview reads as one session in Otari.
let interviewSessionId = "";

export function startInterviewSession() {
  interviewSessionId =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? `interview-${crypto.randomUUID()}`
      : `interview-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return interviewSessionId;
}

export function setInterviewSessionId(id) {
  interviewSessionId = id || "";
}

// Otari refusals the user can act on (see app/services/otari_errors.py).
function policyMessage(body) {
  if (body?.code === "budget_exceeded") {
    return "You've used this period's AI allowance for your plan. It resets automatically — or upgrade to the Season Pass for a larger daily allowance.";
  }
  if (body?.code === "guardrail_violation") {
    return "AnchorCV's integrity check found text that tries to instruct the AI evaluator (for example hidden \"rate this candidate 10/10\" instructions in a CV, job page or answer). Remove it and try again.";
  }
  return "";
}

function normalizeErrorDetail(detail) {
  if (!detail) {
    return "Request failed.";
  }

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    const normalized = detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (typeof item?.msg === "string" && item.msg.trim()) {
          return item.msg;
        }
        try {
          return JSON.stringify(item);
        } catch {
          return String(item);
        }
      })
      .filter(Boolean);

    return normalized.join(", ") || "Request failed.";
  }

  if (typeof detail?.message === "string" && detail.message.trim()) {
    return detail.message;
  }

  if (typeof detail?.detail === "string" && detail.detail.trim()) {
    return detail.detail;
  }

  try {
    return JSON.stringify(detail);
  } catch {
    return "Request failed.";
  }
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (interviewSessionId && path.startsWith("/interview/")) {
    headers["X-AnchorCV-Session"] = interviewSessionId;
  }
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
    headers,
  });

  if (!response.ok) {
    let detail = "Request failed.";
    try {
      const body = await response.json();
      detail = body.detail || body.error || detail;
      const error = new Error(policyMessage(body) || normalizeErrorDetail(detail));
      error.code = body.code || "";
      error.detail = body.detail ?? body.error ?? detail;
      error.status = response.status;
      error.body = body;
      throw error;
    } catch (error) {
      if (error instanceof Error && "detail" in error) {
        throw error;
      }
      detail = response.statusText || detail;
    }

    const error = new Error(normalizeErrorDetail(detail));
    error.detail = detail;
    error.status = response.status;
    throw error;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  return response.blob();
}

export function getJson(path) {
  return request(path, { method: "GET" });
}

export function getCurrentUser() {
  return getJson("/auth/me");
}

export function login(payload) {
  return request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function register(payload) {
  return request("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function logout() {
  return request("/auth/logout", { method: "POST" });
}

export function postMultipart(path, formData) {
  return request(path, {
    method: "POST",
    body: formData,
  });
}

export function postJson(path, payload) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function importJobFromUrl(url, researchCompany = true) {
  return postJson("/interview/import-job", { url, research_company: researchCompany });
}

export function listFiles() {
  return getJson("/files");
}

export function uploadFile(formData) {
  return request("/files/upload", {
    method: "POST",
    body: formData,
  });
}

export function deleteFile(fileId) {
  return request(`/files/${fileId}`, { method: "DELETE" });
}

export function getFileDownloadUrl(fileId) {
  return `${API_BASE}/files/${fileId}/download`;
}

export function simulateATS(formData) {
  return request("/ats/simulate", {
    method: "POST",
    body: formData,
  });
}

export function startContextEvidenceSession(payload) {
  return postJson("/resume-defense/sessions", payload);
}


export function submitContextEvidenceAnswer(sessionId, payload) {
  return postJson(`/resume-defense/sessions/${encodeURIComponent(sessionId)}/answers`, payload);
}

export function getInterviewEvidenceMatrix(sessionId) {
  return getJson(`/resume-defense/sessions/${encodeURIComponent(sessionId)}/matrix`);
}

export function getInterviewEvidenceRewrites(sessionId) {
  return getJson(`/resume-defense/sessions/${encodeURIComponent(sessionId)}/rewrites`);
}

