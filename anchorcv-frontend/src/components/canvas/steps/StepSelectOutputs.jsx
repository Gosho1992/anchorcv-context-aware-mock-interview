import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import OutputTypeCards from "../../OutputTypeCards";
import StepWrapper from "../StepWrapper";
import useAuthStore from "../../../store/useAuthStore";
import useCanvasStore from "../../../store/useCanvasStore";
import { hasActivePremium } from "../../../utils/premium";
import { trackCanvasEvent } from "../../../utils/canvasAnalytics";

const PREMIUM_ONLY_OUTPUTS = [
  "Application_Strategy",
  "ATS_Optimization",
  "Resume_Optimization",
  "Email_Template",
];

const FLOW_DEFAULTS = {
  job: ["Cover_Letter", "Job_Match_Score"],
  scholarship: ["Cover_Letter", "Job_Match_Score"],
  improveResume: ["Resume_Optimization"],
};

export default function StepSelectOutputs({ onComplete, onBack }) {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const accessStatus = useAuthStore((state) => state.accessStatus);
  const currentFlow = useCanvasStore((state) => state.currentFlow);
  const selectedOutputs = useCanvasStore((state) => state.selectedOutputs);
  const toggleOutput = useCanvasStore((state) => state.toggleOutput);
  const setSelectedOutputs = useCanvasStore((state) => state.setSelectedOutputs);

  const [upgradeHint, setUpgradeHint] = useState("");

  const isPremium = useMemo(
    () => accessStatus?.access === "premium" || hasActivePremium(user),
    [accessStatus?.access, user]
  );

  const lockedOutputs = isPremium ? [] : PREMIUM_ONLY_OUTPUTS;

  useEffect(() => {
    if (selectedOutputs.length > 0) {
      return;
    }
    const defaults = FLOW_DEFAULTS[currentFlow] || FLOW_DEFAULTS.job;
    const unlocked = defaults.filter((output) => !lockedOutputs.includes(output));
    // Never leave a free user with an empty default selection when the
    // flow's preferred outputs are premium-locked.
    setSelectedOutputs(unlocked.length > 0 ? unlocked : ["Job_Match_Score"]);
  }, [currentFlow, selectedOutputs.length, setSelectedOutputs, lockedOutputs]);

  function handleToggle(outputType) {
    setUpgradeHint("");
    toggleOutput(outputType);
  }

  function handleAttemptLocked() {
    const message = "This output requires Premium. Upgrade to unlock it.";
    setUpgradeHint(message);
    trackCanvasEvent("canvas_error_shown", {
      flow: currentFlow || "unknown",
      step_name: "outputs",
      error_type: "premium_output_locked",
      message,
    });
  }

  return (
    <StepWrapper
      title="Select Outputs"
      description="Choose what AnchorCV should generate for this target."
      onBack={onBack}
    >
      <div className="stack">
        {currentFlow === "scholarship" ? (
          <div className="analysis-meta-card teal">
            <p style={{ margin: 0 }}>
              Scholarship flow uses <strong>Cover Letter</strong> internally for your statement-style output.
            </p>
          </div>
        ) : null}

        <OutputTypeCards
          selectedOutputs={selectedOutputs}
          onToggle={handleToggle}
          lockedOutputs={lockedOutputs}
          onAttemptLocked={handleAttemptLocked}
        />

        {upgradeHint ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>{upgradeHint}</p>
            <button
              type="button"
              className="secondary-button compact-button"
              onClick={() => navigate("/payment")}
              style={{ marginTop: "0.6rem" }}
            >
              Upgrade to Premium
            </button>
          </div>
        ) : null}

        <div className="button-row" style={{ justifyContent: "flex-start" }}>
          <button
            type="button"
            className="primary-button"
            disabled={selectedOutputs.length === 0}
            onClick={onComplete}
          >
            Continue
          </button>
        </div>
      </div>
    </StepWrapper>
  );
}
