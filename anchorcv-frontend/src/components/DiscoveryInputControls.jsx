export const INTENT_OPTIONS = [
  { value: "job", label: "Job", short: "job" },
  { value: "masters", label: "Master's", short: "Master's" },
  { value: "phd", label: "PhD", short: "PhD" },
  { value: "scholarship", label: "Scholarship", short: "scholarship" },
  { value: "bachelors", label: "Bachelor's", short: "Bachelor's" },
];

export const REGION_OPTIONS = [
  { value: "anywhere", label: "Anywhere" },
  { value: "germany", label: "Germany" },
  { value: "uk", label: "United Kingdom" },
  { value: "netherlands", label: "Netherlands" },
  { value: "canada", label: "Canada" },
  { value: "usa", label: "United States" },
  { value: "australia", label: "Australia" },
  { value: "sweden", label: "Sweden" },
  { value: "singapore", label: "Singapore" },
  { value: "japan", label: "Japan" },
];

const EXAMPLE_QUERIES = [
  "Data analyst, AI/ML, Germany",
  "Electrical engineering, power systems, PhD",
  "Public health, epidemiology, scholarship UK",
  "Computer science, fully funded Master's",
];

function ResumeWidget({ uploading, resumeFilename, resumeChars, onPickFile, onClear }) {
  const has = Boolean(resumeFilename);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
      <button
        className="secondary-button compact-button"
        onClick={onPickFile}
        disabled={uploading}
        style={{ fontSize: "0.82rem" }}
      >
        {uploading
          ? "Reading..."
          : has
          ? `File: ${resumeFilename.slice(0, 22)}${resumeFilename.length > 22 ? "..." : ""}`
          : "Upload CV (optional)"}
      </button>
      {has && !uploading && (
        <>
          <button className="secondary-button compact-button" onClick={onClear} style={{ fontSize: "0.78rem", opacity: 0.7 }}>
            Remove
          </button>
          <span className="muted-copy" style={{ fontSize: "0.76rem" }}>{resumeChars.toLocaleString()} chars</span>
        </>
      )}
    </div>
  );
}

export default function DiscoveryInputControls({
  query,
  setQuery,
  intent,
  setIntent,
  region,
  setRegion,
  loading,
  landscape,
  error,
  isBlocked,
  quotaLabel,
  resumeUploading,
  resumeFilename,
  resumeText,
  fileInputRef,
  onExplore,
  onUpgrade,
  onResumeFile,
  onClearResume,
}) {
  return (
    <div className="hero-gradient" style={{ position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: "-60px", right: "-40px", width: "220px", height: "220px", borderRadius: "50%", background: "radial-gradient(circle, rgba(124,111,247,0.07) 0%, transparent 70%)", pointerEvents: "none" }} />
      <div style={{ position: "absolute", bottom: "-50px", left: "25%", width: "160px", height: "160px", borderRadius: "50%", background: "radial-gradient(circle, rgba(45,212,168,0.05) 0%, transparent 70%)", pointerEvents: "none" }} />

      <div style={{ position: "relative" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1rem" }}>
          <div>
            <p className="eyebrow">Discover</p>
            <h2 className="page-title" style={{ marginBottom: "0.25rem" }}>What are you looking for?</h2>
            <p className="muted-copy" style={{ margin: 0, maxWidth: "560px" }}>
              Describe your background and goals. AnchorCV maps the fields, programs, and opportunities that match your profile.
            </p>
          </div>
          <span className="quota-pill">{quotaLabel}</span>
        </div>

        <div style={{ marginBottom: "1rem" }}>
          <p className="muted-copy" style={{ fontSize: "0.82rem", fontWeight: 600, marginBottom: "0.55rem" }}>I'm looking for:</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem" }}>
            {INTENT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setIntent(opt.value)}
                style={{
                  padding: "0.5rem 1.05rem",
                  borderRadius: "999px",
                  border: `1.5px solid ${intent === opt.value ? "var(--accent)" : "var(--border)"}`,
                  background: intent === opt.value ? "rgba(124,111,247,0.14)" : "rgba(255,255,255,0.04)",
                  color: intent === opt.value ? "var(--accent-soft)" : "var(--text-secondary)",
                  fontSize: "0.88rem",
                  fontWeight: intent === opt.value ? 600 : 400,
                  cursor: "pointer",
                  transition: "all 0.18s ease",
                  minHeight: "auto",
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div className="discovery-portal-row" style={{ display: "flex", gap: "0.75rem", marginBottom: "0.85rem", flexWrap: "wrap" }}>
          <input
            type="text"
            value={query || ""}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && onExplore(false)}
            placeholder="e.g., Data analyst, AI/ML, Europe"
            className="discovery-portal"
            style={{ flex: 1, minWidth: "220px" }}
          />
          <button
            className="primary-button"
            onClick={() => onExplore(false)}
            disabled={isBlocked || loading || !(query || "").trim()}
            title={isBlocked ? "Upgrade required" : undefined}
            style={{ whiteSpace: "nowrap" }}
          >
            {loading ? "Exploring..." : "Explore ->"}
          </button>
          {isBlocked ? (
            <button
              type="button"
              className="secondary-button"
              onClick={onUpgrade}
              style={{ whiteSpace: "nowrap" }}
            >
              Upgrade to Premium
            </button>
          ) : null}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span className="muted-copy" style={{ fontSize: "0.82rem", fontWeight: 600, whiteSpace: "nowrap" }}>In:</span>
            <select
              value={region}
              onChange={(event) => setRegion(event.target.value)}
              style={{
                width: "auto", minWidth: "170px", padding: "0.5rem 0.9rem",
                fontSize: "0.88rem", borderRadius: "var(--radius-md)", border: "1px solid var(--border)",
                background: "rgba(22,22,26,0.75)", color: "var(--text-primary)", cursor: "pointer",
              }}
            >
              {REGION_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          <ResumeWidget
            uploading={resumeUploading}
            resumeFilename={resumeFilename}
            resumeChars={resumeText?.length || 0}
            onPickFile={() => fileInputRef.current?.click()}
            onClear={onClearResume}
          />
          <input ref={fileInputRef} type="file" accept=".pdf,.docx,.txt" onChange={onResumeFile} style={{ display: "none" }} />
        </div>

        {!landscape && !loading && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", alignItems: "center" }}>
            <span className="muted-copy" style={{ fontSize: "0.8rem" }}>Try:</span>
            {EXAMPLE_QUERIES.map((example) => (
              <button key={example} className="secondary-button" onClick={() => setQuery(example)} style={{ padding: "0.35rem 0.85rem", fontSize: "0.78rem" }}>
                {example}
              </button>
            ))}
          </div>
        )}

        {error && <p className="error-text" style={{ margin: "0.75rem 0 0" }}>{error}</p>}
      </div>
    </div>
  );
}
