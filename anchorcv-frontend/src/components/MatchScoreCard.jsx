function scoreTone(score, theme = "dark") {
  if (theme === "light") {
    if (score >= 70) return { color: "#15803d", background: "rgba(21, 128, 61, 0.10)" };
    if (score >= 45) return { color: "#b45309", background: "rgba(180, 83, 9, 0.10)" };
    return { color: "#b91c1c", background: "rgba(185, 28, 28, 0.10)" };
  }
  if (score >= 70) return { color: "#22c55e", background: "rgba(34, 197, 94, 0.14)" };
  if (score >= 45) return { color: "#f59e0b", background: "rgba(245, 158, 11, 0.14)" };
  return { color: "#ef4444", background: "rgba(239, 68, 68, 0.14)" };
}

function priorityTone(priority) {
  const normalized = String(priority || "").toLowerCase();
  if (normalized === "high") {
    return {
      label: "High",
      color: "#fecaca",
      background: "rgba(239, 68, 68, 0.18)",
    };
  }
  if (normalized === "medium") {
    return {
      label: "Medium",
      color: "#fde68a",
      background: "rgba(245, 158, 11, 0.18)",
    };
  }
  return {
    label: "Low",
    color: "#bbf7d0",
    background: "rgba(34, 197, 94, 0.18)",
  };
}

function ScoreCircle({ label, score, theme = "dark" }) {
  const tone = scoreTone(Number(score || 0), theme);

  return (
    <div className="stack tight" style={{ alignItems: "center" }}>
      <div
        style={{
          width: "88px",
          height: "88px",
          borderRadius: "999px",
          display: "grid",
          placeItems: "center",
          fontSize: "1.5rem",
          fontWeight: 700,
          color: tone.color,
          background: tone.background,
          border: `2px solid ${tone.color}`,
        }}
      >
        {Number(score || 0)}
      </div>
      <span className="muted-copy" style={{ fontSize: "0.95rem" }}>
        {label}
      </span>
    </div>
  );
}

function WarningsBanner({ warnings }) {
  if (!warnings || warnings.length === 0) {
    return null;
  }

  return (
    <div className="analysis-meta-card warn">
      <div
        style={{
          fontWeight: 700,
          color: "#ef4444",
          fontSize: "0.8rem",
          letterSpacing: "0.04em",
          marginBottom: "0.5rem",
          textTransform: "uppercase",
        }}
      >
        Integrity Flags
      </div>
      <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
        {warnings.map((warning, index) => (
          <li key={`${warning}-${index}`} style={{ color: "#fca5a5" }}>
            {warning}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function MatchScoreCard({ result, theme = "dark" }) {
  const rationaleEntries = [
    ["Overall", result?.score_rationale?.overall],
    ["Skills", result?.score_rationale?.skill],
    ["Experience", result?.score_rationale?.experience],
    ["Keywords", result?.score_rationale?.keyword],
  ];

  return (
    <div className="stack" style={{ color: "inherit" }}>
      <WarningsBanner warnings={result?.warnings} />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))",
          gap: "1rem",
        }}
      >
        <ScoreCircle label="Overall" score={result?.overall_score} theme={theme} />
        <ScoreCircle label="Skills" score={result?.skill_match_score} theme={theme} />
        <ScoreCircle label="Experience" score={result?.experience_match_score} theme={theme} />
        <ScoreCircle label="Keywords" score={result?.keyword_match_score} theme={theme} />
      </div>

      <div className="stack tight">
        <strong>Summary</strong>
        <p className="muted-copy" style={{ margin: 0 }}>
          {result?.summary || "No summary returned."}
        </p>
      </div>

      <div className="stack tight">
        <strong>Strengths</strong>
        {result?.strengths?.length ? (
          <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
            {result.strengths.map((item, index) => (
              <li key={`${item}-${index}`}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className="muted-copy" style={{ margin: 0 }}>
            No strengths returned.
          </p>
        )}
      </div>

      <div className="stack tight">
        <strong>Missing Keywords</strong>
        {result?.missing_keywords?.length ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.55rem" }}>
            {result.missing_keywords.map((keyword, index) => (
              <span
                key={`${keyword}-${index}`}
                style={{
                  padding: "0.35rem 0.7rem",
                  borderRadius: "999px",
                  background: "rgba(249, 115, 22, 0.16)",
                  color: "#fdba74",
                  border: "1px solid rgba(249, 115, 22, 0.35)",
                }}
              >
                {keyword}
              </span>
            ))}
          </div>
        ) : (
          <p className="muted-copy" style={{ margin: 0 }}>
            No missing keywords returned.
          </p>
        )}
      </div>

      <div className="stack tight">
        <strong>Improvements</strong>
        {result?.improvements?.length ? (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr
                  style={{
                    textAlign: "left",
                    borderBottom: "1px solid rgba(148, 163, 184, 0.25)",
                  }}
                >
                  <th style={{ padding: "0.7rem" }}>Area</th>
                  <th style={{ padding: "0.7rem" }}>Current State</th>
                  <th style={{ padding: "0.7rem" }}>Recommendation</th>
                  <th style={{ padding: "0.7rem" }}>Priority</th>
                </tr>
              </thead>
              <tbody>
                {result.improvements.map((item, index) => {
                  const tone = priorityTone(item.priority);
                  return (
                    <tr
                      key={`${item.area}-${index}`}
                      style={{
                        borderBottom: "1px solid rgba(148, 163, 184, 0.12)",
                      }}
                    >
                      <td style={{ padding: "0.7rem", verticalAlign: "top" }}>
                        {item.area}
                      </td>
                      <td style={{ padding: "0.7rem", verticalAlign: "top" }}>
                        {item.current_state}
                      </td>
                      <td style={{ padding: "0.7rem", verticalAlign: "top" }}>
                        {item.recommendation}
                      </td>
                      <td style={{ padding: "0.7rem", verticalAlign: "top" }}>
                        <span
                          style={{
                            padding: "0.3rem 0.6rem",
                            borderRadius: "999px",
                            background: tone.background,
                            color: tone.color,
                          }}
                        >
                          {tone.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted-copy" style={{ margin: 0 }}>
            No improvements returned.
          </p>
        )}
      </div>

      <details className="preview-toggle-panel">
        <summary>Score rationale</summary>
        <div className="stack tight" style={{ marginTop: "1rem" }}>
          {rationaleEntries.map(([label, section]) => (
            <div
              key={label}
              className="stack tight"
              style={{
                padding: "1rem",
                borderRadius: "0.75rem",
                background: theme === "light"
                  ? "rgba(0, 0, 0, 0.04)"
                  : "rgba(15, 23, 42, 0.55)",
                border: theme === "light"
                  ? "1px solid rgba(0, 0, 0, 0.07)"
                  : "none",
              }}
            >
              <strong>{label}</strong>
              <p className="muted-copy" style={{ margin: 0 }}>
                {section?.explanation || "No rationale returned."}
              </p>
              <div className="stack tight">
                <span className="muted-copy">Resume quotes</span>
                {section?.resume_quotes?.length ? (
                  <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                    {section.resume_quotes.map((quote, index) => (
                      <li key={`${label}-resume-${index}`}>{quote}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted-copy" style={{ margin: 0 }}>
                    No resume quotes returned.
                  </p>
                )}
              </div>
              <div className="stack tight">
                <span className="muted-copy">Requirement quotes</span>
                {section?.requirement_quotes?.length ? (
                  <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                    {section.requirement_quotes.map((quote, index) => (
                      <li key={`${label}-req-${index}`}>{quote}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted-copy" style={{ margin: 0 }}>
                    No requirement quotes returned.
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
