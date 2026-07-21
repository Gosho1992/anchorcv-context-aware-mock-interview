import { useMemo, useState } from "react";
import { postJson, postMultipart } from "../../../api/client";
import FileDropzone from "../../FileDropzone";
import StepWrapper from "../StepWrapper";
import useCanvasStore from "../../../store/useCanvasStore";
import { trackCanvasEvent } from "../../../utils/canvasAnalytics";

export default function StepPasteJD({ onComplete, onBack }) {
  const currentFlow = useCanvasStore((state) => state.currentFlow);
  const jdText = useCanvasStore((state) => state.jdText);
  const setJD = useCanvasStore((state) => state.setJD);

  const [jdFile, setJdFile] = useState(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [isFetchingUrl, setIsFetchingUrl] = useState(false);
  const [isExtractingFile, setIsExtractingFile] = useState(false);
  const [urlError, setUrlError] = useState("");
  const [fileError, setFileError] = useState("");

  const title = useMemo(
    () => (currentFlow === "scholarship" ? "Paste Scholarship Details" : "Paste Job Description"),
    [currentFlow]
  );

  async function handleFetchFromUrl() {
    setUrlError("");
    const trimmed = sourceUrl.trim();
    if (!trimmed) {
      return;
    }

    setIsFetchingUrl(true);
    try {
      const response = await postJson("/jobs/extract-from-url", { url: trimmed });
      const extracted = response?.job_description || response?.text || "";
      if (!extracted.trim()) {
        throw new Error("No content could be extracted from that URL.");
      }
      setJD(extracted);
    } catch {
      const message = "URL fetch failed. You can continue by pasting text manually below.";
      setUrlError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: currentFlow || "unknown",
        step_name: "paste",
        error_type: "url_fetch_failed",
        message,
      });
    } finally {
      setIsFetchingUrl(false);
    }
  }

  async function handleJdFile(nextFile) {
    setJdFile(nextFile);
    setFileError("");
    if (!nextFile) {
      return;
    }

    setIsExtractingFile(true);
    try {
      let extractedText = "";
      if (nextFile.name.toLowerCase().endsWith(".txt")) {
        extractedText = await nextFile.text();
      } else {
        const formData = new FormData();
        formData.append("file", nextFile);
        const response = await postMultipart("/discover/extract-resume", formData);
        extractedText = response?.resume_text || "";
      }

      if (!extractedText.trim()) {
        throw new Error("Could not read this file. Paste the details manually.");
      }
      setJD(extractedText);
    } catch (error) {
      const message = error?.message || "Could not process this file. Paste details manually.";
      setFileError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: currentFlow || "unknown",
        step_name: "paste",
        error_type: "requirements_file_extract_failed",
        message,
      });
    } finally {
      setIsExtractingFile(false);
    }
  }

  const hasValidInput = Boolean((jdText || "").trim());

  return (
    <StepWrapper
      title={title}
      description="Paste role requirements, scholarship details, or fetch from a URL."
      onBack={onBack}
    >
      <div className="stack">
        <div className="stack tight">
          <span className="eyebrow">Fetch from URL (optional)</span>
          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <input
              className="input-modern"
              placeholder="https://..."
              value={sourceUrl}
              onChange={(event) => setSourceUrl(event.target.value)}
              style={{ flex: 1, minWidth: "220px" }}
            />
            <button
              type="button"
              className="secondary-button"
              onClick={handleFetchFromUrl}
              disabled={isFetchingUrl || !sourceUrl.trim()}
            >
              {isFetchingUrl ? "Fetching..." : "Fetch from URL"}
            </button>
          </div>
          {urlError ? (
            <p className="muted-copy" style={{ margin: 0, color: "#f59e0b" }}>
              {urlError}
            </p>
          ) : null}
        </div>

        <FileDropzone
          label="Upload job description or scholarship details (optional)"
          file={jdFile}
          onChange={handleJdFile}
          accept=".pdf,.docx,.txt"
        />

        {isExtractingFile ? (
          <p className="muted-copy" style={{ margin: 0 }}>Extracting text from uploaded file...</p>
        ) : null}
        {fileError ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>{fileError}</p>
          </div>
        ) : null}

        <label className="stack tight">
          <span className="eyebrow">Requirements Text</span>
          <textarea
            className="input-modern"
            rows={11}
            value={jdText || ""}
            onChange={(event) => setJD(event.target.value)}
            placeholder="Paste the complete role or scholarship details here..."
          />
        </label>

        <div className="button-row" style={{ justifyContent: "flex-start" }}>
          <button
            type="button"
            className="primary-button"
            onClick={onComplete}
            disabled={!hasValidInput}
          >
            Continue
          </button>
        </div>
      </div>
    </StepWrapper>
  );
}
