// Lightweight Gmail send (no OAuth): opens Gmail's web compose window with a
// prefilled subject and body. The "to" field is intentionally left blank so the
// user chooses the recipient.

export function buildApplicationSubject(jobTitle, candidateName) {
  const title = (jobTitle || "").trim();
  const name = (candidateName || "").trim();
  if (title && name) return `Application for ${title} — ${name}`;
  if (title) return `Application for ${title}`;
  return "Job Application";
}

// Convert result HTML into plain text suitable for an email body.
export function htmlToPlainText(html) {
  if (!html) return "";
  if (typeof document === "undefined") {
    return String(html).replace(/<[^>]+>/g, "");
  }
  const el = document.createElement("div");
  el.innerHTML = html;
  const text = el.textContent || el.innerText || "";
  return text.replace(/\n{3,}/g, "\n\n").trim();
}

export function firstNonEmptyLine(text) {
  return (text || "")
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean) || "";
}

export function openGmailCompose({ subject = "", body = "" } = {}) {
  const url =
    "https://mail.google.com/mail/?view=cm&fs=1" +
    `&su=${encodeURIComponent(subject)}` +
    `&body=${encodeURIComponent(body)}`;
  window.open(url, "_blank", "noopener,noreferrer");
}
