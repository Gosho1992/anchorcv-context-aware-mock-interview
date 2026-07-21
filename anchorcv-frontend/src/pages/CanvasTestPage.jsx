import { useState } from "react";
import OutputTypeCards from "../components/OutputTypeCards";

export default function CanvasTestPage() {
  const [selectedOutputs, setSelectedOutputs] = useState([
    "Cover_Letter",
    "Job_Match_Score",
  ]);

  function handleToggle(outputType) {
    setSelectedOutputs((current) =>
      current.includes(outputType)
        ? current.filter((value) => value !== outputType)
        : [...current, outputType]
    );
  }

  return (
    <section className="stack page-enter">
      <div className="panel stack">
        <div>
          <p className="eyebrow">Canvas Test</p>
          <h2 className="page-title">OutputTypeCards Reuse Check</h2>
          <p className="muted-copy" style={{ margin: 0 }}>
            This temporary route validates that output cards work outside
            AnalysisPage.
          </p>
        </div>
        <OutputTypeCards selectedOutputs={selectedOutputs} onToggle={handleToggle} />
      </div>
    </section>
  );
}
