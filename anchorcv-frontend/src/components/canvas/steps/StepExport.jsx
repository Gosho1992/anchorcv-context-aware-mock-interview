import { useMemo, useState } from "react";
import { toast } from "sonner";
import { postJson, uploadFile } from "../../../api/client";
import StepWrapper from "../StepWrapper";
import useCanvasStore from "../../../store/useCanvasStore";
import { trackCanvasEvent } from "../../../utils/canvasAnalytics";
import {
  openGmailCompose,
  buildApplicationSubject,
  htmlToPlainText,
  firstNonEmptyLine,
} from "../../../utils/gmail";

function buildTimestamp() {
  return new Date().toISOString().replaceAll(":", "-");
}

function buildFilename(extension) {
  return `anchorcv-canvas-${buildTimestamp()}${extension}`;
}

function buildCanvasDocument(results) {
  const sections = Object.entries(results || {}).map(([outputType, result]) => {
    const title = String(outputType).replaceAll("_", " ");
    const html = result?.result_html || `<pre>${result?.result_text || ""}</pre>`;
    return `<section style="margin-bottom:28px"><h2>${title}</h2>${html}</section>`;
  });

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>AnchorCV Canvas Export</title>
    <style>
      body { font-family: Arial, sans-serif; max-width: 860px; margin: 0 auto; padding: 2rem; color: #1a1a1a; }
      h1 { color: #1e3a5f; margin-bottom: 1.2rem; }
      h2 { color: #1e3a5f; margin: 0 0 0.8rem; }
    </style>
  </head>
  <body>
    <h1>AnchorCV Canvas Results</h1>
    ${sections.join("")}
  </body>
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

export default function StepExport({ onBack, onRestart }) {
  const currentFlow = useCanvasStore((state) => state.currentFlow);
  const generatedResults = useCanvasStore((state) => state.generatedResults);
  const jdText = useCanvasStore((state) => state.jdText);
  const cvText = useCanvasStore((state) => state.cvText);

  const [pendingAction, setPendingAction] = useState("");
  const [error, setError] = useState("");

  const html = useMemo(() => buildCanvasDocument(generatedResults), [generatedResults]);
  const hasResults = Object.keys(generatedResults || {}).length > 0;

  async function handlePdf() {
    setPendingAction("pdf");
    setError("");
    try {
      const blob = await postJson("/export/pdf", {
        html,
        filename: buildFilename(".pdf"),
      });
      downloadBlob(blob, buildFilename(".pdf"));
      toast.success("PDF downloaded.");
    } catch (err) {
      const message = err?.message || "PDF export failed.";
      setError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: currentFlow || "unknown",
        step_name: "export",
        error_type: "pdf_export_failed",
        message,
      });
    } finally {
      setPendingAction("");
    }
  }

  async function handleDocx() {
    setPendingAction("docx");
    setError("");
    try {
      const blob = await postJson("/export/docx", {
        html,
        filename: buildFilename(".docx"),
      });
      downloadBlob(blob, buildFilename(".docx"));
      toast.success("DOCX downloaded.");
    } catch (err) {
      const message = err?.message || "DOCX export failed.";
      setError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: currentFlow || "unknown",
        step_name: "export",
        error_type: "docx_export_failed",
        message,
      });
    } finally {
      setPendingAction("");
    }
  }

  async function handleSaveToCloud() {
    setPendingAction("cloud");
    setError("");
    try {
      const pdfBlob = await postJson("/export/pdf", {
        html,
        filename: buildFilename(".pdf"),
      });
      const formData = new FormData();
      formData.append("file", new File([pdfBlob], buildFilename(".pdf"), { type: "application/pdf" }));
      await uploadFile(formData);
      toast.success("Saved to cloud.");
    } catch (err) {
      const message = err?.message || "Cloud save failed.";
      setError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: currentFlow || "unknown",
        step_name: "export",
        error_type: "cloud_save_failed",
        message,
      });
    } finally {
      setPendingAction("");
    }
  }

  function handleGmail() {
    // Prefer the cover letter as the email body; fall back to any output.
    const cover = generatedResults?.Cover_Letter;
    const source = cover || Object.values(generatedResults || {})[0] || null;
    const body = source
      ? source.result_text || htmlToPlainText(source.result_html)
      : "";
    openGmailCompose({
      subject: buildApplicationSubject(
        firstNonEmptyLine(jdText),
        firstNonEmptyLine(cvText)
      ),
      body,
    });
  }

  function handleStartOver() {
    if (onRestart) {
      onRestart();
      return;
    }
  }

  return (
    <StepWrapper
      title="Export Results"
      description="Download PDF/DOCX or save to cloud. Failures are retryable and results are preserved."
      onBack={onBack}
    >
      <div className="stack">
        <div className="button-row" style={{ justifyContent: "flex-start" }}>
          <button
            type="button"
            className="secondary-button"
            onClick={handlePdf}
            disabled={!hasResults || pendingAction === "pdf"}
          >
            {pendingAction === "pdf" ? "Preparing PDF..." : "Download PDF"}
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={handleDocx}
            disabled={!hasResults || pendingAction === "docx"}
          >
            {pendingAction === "docx" ? "Preparing DOCX..." : "Download DOCX"}
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={handleSaveToCloud}
            disabled={!hasResults || pendingAction === "cloud"}
          >
            {pendingAction === "cloud" ? "Saving..." : "Save to Cloud"}
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={handleGmail}
            disabled={!hasResults}
          >
            Send via Gmail
          </button>
        </div>

        {error ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>{error}</p>
            <p className="muted-copy" style={{ margin: "0.4rem 0 0" }}>
              Retry the failed export action. Generated results are still available.
            </p>
          </div>
        ) : null}

        <div className="button-row" style={{ justifyContent: "flex-start" }}>
          <button type="button" className="primary-button" onClick={handleStartOver}>
            Finish
          </button>
          <button type="button" className="primary-button" onClick={handleStartOver}>
            Start Over
          </button>
        </div>
      </div>
    </StepWrapper>
  );
}
