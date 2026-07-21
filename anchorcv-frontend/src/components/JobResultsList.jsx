// Extracted from JobsPage.jsx so the same job-card list (match badge, salary /
// posted / source pills, action buttons) can be reused by the Canvas job-search
// flow. JobsPage.jsx imports this too.

function scoreColor(score) {
  if (score >= 75) return "var(--accent-teal, #2dd4a8)";
  if (score >= 50) return "var(--accent)";
  if (score >= 30) return "#f59e0b";
  return "#ef4444";
}

function scoreLabel(score) {
  if (score >= 75) return "Strong match";
  if (score >= 50) return "Good match";
  if (score >= 30) return "Partial match";
  return "Low match";
}

function formatPostedAt(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const days = Math.round((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days} days ago`;
  return date.toLocaleDateString();
}

function MatchBadge({ score }) {
  const color = scoreColor(score);
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "0.4rem",
      padding: "0.25rem 0.7rem", borderRadius: "999px",
      background: "rgba(255,255,255,0.05)", border: `1.5px solid ${color}`,
      color, fontWeight: 700, fontSize: "0.82rem", whiteSpace: "nowrap",
    }}>
      🎯 {score}/100 · {scoreLabel(score)}
    </span>
  );
}

function JobCard({ job, match, hasCv, busy, onMatch, onCover, onTailorResume }) {
  const posted = formatPostedAt(job.posted_at);
  return (
    <div className="panel stack tight" style={{ gap: "0.6rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.75rem", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: "200px" }}>
          <strong style={{ fontSize: "1rem" }}>{job.title}</strong>
          <p className="muted-copy" style={{ margin: "0.2rem 0 0", fontSize: "0.88rem" }}>
            {job.company}{job.location ? ` · ${job.location}` : ""}
          </p>
        </div>
        {match?.score != null && !match.loading && <MatchBadge score={match.score} />}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
        {job.salary && (
          <span className="quota-pill" style={{ fontSize: "0.76rem" }}>💰 {job.salary}</span>
        )}
        {posted && (
          <span className="quota-pill" style={{ fontSize: "0.76rem" }}>🗓️ {posted}</span>
        )}
        {job.source && (
          <span className="quota-pill" style={{ fontSize: "0.76rem" }}>via {job.source}</span>
        )}
      </div>

      {job.snippet && (
        <p className="muted-copy" style={{ margin: 0, fontSize: "0.85rem", lineHeight: 1.55 }}>
          {job.snippet}
        </p>
      )}

      {match?.error && <p className="error-text" style={{ margin: 0, fontSize: "0.8rem" }}>{match.error}</p>}

      <div className="button-row" style={{ justifyContent: "flex-start", flexWrap: "wrap", gap: "0.5rem" }}>
        {job.url && (
          <a className="secondary-button compact-button" href={job.url} target="_blank" rel="noopener noreferrer">
            View posting ↗
          </a>
        )}
        <button
          className="secondary-button compact-button"
          onClick={onMatch}
          disabled={!hasCv || match?.loading}
          title={hasCv ? undefined : "Upload your CV to see a match score"}
        >
          {match?.loading ? "Scoring…" : match?.score != null ? "Re-score" : "Check match"}
        </button>
        <button
          className="secondary-button compact-button"
          onClick={onTailorResume}
          disabled={!hasCv || Boolean(busy)}
          title={hasCv ? undefined : "Upload your CV to tailor your resume"}
        >
          {busy === "resume" ? "Tailoring…" : "Tailor Resume"}
        </button>
        <button
          className="primary-button compact-button"
          onClick={onCover}
          disabled={!hasCv || Boolean(busy)}
          title={hasCv ? undefined : "Upload your CV to generate a cover letter"}
        >
          {busy === "cover" ? "Writing…" : "Cover letter →"}
        </button>
      </div>
    </div>
  );
}

export default function JobResultsList({
  jobs,
  matches = {},
  hasCv,
  getBusy,
  onMatch,
  onCover,
  onTailorResume,
}) {
  if (!jobs) return null;
  if (jobs.length === 0) {
    return (
      <div className="panel stack tight">
        <strong>No jobs found.</strong>
        <p className="muted-copy" style={{ margin: 0 }}>
          Try a broader job title, a different country, or relaxing the salary and date filters.
        </p>
      </div>
    );
  }
  return (
    <div className="stack tight" style={{ gap: "1rem" }}>
      {jobs.map((job, idx) => (
        <JobCard
          key={`${job.url || "job"}-${idx}`}
          job={job}
          match={matches[idx]}
          hasCv={hasCv}
          busy={getBusy ? getBusy(idx) : null}
          onMatch={() => onMatch && onMatch(job, idx)}
          onCover={() => onCover && onCover(job, idx)}
          onTailorResume={() => onTailorResume && onTailorResume(job, idx)}
        />
      ))}
    </div>
  );
}
