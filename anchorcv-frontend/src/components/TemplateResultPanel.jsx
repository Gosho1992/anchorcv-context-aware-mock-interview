// Extracted from TemplatesPage.jsx: the Compare-&-Score result (score gauge,
// section scores, strengths / gaps / recommendations) and the converted-CV
// result (with PDF / DOCX download). Reused by TemplatesPage and the Canvas
// templates flow.

export function scoreColor(score) {
  if (score >= 75) return "var(--teal, #2dd4a8)";
  if (score >= 50) return "#f59e0b";
  return "#ef4444";
}

export default function TemplateResultPanel({
  compareResult,
  convertResult,
  onConvert,
  onExport,
  exporting = "",
  busy = false,
}) {
  return (
    <>
        {compareResult ? (
          <div className="stack result-reveal">
            <div className="analysis-meta-card" style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
              <div
                role="img"
                aria-label={`Overall score ${compareResult.overall_score} out of 100`}
                style={{
                  width: "72px",
                  height: "72px",
                  borderRadius: "50%",
                  display: "grid",
                  placeItems: "center",
                  fontSize: "1.3rem",
                  fontWeight: 800,
                  color: "#fff",
                  background: scoreColor(compareResult.overall_score),
                  flexShrink: 0,
                }}
              >
                {compareResult.overall_score}
              </div>
              <div>
                <p style={{ margin: 0, fontWeight: 700 }}>
                  Fit with {compareResult.template_name}
                </p>
                <p className="muted-copy" style={{ margin: "0.25rem 0 0" }}>
                  How your CV measures against this format's standards today.
                </p>
              </div>
            </div>

            {compareResult.section_scores?.length ? (
              <div className="analysis-meta-card">
                <p style={{ margin: "0 0 0.6rem", fontWeight: 700 }}>Section scores</p>
                <div className="stack tight">
                  {compareResult.section_scores.map((item) => (
                    <div key={item.section}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
                        <span style={{ fontWeight: 600 }}>{item.section}</span>
                        <span style={{ color: scoreColor(item.score), fontWeight: 700 }}>
                          {item.score}
                        </span>
                      </div>
                      <div
                        aria-hidden="true"
                        style={{
                          height: "6px",
                          borderRadius: "3px",
                          background: "var(--border)",
                          overflow: "hidden",
                          margin: "0.25rem 0 0.2rem",
                        }}
                      >
                        <div
                          style={{
                            width: `${item.score}%`,
                            height: "100%",
                            background: scoreColor(item.score),
                          }}
                        />
                      </div>
                      {item.comment ? (
                        <p className="muted-copy" style={{ margin: 0, fontSize: "0.85rem" }}>
                          {item.comment}
                        </p>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div
              className="card-grid"
              style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}
            >
              <div className="analysis-meta-card teal">
                <p style={{ margin: "0 0 0.5rem", fontWeight: 700 }}>Strengths</p>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(compareResult.strengths || []).map((item) => (
                    <li key={item} className="muted-copy" style={{ marginBottom: "0.3rem" }}>{item}</li>
                  ))}
                </ul>
              </div>
              <div className="analysis-meta-card warn">
                <p style={{ margin: "0 0 0.5rem", fontWeight: 700 }}>Gaps</p>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(compareResult.gaps || []).map((item) => (
                    <li key={item} className="muted-copy" style={{ marginBottom: "0.3rem" }}>{item}</li>
                  ))}
                </ul>
              </div>
              <div className="analysis-meta-card">
                <p style={{ margin: "0 0 0.5rem", fontWeight: 700 }}>Recommendations</p>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(compareResult.recommendations || []).map((item) => (
                    <li key={item} className="muted-copy" style={{ marginBottom: "0.3rem" }}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="button-row" style={{ justifyContent: "flex-start" }}>
              <button
                type="button"
                className="primary-button"
                onClick={() => onConvert && onConvert()}
                disabled={busy}
              >
                Convert my CV to this format
              </button>
            </div>
          </div>
        ) : null}

        {convertResult ? (
          <div className="stack result-reveal">
            <div className="button-row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <p style={{ margin: 0, fontWeight: 700 }}>
                Your CV in {convertResult.template_name} format
              </p>
              <div className="button-row" style={{ justifyContent: "flex-end" }}>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => onExport && onExport("pdf")}
                  disabled={exporting === "pdf"}
                >
                  {exporting === "pdf" ? "Preparing PDF..." : "Download PDF"}
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => onExport && onExport("docx")}
                  disabled={exporting === "docx"}
                >
                  {exporting === "docx" ? "Preparing DOCX..." : "Download DOCX"}
                </button>
              </div>
            </div>
            <p className="subtle-copy" style={{ margin: 0, fontSize: "0.82rem" }}>
              Anything shown as [ADD: ...] is information this format expects
              that was not in your CV — fill it in before submitting.
            </p>
            <div
              className="panel glass-panel ai-result-content"
              dangerouslySetInnerHTML={{ __html: convertResult.result_html }}
            />
          </div>
        ) : null}
    </>
  );
}
