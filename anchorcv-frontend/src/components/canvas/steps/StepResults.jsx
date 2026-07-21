import MatchScoreCard from "../../MatchScoreCard";
import StepWrapper from "../StepWrapper";
import useCanvasStore from "../../../store/useCanvasStore";

function outputLabel(outputType) {
  return String(outputType || "").replaceAll("_", " ");
}

export default function StepResults({ onBack, onEditJD, onEditOutputs, onComplete }) {
  const generatedResults = useCanvasStore((state) => state.generatedResults);
  const allEntries = Object.entries(generatedResults || {});
  const strategyEntry = allEntries.find(([key]) => key === "Application_Strategy");
  const entries = allEntries.filter(([key]) => key !== "Application_Strategy");
  const hasAny = allEntries.length > 0;

  return (
    <StepWrapper
      title="Generated Results"
      description="Review each output, then continue to export."
      onBack={onBack}
      maxWidth="100%"
    >
      {!hasAny ? (
        <div className="analysis-meta-card warn">
          <p style={{ margin: 0 }}>No results available yet. Generate outputs first.</p>
        </div>
      ) : (
        <div className="stack">
          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <button type="button" className="secondary-button" onClick={onEditJD}>
              Edit Requirements
            </button>
            <button type="button" className="secondary-button" onClick={onEditOutputs}>
              Edit Outputs
            </button>
          </div>

          {strategyEntry ? (
            <div
              className="panel"
              style={{
                border: "2px solid var(--accent)",
                background: "color-mix(in srgb, var(--accent) 12%, transparent)",
                borderRadius: "var(--radius-lg, 14px)",
              }}
            >
              <p className="eyebrow" style={{ margin: 0, color: "var(--accent)" }}>
                Before you apply &mdash; read this
              </p>
              <div
                className="ai-result-content"
                style={{ marginTop: "0.6rem" }}
                dangerouslySetInnerHTML={{
                  __html:
                    strategyEntry[1]?.result_html ||
                    strategyEntry[1]?.result_text ||
                    "",
                }}
              />
            </div>
          ) : null}

          {entries.map(([outputType, result]) => (
            <details key={outputType} className="panel glass-panel" open>
              <summary style={{ cursor: "pointer", fontWeight: 700 }}>
                {outputLabel(outputType)}
              </summary>
              <div style={{ marginTop: "1rem" }}>
                {outputType === "Job_Match_Score" ? (
                  <MatchScoreCard result={result} theme="light" />
                ) : outputType === "Cover_Letter" || outputType === "Email_Template" ? (
                  <div
                    className="letter-preview"
                    dangerouslySetInnerHTML={{
                      __html: result?.result_html || result?.result_text || "",
                    }}
                  />
                ) : (
                  <div
                    className="ai-result-content"
                    dangerouslySetInnerHTML={{
                      __html: result?.result_html || result?.result_text || "",
                    }}
                  />
                )}
              </div>
            </details>
          ))}

          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <button type="button" className="primary-button" onClick={onComplete}>
              Continue to Export
            </button>
          </div>
        </div>
      )}
    </StepWrapper>
  );
}
