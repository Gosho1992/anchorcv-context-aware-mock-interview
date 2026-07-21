import { useState } from "react";
import { postMultipart } from "../../../api/client";
import FileDropzone from "../../FileDropzone";
import StepWrapper from "../StepWrapper";
import useCanvasStore from "../../../store/useCanvasStore";
import { trackCanvasEvent } from "../../../utils/canvasAnalytics";

export default function StepUploadCV({ onComplete, onBack, standalone = false }) {
  const uploadedCV = useCanvasStore((state) => state.uploadedCV);
  const cvFileName = useCanvasStore((state) => state.cvFileName);
  const cvText = useCanvasStore((state) => state.cvText);
  const currentFlow = useCanvasStore((state) => state.currentFlow);
  const setUploadedCV = useCanvasStore((state) => state.setUploadedCV);

  const [isExtracting, setIsExtracting] = useState(false);
  const [extractError, setExtractError] = useState("");
  const [replacing, setReplacing] = useState(false);

  const hasCV = Boolean(uploadedCV || (cvText || "").trim());
  const displayName = uploadedCV?.name || cvFileName || "extracted CV text";
  const showDropzone = !hasCV || replacing;

  async function handleFileChange(file) {
    setExtractError("");
    if (!file) {
      return;
    }

    setIsExtracting(true);
    try {
      let extractedText = "";
      if (file.name.toLowerCase().endsWith(".txt")) {
        extractedText = await file.text();
      } else {
        const formData = new FormData();
        formData.append("file", file);
        const response = await postMultipart("/discover/extract-resume", formData);
        extractedText = response?.resume_text || "";
      }

      if (!extractedText.trim()) {
        throw new Error("We could not extract text from this file. Try another CV format.");
      }

      setUploadedCV(file, extractedText);
      setReplacing(false);
      setTimeout(() => {
        onComplete?.();
      }, 250);
    } catch (error) {
      const message = error?.message || "CV extraction failed. Please retry with another file.";
      setExtractError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: currentFlow || "unknown",
        step_name: "upload",
        error_type: "cv_extraction_failed",
        message,
      });
    } finally {
      setIsExtracting(false);
    }
  }

  const title = standalone
    ? "Replace Your CV"
    : hasCV
      ? "Your CV"
      : "Upload Your CV";
  const description = hasCV
    ? "This CV is used across all flows. Replace it or continue."
    : "We will extract your CV text and carry it through the flow.";

  return (
    <StepWrapper
      title={title}
      description={description}
      onBack={onBack}
      stepIndexOverride={standalone ? 1 : undefined}
    >
      <div className="stack">
        {hasCV && !replacing ? (
          <div className="analysis-meta-card" style={{ borderColor: "rgba(34,197,94,0.35)" }}>
            <p style={{ margin: 0 }}>
              <span aria-hidden="true" style={{ color: "#22c55e", marginRight: "0.4rem" }}>
                ✓
              </span>
              CV ready: <strong>{displayName}</strong>
            </p>
            <div className="button-row" style={{ justifyContent: "flex-start", marginTop: "0.8rem" }}>
              <button
                type="button"
                className="secondary-button compact-button"
                onClick={() => {
                  setExtractError("");
                  setReplacing(true);
                }}
              >
                Replace
              </button>
              <button
                type="button"
                className="primary-button compact-button"
                onClick={() => onComplete?.()}
              >
                {standalone ? "Done" : "Continue"}
              </button>
            </div>
          </div>
        ) : null}

        {showDropzone ? (
          <>
            <FileDropzone
              label={hasCV ? "Upload a new CV to replace the current one" : "Upload your CV"}
              file={replacing ? null : uploadedCV}
              onChange={handleFileChange}
            />
            {hasCV && replacing ? (
              <div className="button-row" style={{ justifyContent: "flex-start" }}>
                <button
                  type="button"
                  className="secondary-button compact-button"
                  onClick={() => {
                    setExtractError("");
                    setReplacing(false);
                  }}
                >
                  Cancel — keep {displayName}
                </button>
              </div>
            ) : null}
          </>
        ) : null}

        {isExtracting ? (
          <p className="muted-copy" style={{ margin: 0 }}>Extracting CV text...</p>
        ) : null}

        {extractError ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>{extractError}</p>
            <button
              type="button"
              className="secondary-button compact-button"
              onClick={() => setExtractError("")}
              style={{ marginTop: "0.6rem" }}
            >
              Retry
            </button>
          </div>
        ) : null}
      </div>
    </StepWrapper>
  );
}
