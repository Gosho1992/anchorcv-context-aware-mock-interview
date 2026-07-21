import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ATSResultsPanel, { buildATSReportHtml } from "../../ATSResultsPanel";
import LoadingQuotes from "../../LoadingQuotes";
import StepWrapper from "../StepWrapper";
import { simulateATS } from "../../../api/client";
import useCanvasStore from "../../../store/useCanvasStore";
import { trackCanvasEvent } from "../../../utils/canvasAnalytics";

const LOADING_QUOTES = [
  "Scanning your CV for ATS keywords...",
  "Checking formatting for parser traps...",
  "Scoring keywords, formatting, experience and education...",
  "Comparing your CV against the job description...",
  "Preparing truthful, targeted improvement suggestions...",
];

export default function StepATSResults({ onComplete, onBack }) {
  const navigate = useNavigate();
  const uploadedCV = useCanvasStore((state) => state.uploadedCV);
  const cvText = useCanvasStore((state) => state.cvText);
  const cvFileName = useCanvasStore((state) => state.cvFileName);
  const jdText = useCanvasStore((state) => state.jdText);
  const currentFlow = useCanvasStore((state) => state.currentFlow);
  const setGeneratedResults = useCanvasStore((state) => state.setGeneratedResults);
  const setIsProcessing = useCanvasStore((state) => state.setIsProcessing);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [premiumBlocked, setPremiumBlocked] = useState(false);

  // The File object does not survive a refresh, but the extracted CV text does.
  function getUploadableCV() {
    if (uploadedCV) {
      return uploadedCV;
    }
    if ((cvText || "").trim()) {
      return new File([cvText], cvFileName?.endsWith(".txt") ? cvFileName : "resume.txt", {
        type: "text/plain",
      });
    }
    return null;
  }

  const canRun = Boolean(uploadedCV || (cvText || "").trim());

  async function runSimulation() {
    const cvFile = getUploadableCV();
    if (!cvFile) {
      setError("No CV found. Go back and upload your CV.");
      return;
    }

    setRunning(true);
    setIsProcessing(true);
    setError("");
    setPremiumBlocked(false);

    try {
      const formData = new FormData();
      formData.append("file", cvFile);
      formData.append("job_description", jdText || "");
      const data = await simulateATS(formData);
      setResult(data);
      // Persist an exportable report and RESET (never merge) so a prior session's
      // outputs can't leak into this ATS export (same guarantee as the Bug 1 fix).
      setGeneratedResults({
        ATS_Report: { result_html: buildATSReportHtml(data), result_text: "" },
      });
    } catch (err) {
      // Premium-gate exactly like StepGenerate: a 402 shows an upgrade path.
      if (err?.status === 402) {
        setPremiumBlocked(true);
        trackCanvasEvent("canvas_error_shown", {
          flow: currentFlow || "atsCheck",
          step_name: "atsResults",
          error_type: "premium_required_402",
          message: "Premium access is required to run ATS Shield.",
        });
      } else {
        setError(err?.message || "ATS simulation failed.");
        trackCanvasEvent("canvas_error_shown", {
          flow: currentFlow || "atsCheck",
          step_name: "atsResults",
          error_type: "ats_simulation_failed",
          message: err?.message || "ATS simulation failed.",
        });
      }
    } finally {
      setRunning(false);
      setIsProcessing(false);
    }
  }

  // Auto-run once when we arrive with a CV + JD already provided.
  useEffect(() => {
    if (!result && !running && canRun) {
      runSimulation();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <StepWrapper
      title="ATS Shield Results"
      description="How well your CV passes automated screening for this role."
      onBack={onBack}
      maxWidth="100%"
    >
      <div className="stack">
        <div className="button-row" style={{ justifyContent: "flex-start" }}>
          <button
            type="button"
            className="primary-button"
            onClick={runSimulation}
            disabled={running || !canRun}
          >
            {running ? "Analyzing..." : result ? "Re-run ATS Simulation" : "Run ATS Simulation"}
          </button>
        </div>

        {running ? (
          <LoadingQuotes
            quotes={LOADING_QUOTES}
            note="This usually takes a few seconds. Please do not close the page."
          />
        ) : null}

        {premiumBlocked ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>ATS Shield requires Premium.</p>
            <button
              type="button"
              className="secondary-button compact-button"
              style={{ marginTop: "0.6rem" }}
              onClick={() => navigate("/payment")}
            >
              Upgrade to Premium
            </button>
          </div>
        ) : null}

        {error ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>{error}</p>
          </div>
        ) : null}

        {result ? <ATSResultsPanel result={result} /> : null}

        {result ? (
          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <button type="button" className="primary-button" onClick={onComplete}>
              Continue to Export
            </button>
          </div>
        ) : null}
      </div>
    </StepWrapper>
  );
}
