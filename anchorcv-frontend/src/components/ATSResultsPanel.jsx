// Extracted from ATSPage.jsx so the same score gauge, keyword pills, formatting
// issues and improvements list can be reused by the Canvas ATS flow.

export function scoreColor(score) {
  if (score >= 80) return "#16a34a"; // green
  if (score >= 65) return "#65a30d"; // lime
  if (score >= 45) return "#d97706"; // amber
  return "#dc2626"; // red
}

function severityColor(severity) {
  switch ((severity || "").toLowerCase()) {
    case "high":
      return "#dc2626";
    case "medium":
      return "#d97706";
    case "low":
      return "#0284c7";
    default:
      return "#64748b";
  }
}

function ScoreGauge({ score, label = "ATS Score" }) {
  const radius = 70;
  const stroke = 12;
  const normalized = radius - stroke / 2;
  const circumference = 2 * Math.PI * normalized;
  const clamped = Math.max(0, Math.min(100, score));
  const offset = circumference - (clamped / 100) * circumference;
  const color = scoreColor(clamped);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <svg height={radius * 2} width={radius * 2} aria-hidden="true">
        <circle
          stroke="var(--border, #e2e8f0)"
          fill="transparent"
          strokeWidth={stroke}
          r={normalized}
          cx={radius}
          cy={radius}
        />
        <circle
          stroke={color}
          fill="transparent"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${circumference} ${circumference}`}
          strokeDashoffset={offset}
          r={normalized}
          cx={radius}
          cy={radius}
          style={{ transition: "stroke-dashoffset 0.8s ease", transform: "rotate(-90deg)", transformOrigin: "50% 50%" }}
        />
        <text x="50%" y="48%" dominantBaseline="middle" textAnchor="middle" fontSize="34" fontWeight="700" fill={color}>
          {Math.round(clamped)}
        </text>
        <text x="50%" y="68%" dominantBaseline="middle" textAnchor="middle" fontSize="12" fill="var(--muted, #64748b)">
          / 100
        </text>
      </svg>
      <span className="muted-copy" style={{ fontWeight: 600 }}>{label}</span>
    </div>
  );
}

function SubScoreBar({ label, value }) {
  const color = scoreColor(value);
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ fontWeight: 600 }}>{label}</span>
        <span style={{ color, fontWeight: 700 }}>{Math.round(value)}</span>
      </div>
      <div style={{ height: 8, borderRadius: 999, background: "var(--border, #e2e8f0)", overflow: "hidden" }}>
        <div
          style={{
            width: `${Math.max(0, Math.min(100, value))}%`,
            height: "100%",
            background: color,
            borderRadius: 999,
            transition: "width 0.8s ease",
          }}
        />
      </div>
    </div>
  );
}

function Pill({ text, kind }) {
  const map = {
    present: { bg: "rgba(22,163,74,0.12)", color: "#16a34a", icon: "✅" },
    missing: { bg: "rgba(220,38,38,0.12)", color: "#dc2626", icon: "❌" },
    partial: { bg: "rgba(217,119,6,0.12)", color: "#d97706", icon: "⚠️" },
  };
  const s = map[kind] || map.present;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "4px 10px",
        borderRadius: 999,
        background: s.bg,
        color: s.color,
        fontSize: 13,
        fontWeight: 600,
        margin: "3px 4px 3px 0",
      }}
    >
      <span aria-hidden="true">{s.icon}</span>
      {text}
    </span>
  );
}


// Build a self-contained HTML report from an ATS result, for PDF/DOCX export.
export function buildATSReportHtml(result) {
  if (!result) return "";
  const kw = result.keywords || {};
  const subs = result.sub_scores || {};
  const present = (kw.present || []).join(", ") || "None";
  const partial = (kw.partial || []).join(", ") || "None";
  const missing = (kw.missing || []).join(", ") || "None";
  const issues = (result.formatting_issues || [])
    .map((i) => `<li><strong>[${String(i.severity || "").toUpperCase()}]</strong> ${i.description} &mdash; Fix: ${i.fix}</li>`)
    .join("");
  const improvements = (result.improvements || [])
    .map((i) => `<li><strong>${i.area}:</strong> ${i.before ? "Before: " + i.before + " &rarr; " : ""}After: ${i.after}${i.rationale ? " (" + i.rationale + ")" : ""}</li>`)
    .join("");
  return `
    <h1>ATS Report</h1>
    <p><strong>Overall score:</strong> ${Math.round(result.score || 0)}/100 &mdash; ${result.status || ""}</p>
    <p><strong>Optimized potential:</strong> ${Math.round(result.optimized_score || 0)}/100</p>
    <h2>Sub-scores</h2>
    <ul>
      <li>Keywords: ${Math.round(subs.keyword || 0)}</li>
      <li>Formatting: ${Math.round(subs.formatting || 0)}</li>
      <li>Experience: ${Math.round(subs.experience || 0)}</li>
      <li>Education: ${Math.round(subs.education || 0)}</li>
    </ul>
    <h2>Keywords (${kw.match_percentage || 0}% match)</h2>
    <p><strong>Present:</strong> ${present}</p>
    <p><strong>Partial:</strong> ${partial}</p>
    <p><strong>Missing:</strong> ${missing}</p>
    <h2>Formatting issues</h2>
    <ul>${issues || "<li>No major formatting issues detected.</li>"}</ul>
    <h2>Suggested improvements</h2>
    <ul>${improvements || "<li>No improvements generated.</li>"}</ul>
  `;
}

export default function ATSResultsPanel({ result }) {
  if (!result) return null;
  return (
    <>
              {/* Score overview */}
              <div className="panel">
                <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-lg, 24px)", alignItems: "center" }}>
                  <ScoreGauge score={result.score} />
                  <div style={{ flex: 1, minWidth: 260 }}>
                    <p className="eyebrow">Overall verdict</p>
                    <h3 className="page-title" style={{ margin: "2px 0 10px", color: scoreColor(result.score) }}>
                      {result.status}
                    </h3>
                    <SubScoreBar label="Keywords (40%)" value={result.sub_scores.keyword} />
                    <SubScoreBar label="Formatting (25%)" value={result.sub_scores.formatting} />
                    <SubScoreBar label="Experience (20%)" value={result.sub_scores.experience} />
                    <SubScoreBar label="Education (15%)" value={result.sub_scores.education} />
                  </div>
                </div>
              </div>
    
              {/* Optimized potential */}
              <div className="panel stack">
                <div>
                  <p className="eyebrow">Your potential</p>
                  <h3 className="page-title" style={{ margin: "2px 0" }}>Optimized score estimate</h3>
                  <p className="muted-copy">
                    If you apply the keyword and formatting fixes below, your ATS score could rise from{" "}
                    <strong>{Math.round(result.score)}</strong> to about{" "}
                    <strong style={{ color: scoreColor(result.optimized_score) }}>
                      {Math.round(result.optimized_score)}
                    </strong>.
                  </p>
                </div>
                <div style={{ position: "relative", height: 14, borderRadius: 999, background: "var(--border, #e2e8f0)", overflow: "hidden" }}>
                  <div
                    style={{
                      position: "absolute",
                      inset: 0,
                      width: `${result.optimized_score}%`,
                      background: "repeating-linear-gradient(45deg, rgba(22,163,74,0.25), rgba(22,163,74,0.25) 8px, rgba(22,163,74,0.12) 8px, rgba(22,163,74,0.12) 16px)",
                      borderRadius: 999,
                    }}
                  />
                  <div
                    style={{
                      position: "absolute",
                      inset: 0,
                      width: `${result.score}%`,
                      background: scoreColor(result.score),
                      borderRadius: 999,
                      transition: "width 0.8s ease",
                    }}
                  />
                </div>
              </div>
    
              {/* Keywords */}
              <div className="panel stack">
                <div>
                  <p className="eyebrow">Keyword match · {result.keywords.match_percentage}%</p>
                  <h3 className="page-title" style={{ margin: "2px 0" }}>Keywords</h3>
                  <p className="muted-copy">
                    {result.keywords.present.length} present · {result.keywords.partial.length} partial ·{" "}
                    {result.keywords.missing.length} missing (of {result.keywords.total_required} detected in the JD)
                  </p>
                </div>
    
                {result.keywords.present.length ? (
                  <div>
                    <p className="eyebrow">Present</p>
                    <div>{result.keywords.present.map((k) => <Pill key={`p-${k}`} text={k} kind="present" />)}</div>
                  </div>
                ) : null}
    
                {result.keywords.partial.length ? (
                  <div>
                    <p className="eyebrow">Partial</p>
                    <div>{result.keywords.partial.map((k) => <Pill key={`pa-${k}`} text={k} kind="partial" />)}</div>
                  </div>
                ) : null}
    
                {result.keywords.missing.length ? (
                  <div>
                    <p className="eyebrow">Missing</p>
                    <div>{result.keywords.missing.map((k) => <Pill key={`m-${k}`} text={k} kind="missing" />)}</div>
                  </div>
                ) : null}
    
                {!result.keywords.total_required ? (
                  <p className="muted-copy">No recognizable required skills were detected in the job description.</p>
                ) : null}
              </div>
    
              {/* Formatting issues */}
              <div className="panel stack">
                <div>
                  <p className="eyebrow">Formatting</p>
                  <h3 className="page-title" style={{ margin: "2px 0" }}>
                    Formatting issues {result.formatting_issues.length ? `(${result.formatting_issues.length})` : ""}
                  </h3>
                </div>
                {result.formatting_issues.length ? (
                  result.formatting_issues.map((issue, idx) => (
                    <div
                      key={idx}
                      style={{
                        borderLeft: `4px solid ${severityColor(issue.severity)}`,
                        padding: "10px 14px",
                        borderRadius: 8,
                        background: "var(--surface-muted, #f8fafc)",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                        <span
                          style={{
                            textTransform: "uppercase",
                            fontSize: 11,
                            fontWeight: 700,
                            color: "#fff",
                            background: severityColor(issue.severity),
                            padding: "2px 8px",
                            borderRadius: 999,
                          }}
                        >
                          {issue.severity}
                        </span>
                        <strong>{issue.description}</strong>
                      </div>
                      <p className="muted-copy" style={{ margin: "2px 0" }}>
                        <strong>Fix:</strong> {issue.fix}
                      </p>
                      <p className="muted-copy" style={{ margin: "2px 0" }}>
                        <strong>Impact:</strong> {issue.impact}
                      </p>
                    </div>
                  ))
                ) : (
                  <p className="muted-copy">✅ No major formatting issues detected.</p>
                )}
              </div>
    
              {/* Experience summary */}
              <div className="panel stack">
                <div>
                  <p className="eyebrow">Experience</p>
                  <h3 className="page-title" style={{ margin: "2px 0" }}>Experience analysis</h3>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
                  <div><span className="muted-copy">Total years</span><br /><strong style={{ fontSize: 20 }}>{result.experience.total_years}</strong></div>
                  <div><span className="muted-copy">Roles detected</span><br /><strong style={{ fontSize: 20 }}>{result.experience.job_count}</strong></div>
                  <div><span className="muted-copy">Avg tenure (yrs)</span><br /><strong style={{ fontSize: 20 }}>{result.experience.avg_tenure}</strong></div>
                  <div><span className="muted-copy">Trajectory</span><br /><strong style={{ fontSize: 20 }}>{String(result.experience.trajectory).replace(/_/g, " ")}</strong></div>
                  <div><span className="muted-copy">Employment gaps</span><br /><strong style={{ fontSize: 20 }}>{result.experience.gaps.length}</strong></div>
                </div>
                {result.experience.gaps.length ? (
                  <p className="muted-copy">
                    Gaps: {result.experience.gaps.map((g) => `${g.from}→${g.to} (${g.months} mo)`).join(", ")}
                  </p>
                ) : null}
              </div>
    
              {/* Improvements */}
              <div className="panel stack">
                <div>
                  <p className="eyebrow">Recommendations</p>
                  <h3 className="page-title" style={{ margin: "2px 0" }}>
                    Suggested improvements {result.improvements.length ? `(${result.improvements.length})` : ""}
                  </h3>
                  <p className="muted-copy">Truthful rewrites only — nothing fabricated.</p>
                </div>
                {result.improvements.length ? (
                  result.improvements.map((imp, idx) => (
                    <div key={idx} style={{ border: "1px solid var(--border, #e2e8f0)", borderRadius: 10, padding: 14 }}>
                      <span
                        style={{
                          display: "inline-block",
                          fontSize: 11,
                          fontWeight: 700,
                          textTransform: "uppercase",
                          color: "#4f46e5",
                          background: "rgba(79,70,229,0.1)",
                          padding: "2px 8px",
                          borderRadius: 999,
                          marginBottom: 8,
                        }}
                      >
                        {imp.area}
                      </span>
                      {imp.before ? (
                        <div style={{ marginBottom: 8 }}>
                          <span className="muted-copy" style={{ fontWeight: 600, color: "#dc2626" }}>Before</span>
                          <p style={{ margin: "2px 0", padding: "6px 10px", background: "rgba(220,38,38,0.07)", borderRadius: 6 }}>
                            {imp.before}
                          </p>
                        </div>
                      ) : null}
                      <div>
                        <span className="muted-copy" style={{ fontWeight: 600, color: "#16a34a" }}>After</span>
                        <p style={{ margin: "2px 0", padding: "6px 10px", background: "rgba(22,163,74,0.08)", borderRadius: 6 }}>
                          {imp.after}
                        </p>
                      </div>
                      {imp.rationale ? <p className="muted-copy" style={{ marginTop: 6 }}>💡 {imp.rationale}</p> : null}
                    </div>
                  ))
                ) : (
                  <p className="muted-copy">
                    No AI improvements were generated (the AI service may be unavailable). The keyword and
                    formatting sections above still give you concrete actions.
                  </p>
                )}
              </div>
            </>
  );
}
