import { useEffect, useMemo, useState } from "react";
import TemplateGallery, { TemplateDetail } from "../../TemplateGallery";
import LoadingQuotes from "../../LoadingQuotes";
import ModelSelect from "../../ModelSelect";
import StepWrapper from "../StepWrapper";
import { getJson, postMultipart } from "../../../api/client";
import useCanvasStore from "../../../store/useCanvasStore";

const LOADING_QUOTES = [
  "Studying the target format's standards...",
  "Restructuring your experience to fit...",
  "The best CVs speak the reviewer's language...",
  "Checking section order and conventions...",
  "Almost there - polishing the structure...",
];

export default function StepTemplateSelect({ onComplete, onBack }) {
  const uploadedCV = useCanvasStore((state) => state.uploadedCV);
  const cvText = useCanvasStore((state) => state.cvText);
  const cvFileName = useCanvasStore((state) => state.cvFileName);
  const setTemplateSelection = useCanvasStore((state) => state.setTemplateSelection);
  const setTemplateConvertResult = useCanvasStore((state) => state.setTemplateConvertResult);
  const setTemplateCompareResult = useCanvasStore((state) => state.setTemplateCompareResult);

  const [templates, setTemplates] = useState([]);
  const [loadError, setLoadError] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [model, setModel] = useState("");
  const [action, setAction] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let isActive = true;
    getJson("/templates")
      .then((response) => {
        if (isActive && Array.isArray(response?.templates)) {
          setTemplates(response.templates);
        }
      })
      .catch(() => {
        if (isActive) setLoadError("Could not load templates. Refresh to retry.");
      });
    return () => {
      isActive = false;
    };
  }, []);

  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === selectedId) || null,
    [templates, selectedId]
  );

  const busy = action === "convert" || action === "compare";
  const canRun = Boolean(uploadedCV || (cvText || "").trim());

  function getUploadableCV() {
    if (uploadedCV) return uploadedCV;
    if ((cvText || "").trim()) {
      return new File([cvText], cvFileName?.endsWith(".txt") ? cvFileName : "resume.txt", {
        type: "text/plain",
      });
    }
    return null;
  }

  function selectTemplate(id) {
    setSelectedId(id);
    setError("");
  }

  async function runAction(kind) {
    const cvFile = getUploadableCV();
    if (!cvFile || !selectedTemplate) return;
    setAction(kind);
    setError("");

    const formData = new FormData();
    formData.append("file", cvFile);
    formData.append("template_id", selectedTemplate.id);
    if (model) formData.append("model", model);

    try {
      const selection = {
        templateId: selectedTemplate.id,
        templateName: selectedTemplate.name,
        targetRole: targetRole.trim(),
        model,
      };
      if (kind === "convert") {
        if (targetRole.trim()) formData.append("target_role", targetRole.trim());
        const result = await postMultipart("/templates/convert", formData);
        setTemplateSelection(selection);
        setTemplateConvertResult(result);
        setTemplateCompareResult(null);
      } else {
        const result = await postMultipart("/templates/compare", formData);
        setTemplateSelection(selection);
        setTemplateCompareResult(result);
        setTemplateConvertResult(null);
      }
      onComplete?.();
    } catch (err) {
      setError(err?.message || "Something went wrong. Please try again.");
    } finally {
      setAction("");
    }
  }

  return (
    <StepWrapper
      title="World-class CV templates"
      description="Convert your CV into the format a top institution expects, or score it against their standards."
      onBack={onBack}
      maxWidth="100%"
    >
      <div className="stack">
        {loadError ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>{loadError}</p>
          </div>
        ) : null}

        <TemplateGallery templates={templates} selectedId={selectedId} onSelect={selectTemplate} />

        {selectedTemplate ? (
          <div className="panel stack">
            <TemplateDetail template={selectedTemplate} />

            {!canRun ? (
              <div className="analysis-meta-card warn">
                <p style={{ margin: 0 }}>No CV found. Go back and upload your CV first.</p>
              </div>
            ) : null}

            <div className="button-row" style={{ justifyContent: "flex-start", alignItems: "flex-end", flexWrap: "wrap" }}>
              <label className="stack tight" style={{ flex: 1, minWidth: "220px" }}>
                <span className="eyebrow">Target role / position (optional)</span>
                <input
                  className="input-modern"
                  placeholder="e.g. Senior Public Sector Specialist"
                  value={targetRole}
                  onChange={(event) => setTargetRole(event.target.value)}
                />
              </label>
              <ModelSelect value={model} onChange={setModel} disabled={busy} compact />
            </div>

            <div className="button-row" style={{ justifyContent: "flex-start" }}>
              <button
                type="button"
                className="primary-button"
                onClick={() => runAction("convert")}
                disabled={!canRun || busy}
              >
                {action === "convert" ? "Converting..." : `Convert to ${selectedTemplate.name}`}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => runAction("compare")}
                disabled={!canRun || busy}
              >
                {action === "compare" ? "Scoring..." : "Compare & Score My CV"}
              </button>
            </div>

            {busy ? (
              <LoadingQuotes quotes={LOADING_QUOTES} note="This usually takes 10-25 seconds." />
            ) : null}

            {error ? (
              <div className="analysis-meta-card warn">
                <p style={{ margin: 0 }}>{error}</p>
              </div>
            ) : null}
          </div>
        ) : templates.length > 0 ? (
          <div className="analysis-meta-card">
            <p style={{ margin: 0 }} className="muted-copy">
              Select a template above to see its structure, expectations, and to convert or score your CV.
            </p>
          </div>
        ) : null}
      </div>
    </StepWrapper>
  );
}
