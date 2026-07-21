import useCanvasStore from "../../store/useCanvasStore";

export default function StepWrapper({
  title,
  description,
  children,
  onBack,
  stepIndexOverride,
  maxWidth,
}) {
  const currentStep = useCanvasStore((state) => state.currentStep);
  const stepIndex = Number.isFinite(stepIndexOverride) ? stepIndexOverride : currentStep;
  const canGoBack = stepIndex > 0;

  return (
    <section key={`canvas-step-${stepIndex}`} className="stack page-enter">
      <div className="panel stack" style={{ maxWidth: maxWidth || "700px", margin: "0 auto", width: "100%" }}>
        <div className="stack tight">
          {canGoBack ? (
            <button
              type="button"
              className="secondary-button compact-button"
              onClick={onBack}
            >
              Back
            </button>
          ) : null}
          <p className="eyebrow">Canvas Step</p>
          <h2 className="page-title">{title}</h2>
          {description ? (
            <p className="muted-copy" style={{ margin: 0 }}>
              {description}
            </p>
          ) : null}
        </div>
        {children}
      </div>
    </section>
  );
}
