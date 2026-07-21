const API_BASE = import.meta.env.VITE_API_BASE || "/api";

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
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
  });

  if (!response.ok) {
    let detail = "Request failed.";
    try {
      const body = await response.json();
      detail = body.detail || body.error || detail;
      const error = new Error(normalizeErrorDetail(detail));
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

