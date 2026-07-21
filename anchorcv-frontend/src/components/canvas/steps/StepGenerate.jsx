import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import LoadingQuotes from "../../LoadingQuotes";
import ModelSelect from "../../ModelSelect";
import StepWrapper from "../StepWrapper";
import { postMultipart } from "../../../api/client";
import useCanvasStore from "../../../store/useCanvasStore";
import { trackCanvasEvent } from "../../../utils/canvasAnalytics";

const LOADING_QUOTES = [
  "Analysing your CV against the role requirements...",
  "Identifying strengths, gaps, and opportunities...",
  "Calculating your fit score...",
  "Matching your experience to what recruiters look for...",
  "Building your personalised action plan...",
  "Great applications start with great analysis...",
  "Scanning for ATS keywords and formatting issues...",
  "Tailored for international job seekers and scholars...",
  "Almost there - your insights are being prepared...",
  "Your next opportunity is one good analysis away...",
];

function normalizeError(error) {
  return {
    status: error?.status || 500,
    message: error?.message || "Generation failed.",
  };
}

export default function StepGenerate({ onComplete, onBack }) {
  const navigate = useNavigate();
  const uploadedCV = useCanvasStore((state) => state.uploadedCV);
  const cvText = useCanvasStore((state) => state.cvText);
  const cvFileName = useCanvasStore((state) => state.cvFileName);
  const jdText = useCanvasStore((state) => state.jdText);
  const selectedOutputs = useCanvasStore((state) => state.selectedOutputs);
  const selectedModel = useCanvasStore((state) => state.selectedModel);
  const setSelectedModel = useCanvasStore((state) => state.setSelectedModel);
  const generatedResults = useCanvasStore((state) => state.generatedResults);
  const currentFlow = useCanvasStore((state) => state.currentFlow);
  const setGeneratedResults = useCanvasStore((state) => state.setGeneratedResults);
  const setIsProcessing = useCanvasStore((state) => state.setIsProcessing);

  const [running, setRunning] = useState(false);
  const [failures, setFailures] = useState([]);
  const [premiumBlocked, setPremiumBlocked] = useState(false);

  const outputsToShow = useMemo(
    () => selectedOutputs.map((output) => output.replaceAll("_", " ")),
    [selectedOutputs]
  );

  // The File object does not survive a page refresh, but the extracted CV
  // text does — rebuild an uploadable file from it when needed.
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

  const canGenerate = Boolean(uploadedCV || (cvText || "").trim());

  async function runSingle(outputType, cvFile) {
    if (outputType === "Job_Match_Score") {
      const formData = new FormData();
      formData.append("resume_file", cvFile);
      if ((jdText || "").trim()) {
        formData.append("requirement_text", jdText);
      }
      if (selectedModel) {
        formData.append("model", selectedModel);
      }
      return postMultipart("/match", formData);
    }

    const formData = new FormData();
    formData.append("file", cvFile);
    formData.append("requirement_text", jdText || "");
    formData.append("output_type", outputType);
    if (selectedModel) {
      formData.append("model", selectedModel);
    }
    return postMultipart("/analyse", formData);
  }

  async function runGeneration(targetOutputs, { reset = false } = {}) {
    const cvFile = getUploadableCV();
    if (!cvFile || targetOutputs.length === 0) {
      return;
    }

    setRunning(true);
    setIsProcessing(true);
    setPremiumBlocked(false);
    setFailures([]);

    // A fresh Generate run must never inherit results from a previous run or a
    // persisted prior session. Clear them up front so that even a total failure
    // cannot leave stale outputs rendered or exported. Retries pass reset=false
    // to preserve the current run's already-succeeded outputs.
    if (reset) {
      setGeneratedResults({});
    }
    const baseResults = reset ? {} : generatedResults;

    const successes = {};
    const failed = [];

    // Run all outputs in parallel — they are independent requests.
    const settled = await Promise.allSettled(
      targetOutputs.map((outputType) => runSingle(outputType, cvFile))
    );
    settled.forEach((outcome, index) => {
      const outputType = targetOutputs[index];
      if (outcome.status === "fulfilled") {
        successes[outputType] = outcome.value;
      } else {
        const normalized = normalizeError(outcome.reason);
        failed.push({ outputType, ...normalized });
      }
    });

    // Proactive Application Strategy: when the match (or ATS) score comes back
    // low, add a strategy output to THIS fresh (reset) run so it is included
    // cleanly alongside the selected outputs -- never merged in as a stale
    // leftover (reuses the reset:true fresh-run path from the Bug 1 fix).
    const STRATEGY_KEY = "Application_Strategy";
    const alreadyHasStrategy =
      targetOutputs.includes(STRATEGY_KEY) || STRATEGY_KEY in successes;
    if (!alreadyHasStrategy) {
      const matchResult = successes["Job_Match_Score"];
      const matchScore =
        matchResult && typeof matchResult.overall_score === "number"
          ? matchResult.overall_score
          : null;
      const atsResult = successes["ATS_Optimization"];
      const atsScore =
        atsResult && typeof atsResult.score === "number"
          ? atsResult.score
          : atsResult && typeof atsResult.ats_score === "number"
          ? atsResult.ats_score
          : null;
      const lowMatch = matchScore != null && matchScore < 50;
      const lowAts = atsScore != null && atsScore < 60;
      if (lowMatch || lowAts) {
        try {
          successes[STRATEGY_KEY] = await runSingle(STRATEGY_KEY, cvFile);
          trackCanvasEvent("canvas_output_generated", {
            flow: currentFlow || "unknown",
            step_name: "generate",
            output_type: STRATEGY_KEY,
            auto_added: true,
            trigger: lowMatch ? "low_match_score" : "low_ats_score",
          });
        } catch {
          // If the strategy add-on fails, keep the primary outputs intact.
        }
      }
    }

    if (Object.keys(successes).length > 0) {
      setGeneratedResults({
        ...baseResults,
        ...successes,
      });
    }

    const has402 = failed.some((item) => item.status === 402);
    if (has402) {
      setPremiumBlocked(true);
      trackCanvasEvent("canvas_error_shown", {
        flow: currentFlow || "unknown",
        step_name: "generate",
        error_type: "premium_required_402",
        message: "Premium access is required for one or more selected outputs.",
      });
    }

    if (failed.length > 0) {
      trackCanvasEvent("canvas_error_shown", {
        flow: currentFlow || "unknown",
        step_name: "generate",
        error_type: has402 ? "partial_failure_with_premium_block" : "partial_generation_failure",
        failed_outputs: failed.map((item) => item.outputType),
      });
    }

    setFailures(failed);
    setRunning(false);
    setIsProcessing(false);

    if (Object.keys(successes).length > 0) {
      onComplete?.();
    }
  }

  return (
    <StepWrapper
      title="Generate Outputs"
      description="Run selected outputs and continue once at least one result is ready."
      onBack={onBack}
    >
      <div className="stack">
        <div className="analysis-meta-card">
          <p style={{ margin: 0 }}>
            Selected: <strong>{outputsToShow.join(", ") || "None"}</strong>
          </p>
        </div>

        <ModelSelect value={selectedModel} onChange={setSelectedModel} disabled={running} />

        <div className="button-row" style={{ justifyContent: "flex-start" }}>
          <button
            type="button"
            className="primary-button"
            onClick={() => runGeneration(selectedOutputs, { reset: true })}
            disabled={running || !canGenerate || selectedOutputs.length === 0}
          >
            {running ? "Generating..." : "Generate"}
          </button>
        </div>

        {running ? (
          <LoadingQuotes
            quotes={LOADING_QUOTES}
            note="This usually takes 10-20 seconds. Please do not close the page."
          />
        ) : null}

        {premiumBlocked ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>
              Premium access is required for one or more selected outputs.
            </p>
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

        {failures.length > 0 ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>
              Some outputs failed. Successful outputs were kept.
            </p>
            <ul style={{ margin: "0.6rem 0 0", paddingLeft: "1rem" }}>
              {failures.map((item) => (
                <li key={item.outputType}>
                  {item.outputType.replaceAll("_", " ")}: {item.message}
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="secondary-button compact-button"
              style={{ marginTop: "0.7rem" }}
              onClick={() => runGeneration(failures.map((item) => item.outputType), { reset: false })}
            >
              Retry Failed Outputs
            </button>
          </div>
        ) : null}
      </div>
    </StepWrapper>
  );
}
