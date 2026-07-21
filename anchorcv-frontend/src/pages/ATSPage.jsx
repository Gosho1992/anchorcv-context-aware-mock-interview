import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { simulateATS } from "../api/client";
import ATSResultsPanel, { scoreColor } from "../components/ATSResultsPanel";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function ATSPage() {
  const [file, setFile] = useState(null);
  const [jobDescription, setJobDescription] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    document.title = "ATS Shield · AnchorCV";
  }, []);

  const mutation = useMutation({
    mutationFn: async () => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("job_description", jobDescription);
      return simulateATS(formData);
    },
    onError: (error) => {
      toast.error(error.message || "ATS simulation failed.");
    },
  });

  const result = mutation.data;

  function handleDrop(event) {
    event.preventDefault();
    setDragActive(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) setFile(dropped);
  }

  function canRun() {
    return Boolean(file) && jobDescription.trim().length > 0 && !mutation.isPending;
  }

  return (
    <section className="stack page-enter">
      <div className="panel stack">
        <div>
          <p className="eyebrow">🛡️ ATS Shield</p>
          <h2 className="page-title">Beat the Applicant Tracking System</h2>
          <p className="muted-copy">
            Upload your CV and paste the job description. ATS Shield scores how well your
            resume will pass automated screening — keywords, formatting, experience, and
            education — then suggests truthful, targeted improvements.
          </p>
        </div>

        {/* Upload + JD */}
        <div className="ats-input-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-md, 16px)" }}>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
            }}
            style={{
              border: `2px dashed ${dragActive ? scoreColor(90) : "var(--border, #cbd5e1)"}`,
              borderRadius: 12,
              padding: "28px 18px",
              textAlign: "center",
              cursor: "pointer",
              background: dragActive ? "rgba(22,163,74,0.06)" : "var(--surface-muted, #f8fafc)",
              transition: "all 0.2s ease",
              minHeight: 150,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              gap: 6,
            }}
          >
            <div style={{ fontSize: 30 }} aria-hidden="true">📄</div>
            {file ? (
              <>
                <strong>{file.name}</strong>
                <span className="muted-copy">{Math.round((file.size || 0) / 1024)} KB · click to replace</span>
              </>
            ) : (
              <>
                <strong>Drag &amp; drop your CV here</strong>
                <span className="muted-copy">or click to browse · PDF, DOCX, TXT, or image</span>
              </>
            )}
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
              style={{ display: "none" }}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </div>

          <div className="stack tight">
            <label htmlFor="ats-jd" style={{ fontWeight: 600 }}>Job description</label>
            <textarea
              id="ats-jd"
              value={jobDescription}
              onChange={(e) => setJobDescription(e.target.value)}
              placeholder="Paste the full job description here..."
              rows={7}
              style={{
                width: "100%",
                resize: "vertical",
                padding: 12,
                borderRadius: 10,
                border: "1px solid var(--border, #cbd5e1)",
                fontFamily: "inherit",
                fontSize: 14,
                background: "var(--surface, #fff)",
                color: "inherit",
              }}
            />
          </div>
        </div>

        <div className="button-row">
          <button className="primary-button" disabled={!canRun()} onClick={() => mutation.mutate()}>
            {mutation.isPending ? "Analyzing…" : "Run ATS Simulation"}
          </button>
          {result ? (
            <button
              className="secondary-button"
              onClick={() => {
                setFile(null);
                setJobDescription("");
                mutation.reset();
              }}
            >
              Reset
            </button>
          ) : null}
        </div>

        {mutation.error ? <p className="error-text">{mutation.error.message}</p> : null}
      </div>

      {/* Results */}
      {result ? <ATSResultsPanel result={result} /> : null}
    </section>
  );
}
