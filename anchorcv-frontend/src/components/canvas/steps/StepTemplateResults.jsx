import { useEffect, useState } from "react";
import { toast } from "sonner";
import TemplateResultPanel from "../../TemplateResultPanel";
import StepWrapper from "../StepWrapper";
import { postJson, postMultipart } from "../../../api/client";
import useCanvasStore from "../../../store/useCanvasStore";

function buildExportDocument(templateName, html) {
  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>${templateName}</title>
    <style>
      body { font-family: Arial, sans-serif; max-width: 860px; margin: 0 auto; padding: 2rem; color: #1a1a1a; line-height: 1.5; }
      h1, h2, h3 { color: #1e3a5f; }
      h2 { border-bottom: 1px solid #d1d5db; padding-bottom: 4px; }
    </style>
  </head>
  <body>${html}</body>
</html>`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function StepTemplateResults({ onComplete, onBack }) {
  const uploadedCV = useCanvasStore((state) => state.uploadedCV);
  const cvText = useCanvasStore((state) => state.cvText);
  const cvFileName = useCanvasStore((state) => state.cvFileName);
  const templateSelection = useCanvasStore((state) => state.templateSelection);
  const convertResult = useCanvasStore((state) => state.templateConvertResult);
  const compareResult = useCanvasStore((state) => state.templateCompareResult);
  const setTemplateConvertResult = useCanvasStore((state) => state.setTemplateConvertResult);
  const setTemplateCompareResult = useCanvasStore((state) => state.setTemplateCompareResult);
  const setGeneratedResults = useCanvasStore((state) => state.setGeneratedResults);

  const [exporting, setExporting] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function getUploadableCV() {
    if (uploadedCV) return uploadedCV;
    if ((cvText || "").trim()) {
      return new File([cvText], cvFileName?.endsWith(".txt") ? cvFileName : "resume.txt", {
        type: "text/plain",
      });
    }
    return null;
  }

  // Make the converted CV exportable through the shared Export step, RESET so a
  // prior session's outputs can't leak in (same guarantee as the Bug 1 fix).
  useEffect(() => {
    if (convertResult?.result_html) {
      setGeneratedResults({
        Template_CV: { result_html: convertResult.result_html, result_text: "" },
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [convertResult]);

  async function handleConvert() {
    const cvFile = getUploadableCV();
    if (!cvFile || !templateSelection?.templateId) return;
    setBusy(true);
    setError("");
    const formData = new FormData();
    formData.append("file", cvFile);
    formData.append("template_id", templateSelection.templateId);
    if (templateSelection.model) formData.append("model", templateSelection.model);
    if (templateSelection.targetRole) formData.append("target_role", templateSelection.targetRole);
    try {
      const result = await postMultipart("/templates/convert", formData);
      setTemplateConvertResult(result);
      setTemplateCompareResult(null);
    } catch (err) {
      setError(err?.message || "Conversion failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleExport(type) {
    if (!convertResult?.result_html) return;
    setExporting(type);
    try {
      const html = buildExportDocument(convertResult.template_name, convertResult.result_html);
      const filename = `anchorcv-${convertResult.template_id}.${type}`;
      const blob = await postJson(`/export/${type}`, { html, filename });
      downloadBlob(blob, filename);
      toast.success(`${type.toUpperCase()} downloaded.`);
    } catch (err) {
      setError(err?.message || `${type.toUpperCase()} export failed.`);
    } finally {
      setExporting("");
    }
  }

  const hasResult = Boolean(convertResult || compareResult);

  return (
    <StepWrapper
      title="Template results"
      description="Review your CV in the target format, or the fit score against its standards."
      onBack={onBack}
      maxWidth="100%"
    >
      <div className="stack">
        {!hasResult ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>No result yet. Go back and run Convert or Compare.</p>
          </div>
        ) : null}

        {error ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>{error}</p>
          </div>
        ) : null}

        <TemplateResultPanel
          compareResult={compareResult}
          convertResult={convertResult}
          onConvert={handleConvert}
          onExport={handleExport}
          exporting={exporting}
          busy={busy}
        />

        {convertResult ? (
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
