import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { postJson, postMultipart } from "../api/client";
import useAuthStore from "../store/useAuthStore";
import JobSearchFilters from "../components/JobSearchFilters";
import JobResultsList from "../components/JobResultsList";

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Build a self-contained HTML doc for the export endpoints when the generator
// only returned plain text.
function resultToHtml(html, text) {
  if (html && html.trim()) return html;
  const safe = escapeHtml(text || "").replace(/\n/g, "<br>");
  return `<div style="font-family:Georgia,'Times New Roman',serif;font-size:12pt;line-height:1.6;color:#1a1a1a;">${safe}</div>`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

// Generated-document types. output_type values use the backend's canonical
// strings (app/services/legacy_bridge.py): "Cover_Letter" and
// "Resume_Optimization" (the backend does not recognize "Resume_Improvement").
const DOC_TYPES = {
  cover: {
    documentType: "cover_letter",
    eyebrow: "Cover letter",
    slug: "cover-letter",
    loadingTitle: "Writing your cover letter…",
    loadingHint: "Tailoring it to this role using your CV. This can take a moment.",
  },
  resume: {
    documentType: "resume",
    eyebrow: "Tailored resume",
    slug: "tailored-resume",
    loadingTitle: "Tailoring your resume…",
    loadingHint: "Rewriting your CV to match this role. This can take a moment.",
  },
};

function safeFilename(job, slug, ext) {
  const base =
    [job?.company, job?.title]
      .filter(Boolean)
      .join("-")
      .replace(/[^a-z0-9]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || slug || "anchorcv";
  return `${base}-${slug}${ext}`;
}

// Compose the job-description text we send to the match + generation engines.
function jobToRequirementText(job) {
  return [
    job.title,
    job.company ? `Company: ${job.company}` : "",
    job.location ? `Location: ${job.location}` : "",
    job.salary ? `Salary: ${job.salary}` : "",
    "",
    job.snippet || "",
  ]
    .filter((line) => line !== undefined && line !== null)
    .join("\n")
    .trim();
}

export default function JobsPage() {
  const navigate = useNavigate();
  const accessStatus = useAuthStore((s) => s.accessStatus);
  const isBlocked = accessStatus?.access === "blocked";

  // ── CV upload ──
  const [cvFile, setCvFile] = useState(null);
  const [cvText, setCvText] = useState(""); // extracted plain text, used for generation
  const [cvExtracting, setCvExtracting] = useState(false);
  const fileInputRef = useRef(null);

  // Search filters live in <JobSearchFilters>; JobsPage reacts to results only.

  // ── Results ──
  const [jobs, setJobs] = useState(null);
  const [searchMeta, setSearchMeta] = useState(null); // { count, query }
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // ── Per-job match scores, keyed by job index ──
  // { [idx]: { loading, score, detail, error } }
  const [matches, setMatches] = useState({});

  // ── Generated-document modal state (cover letter or tailored resume) ──
  const [docJobIdx, setDocJobIdx] = useState(null);
  const [docKind, setDocKind] = useState(null); // "cover" | "resume"
  const [docLoading, setDocLoading] = useState(false);
  const [docError, setDocError] = useState("");
  const [docResult, setDocResult] = useState(null); // { html, text }
  const [exporting, setExporting] = useState(""); // "pdf" | "docx" | ""

  useEffect(() => {
    document.title = "Jobs · AnchorCV";
  }, []);

  async function handleCvFile(event) {
    const file = event.target.files?.[0] || null;
    event.target.value = "";
    if (!file) return;
    setCvFile(file);
    setCvText("");
    setError("");
    // Extract plain text from the CV so we can pass cv_text to the generator.
    setCvExtracting(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const data = await postMultipart("/discover/extract-resume", formData);
      setCvText(data?.resume_text || "");
    } catch (err) {
      const msg = err?.detail || err?.message || "Could not read your CV.";
      setError(typeof msg === "string" ? msg : "Could not read your CV.");
      setCvText("");
    } finally {
      setCvExtracting(false);
    }
  }

  function handleRemoveCv() {
    setCvFile(null);
    setCvText("");
  }

  async function handleSearch(payload) {
    if (isBlocked) return;
    if (!payload || !payload.job_title) return;

    setLoading(true);
    setError("");
    setMatches({});

    try {
      const data = await postJson("/jobs/search", payload);
      setJobs(data.jobs || []);
      setSearchMeta({ count: data.count ?? (data.jobs || []).length, query: data.query });
    } catch (err) {
      const msg = err?.detail || err?.message || "Job search failed.";
      setError(typeof msg === "string" ? msg : "Job search failed.");
      setJobs(null);
      setSearchMeta(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleMatch(job, idx) {
    if (!cvFile) {
      setError("Upload your CV first to see match scores.");
      return;
    }
    if (!cvText.trim()) {
      setError(
        cvExtracting
          ? "Still reading your CV — try again in a moment."
          : "Couldn't read text from your CV. Try a text-based PDF or DOCX."
      );
      return;
    }
    setMatches((prev) => ({ ...prev, [idx]: { loading: true } }));
    try {
      const data = await postJson("/jobs/match-score", {
        cv_text: cvText,
        job_title: job.title || "",
        company_name: job.company || "",
        job_description: jobToRequirementText(job),
      });
      setMatches((prev) => ({
        ...prev,
        [idx]: { loading: false, score: data.overall_score, detail: data },
      }));
    } catch (err) {
      const msg = err?.detail || err?.message || "Could not score this job.";
      setMatches((prev) => ({
        ...prev,
        [idx]: { loading: false, error: typeof msg === "string" ? msg : "Could not score this job." },
      }));
    }
  }

  async function handleGenerate(job, idx, kind) {
    if (!cvFile) {
      setError(`Upload your CV first to ${kind === "resume" ? "tailor your resume" : "generate a cover letter"}.`);
      return;
    }
    if (!cvText.trim()) {
      setError(
        cvExtracting
          ? "Still reading your CV — try again in a moment."
          : "Couldn't read text from your CV. Try a text-based PDF or DOCX."
      );
      return;
    }
    const cfg = DOC_TYPES[kind];
    setDocJobIdx(idx);
    setDocKind(kind);
    setDocResult(null);
    setDocError("");
    setDocLoading(true);
    try {
      const data = await postJson("/jobs/generate-document", {
        cv_text: cvText,
        job_title: job.title || "",
        company_name: job.company || "",
        location: job.location || "",
        salary: job.salary || "",
        job_description: job.snippet || "",
        document_type: cfg.documentType,
      });
      setDocResult({ html: "", text: data?.document || "" });
    } catch (err) {
      const msg = err?.detail || err?.message || "Could not generate this document.";
      setDocError(typeof msg === "string" ? msg : "Could not generate this document.");
    } finally {
      setDocLoading(false);
    }
  }

  async function handleExport(format) {
    if (!docResult || docJobIdx == null) return;
    const job = jobs?.[docJobIdx];
    const slug = DOC_TYPES[docKind]?.slug || "document";
    const ext = format === "pdf" ? ".pdf" : ".docx";
    const html = resultToHtml(docResult.html, docResult.text);
    const filename = safeFilename(job, slug, ext);
    setExporting(format);
    try {
      const blob = await postJson(`/export/${format}`, { html, filename });
      downloadBlob(blob, filename);
    } catch (err) {
      const msg = err?.detail || err?.message || `Could not export ${format.toUpperCase()}.`;
      setDocError(typeof msg === "string" ? msg : `Could not export ${format.toUpperCase()}.`);
    } finally {
      setExporting("");
    }
  }

  function closeDoc() {
    setDocJobIdx(null);
    setDocKind(null);
    setDocResult(null);
    setDocError("");
    setDocLoading(false);
  }

  const hasCv = Boolean(cvFile);

  return (
    <section className="stack page-enter" style={{ gap: "1.75rem" }}>
      {/* ── Hero / search card ── */}
      <div className="hero-gradient" style={{ position: "relative", overflow: "hidden" }}>
        <div style={{ position: "absolute", top: "-60px", right: "-40px", width: "220px", height: "220px", borderRadius: "50%", background: "radial-gradient(circle, rgba(124,111,247,0.07) 0%, transparent 70%)", pointerEvents: "none" }} />

        <div style={{ position: "relative" }}>
          <p className="eyebrow">Jobs</p>
          <h2 className="page-title" style={{ marginBottom: "0.25rem" }}>Find your next role</h2>
          <p className="muted-copy" style={{ margin: "0 0 1.1rem", maxWidth: "560px" }}>
            Search live job postings, score each against your CV, and generate a tailored cover letter or resume in seconds.
          </p>

          {/* CV upload */}
          <div style={{ marginBottom: "1.1rem" }}>
            <p className="muted-copy" style={{ fontSize: "0.82rem", fontWeight: 600, marginBottom: "0.5rem" }}>
              Your CV
            </p>
            <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
              <button
                className="secondary-button compact-button"
                onClick={() => fileInputRef.current?.click()}
                style={{ fontSize: "0.85rem" }}
              >
                {hasCv
                  ? `📄 ${cvFile.name.slice(0, 28)}${cvFile.name.length > 28 ? "…" : ""}`
                  : "📎 Upload CV (PDF / DOCX)"}
              </button>
              {hasCv && (
                <button
                  className="secondary-button compact-button"
                  onClick={handleRemoveCv}
                  style={{ fontSize: "0.78rem", opacity: 0.7 }}
                >
                  Remove
                </button>
              )}
              <span className="muted-copy" style={{ fontSize: "0.78rem" }}>
                {cvExtracting
                  ? "Reading your CV…"
                  : hasCv
                  ? "Used for match scores, cover letters & resumes"
                  : "Optional, but unlocks match scores, cover letters & tailored resumes"}
              </span>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.txt"
              onChange={handleCvFile}
              style={{ display: "none" }}
            />
          </div>

          {/* Search filters */}
          <JobSearchFilters
            onSearch={handleSearch}
            loading={loading}
            disabled={isBlocked}
            error={error}
            showExamples={!jobs}
            onUpgrade={() => navigate("/payment")}
          />
        </div>
      </div>

      {/* ── Results ── */}
      {searchMeta && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "0.5rem" }}>
          <h3 style={{ margin: 0 }}>
            {searchMeta.count} {searchMeta.count === 1 ? "result" : "results"}
          </h3>
          {searchMeta.query && (
            <span className="muted-copy" style={{ fontSize: "0.82rem" }}>for "{searchMeta.query}"</span>
          )}
        </div>
      )}

      {jobs && (
        <JobResultsList
          jobs={jobs}
          matches={matches}
          hasCv={hasCv}
          getBusy={(idx) => (docLoading && docJobIdx === idx ? docKind : null)}
          onMatch={(job, idx) => handleMatch(job, idx)}
          onCover={(job, idx) => handleGenerate(job, idx, "cover")}
          onTailorResume={(job, idx) => handleGenerate(job, idx, "resume")}
        />
      )}

      {/* ── Generated-document modal (cover letter / tailored resume) ── */}
      {docJobIdx != null && (
        <DocumentModal
          job={jobs?.[docJobIdx]}
          kind={docKind}
          loading={docLoading}
          error={docError}
          result={docResult}
          exporting={exporting}
          onExport={handleExport}
          onClose={closeDoc}
        />
      )}
    </section>
  );
}

function DocumentModal({ job, kind, loading, error, result, exporting, onExport, onClose }) {
  const cfg = DOC_TYPES[kind] || DOC_TYPES.cover;
  const loadingMessages = [
    "Reading your CV...",
    "Analysing the job description...",
    kind === "resume" ? "Crafting your tailored resume..." : "Crafting your cover letter...",
    "Almost ready...",
  ];
  const [msgIdx, setMsgIdx] = useState(0);
  useEffect(() => {
    if (!loading) {
      setMsgIdx(0);
      return undefined;
    }
    setMsgIdx(0);
    const id = setInterval(() => {
      setMsgIdx((i) => (i + 1) % loadingMessages.length);
    }, 2000);
    return () => clearInterval(id);
  }, [loading, kind]);
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", top: 0, left: 0, width: "100%", height: "100%", zIndex: 1000,
        display: "flex", alignItems: "flex-start", justifyContent: "center",
        background: "rgba(0,0,0,0.5)", padding: "1.25rem", paddingTop: "60px",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="panel stack"
        style={{ maxWidth: "600px", width: "90%", maxHeight: "80vh", overflowY: "auto", borderRadius: "12px", gap: "1rem" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.75rem" }}>
          <div>
            <p className="eyebrow">{cfg.eyebrow}</p>
            <strong style={{ fontSize: "1rem" }}>{job?.title}</strong>
            {job?.company && <p className="muted-copy" style={{ margin: "0.15rem 0 0", fontSize: "0.85rem" }}>{job.company}</p>}
          </div>
          <button className="secondary-button compact-button" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {loading && (
          <div className="stack tight" style={{ padding: "2rem 0", textAlign: "center", alignItems: "center" }}>
            <style>{`@keyframes anchorcv-spin { to { transform: rotate(360deg); } }`}</style>
            <div
              style={{
                width: "44px",
                height: "44px",
                borderRadius: "50%",
                border: "3px solid rgba(255,255,255,0.12)",
                borderTopColor: "var(--accent, #7c6ff7)",
                animation: "anchorcv-spin 1s linear infinite",
              }}
            />
            <strong style={{ marginTop: "0.9rem" }}>{loadingMessages[msgIdx]}</strong>
          </div>
        )}

        {error && !loading && <p className="error-text" style={{ margin: 0 }}>{error}</p>}

        {result && !loading && (
          <>
            <div
              style={{
                padding: "1rem 1.1rem",
                borderRadius: "var(--radius-md)", border: "1px solid var(--border)",
                background: "rgba(255,255,255,0.03)", lineHeight: 1.65, fontSize: "0.92rem",
                whiteSpace: result.html ? "normal" : "pre-wrap",
              }}
            >
              {result.html
                ? <div dangerouslySetInnerHTML={{ __html: result.html }} />
                : (result.text || "No content returned.")}
            </div>

            <div className="button-row" style={{ justifyContent: "flex-end", flexWrap: "wrap", gap: "0.5rem" }}>
              <button
                className="secondary-button compact-button"
                onClick={() => onExport("docx")}
                disabled={Boolean(exporting)}
              >
                {exporting === "docx" ? "Exporting…" : "⬇ Download DOCX"}
              </button>
              <button
                className="primary-button compact-button"
                onClick={() => onExport("pdf")}
                disabled={Boolean(exporting)}
              >
                {exporting === "pdf" ? "Exporting…" : "⬇ Download PDF"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
