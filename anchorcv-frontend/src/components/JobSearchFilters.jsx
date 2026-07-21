import { useState } from "react";

// Extracted from JobsPage.jsx. Self-contained filter controls (job title,
// country, experience, min salary, posted-within) that build a normalized
// search payload and hand it to onSearch. JobsPage.jsx imports this too.

const COUNTRY_OPTIONS = [
  { value: "", label: "🌐 Any country (defaults to UK)" },
  { value: "United Kingdom", label: "🇬🇧 United Kingdom" },
  { value: "United States", label: "🇺🇸 United States" },
  { value: "Germany", label: "🇩🇪 Germany" },
  { value: "France", label: "🇫🇷 France" },
  { value: "Australia", label: "🇦🇺 Australia" },
  { value: "Canada", label: "🇨🇦 Canada" },
  { value: "Netherlands", label: "🇳🇱 Netherlands" },
  { value: "India", label: "🇮🇳 India" },
  { value: "Poland", label: "🇵🇱 Poland" },
  { value: "Austria", label: "🇦🇹 Austria" },
];

const EXPERIENCE_OPTIONS = [
  { value: "", label: "Any experience" },
  { value: "entry", label: "Entry level" },
  { value: "mid", label: "Mid level" },
  { value: "senior", label: "Senior" },
];

const POSTED_WITHIN_OPTIONS = [
  { value: "", label: "Any time" },
  { value: "24h", label: "Last 24 hours" },
  { value: "3d", label: "Last 3 days" },
  { value: "7d", label: "Last 7 days" },
];

const EXAMPLE_TITLES = [
  "Data Analyst",
  "Software Engineer",
  "Mechanical Engineer",
  "Product Manager",
];

function FilterSelect({ label, value, onChange, options }) {
  return (
    <div className="stack tight" style={{ gap: "0.3rem" }}>
      <label className="muted-copy" style={{ fontSize: "0.78rem", fontWeight: 600 }}>{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          padding: "0.55rem 0.8rem", fontSize: "0.88rem",
          borderRadius: "var(--radius-md)", border: "1px solid var(--border)",
          background: "rgba(22,22,26,0.75)", color: "var(--text-primary)", cursor: "pointer",
        }}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  );
}

export default function JobSearchFilters({
  onSearch,
  loading = false,
  disabled = false,
  error = "",
  showExamples = true,
  onUpgrade,
}) {
  const [jobTitle, setJobTitle] = useState("");
  const [country, setCountry] = useState("");
  const [experienceLevel, setExperienceLevel] = useState("");
  const [salaryMin, setSalaryMin] = useState("");
  const [postedWithin, setPostedWithin] = useState("");

  const canSearch = !disabled && !loading && jobTitle.trim().length >= 2;

  function submit() {
    if (!canSearch) return;
    const payload = { job_title: jobTitle.trim() };
    if (country) payload.country = country;
    if (experienceLevel) payload.experience_level = experienceLevel;
    if (postedWithin) payload.posted_within = postedWithin;
    const parsedSalary = parseInt(salaryMin, 10);
    if (Number.isFinite(parsedSalary) && parsedSalary > 0) {
      payload.salary_min = parsedSalary;
    }
    onSearch && onSearch(payload);
  }

  return (
    <div className="stack tight" style={{ gap: "0.85rem" }}>
      <input
        type="text"
        value={jobTitle}
        onChange={(e) => setJobTitle(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder="Job title — e.g., Data Analyst"
        className="discovery-portal"
      />

      <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
        <FilterSelect label="Country" value={country} onChange={setCountry} options={COUNTRY_OPTIONS} />
        <FilterSelect label="Experience" value={experienceLevel} onChange={setExperienceLevel} options={EXPERIENCE_OPTIONS} />
        <FilterSelect label="Posted within" value={postedWithin} onChange={setPostedWithin} options={POSTED_WITHIN_OPTIONS} />
        <div className="stack tight" style={{ gap: "0.3rem" }}>
          <label className="muted-copy" style={{ fontSize: "0.78rem", fontWeight: 600 }}>Min salary</label>
          <input
            type="number"
            min="0"
            step="1000"
            value={salaryMin}
            onChange={(e) => setSalaryMin(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="e.g., 40000"
            style={{
              padding: "0.55rem 0.8rem", fontSize: "0.88rem",
              borderRadius: "var(--radius-md)", border: "1px solid var(--border)",
              background: "rgba(22,22,26,0.75)", color: "var(--text-primary)",
            }}
          />
        </div>
      </div>

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
        <button
          className="primary-button"
          onClick={submit}
          disabled={!canSearch}
          style={{ whiteSpace: "nowrap" }}
        >
          {loading ? "Searching…" : "Search jobs →"}
        </button>
        {disabled && onUpgrade && (
          <button className="secondary-button" onClick={onUpgrade} style={{ whiteSpace: "nowrap" }}>
            Upgrade to Premium
          </button>
        )}
      </div>

      {showExamples && !loading && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", alignItems: "center" }}>
          <span className="muted-copy" style={{ fontSize: "0.8rem" }}>Try:</span>
          {EXAMPLE_TITLES.map((t) => (
            <button key={t} className="secondary-button" onClick={() => setJobTitle(t)} style={{ padding: "0.35rem 0.85rem", fontSize: "0.78rem" }}>
              {t}
            </button>
          ))}
        </div>
      )}

      {error && <p className="error-text" style={{ margin: 0 }}>{error}</p>}
    </div>
  );
}
