import FirstResumePage from "../../../pages/FirstResumePage";
import StepWrapper from "../StepWrapper";

export default function StepBuildCV({ onBack, onComplete }) {
  return (
    <StepWrapper
      title="Build CV"
      description="Use the full First Resume workspace, then continue when ready."
      onBack={onBack}
      maxWidth="100%"
    >
      <div className="stack">
        <FirstResumePage />
        <div className="button-row" style={{ justifyContent: "flex-start" }}>
          <button type="button" className="primary-button" onClick={onComplete}>
            Continue
          </button>
        </div>
      </div>
    </StepWrapper>
  );
}
