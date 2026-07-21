import DiscoveryLandscape from "../../DiscoveryLandscape";
import StepWrapper from "../StepWrapper";
import useCanvasStore from "../../../store/useCanvasStore";

function inferFlowFromOpportunity(opp) {
  const blob = JSON.stringify(opp || {}).toLowerCase();
  if (blob.includes("scholarship") || blob.includes("fellowship")) {
    return "scholarship";
  }
  return "job";
}

export default function StepDiscoveryLandscape({ onBack, onSwitchFlow, onFinish }) {
  const discoveryData = useCanvasStore((state) => state.discoveryData);
  const setJD = useCanvasStore((state) => state.setJD);

  function handleAnalyzeOpportunity(opp) {
    const requirement = [
      opp?.title,
      `${opp?.institution || ""}, ${opp?.country || ""}`,
      opp?.type ? `Type: ${opp.type}` : "",
      opp?.note,
    ]
      .filter(Boolean)
      .join("\n");

    setJD(requirement);
    onSwitchFlow?.(inferFlowFromOpportunity(opp));
  }

  return (
    <StepWrapper
      title="Discovery Landscape"
      description="Review opportunities and jump directly into CV analysis for a selected target."
      onBack={onBack}
      maxWidth="100%"
    >
      {discoveryData ? (
        <div className="stack">
          <DiscoveryLandscape
            displayedLandscape={discoveryData}
            isSample={Boolean(discoveryData?.__sample)}
            loading={false}
            onRegenerate={() => {}}
            onAnalyzeOpportunity={handleAnalyzeOpportunity}
            onUseSearchTag={(tag) => {
              window.open(`https://www.google.com/search?q=${encodeURIComponent(tag)}`, "_blank", "noopener,noreferrer");
            }}
            onCopyAllTags={() => {
              if (Array.isArray(discoveryData?.search_tags) && discoveryData.search_tags.length) {
                navigator.clipboard.writeText(discoveryData.search_tags.join("\n"));
              }
            }}
          />
          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <button type="button" className="primary-button" onClick={onFinish}>
              Finish
            </button>
          </div>
        </div>
      ) : (
        <div className="analysis-meta-card warn">
          <p style={{ margin: 0 }}>No landscape data available yet.</p>
        </div>
      )}
    </StepWrapper>
  );
}
