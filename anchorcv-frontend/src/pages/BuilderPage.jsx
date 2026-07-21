import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { postJson, postMultipart, uploadFile } from "../api/client";
import FileDropzone from "../components/FileDropzone";
import FormatCard from "../components/FormatCard";
import LoadingQuotes from "../components/LoadingQuotes";
import useAuthStore from "../store/useAuthStore";
import useCvWorkspaceStore from "../store/useCvWorkspaceStore";

const LOADING_QUOTES = [
  "Tailoring your CV to stand out from the crowd...",
  "Analysing your experience and matching it to the role...",
  "Crafting every bullet point with purpose...",
  "Great CVs open doors - yours is almost ready...",
  "Optimising for ATS systems and human readers...",
  "The best time to apply was yesterday. The second best time is now.",
  "Turning your experience into a compelling story...",
  "Built for job seekers who refuse to settle...",
  "Adding the right keywords to get past the filters...",
  "Your next opportunity is one great CV away...",
];

const FORMATS = [
  {
    value: "ATS-Optimized CV",
    label: "ATS-Optimized CV",
    badge: "ATS",
    description: "Keyword-rich layout tuned for applicant tracking systems.",
  },
  {
    value: "Europass CV",
    label: "Europass CV",
    badge: "EU",
    description: "Structured EU-style format for academic and employer submissions.",
  },
  {
    value: "Academic CV",
    label: "Academic CV",
    badge: "Academic",
    description: "Research-first structure for higher education applications.",
  },
  {
    value: "One-page CV",
    label: "One-page CV",
    badge: "Compact",
    description: "Compressed format for fast, concise applications.",
  },
];

const COLOR_SWATCHES = [
  "#6366f1",
  "#14b8a6",
  "#f59e0b",
  "#22c55e",
  "#ef4444",
  "#8b5cf6",
];

const SAMPLE_CV_TEXT = `Aisha Rahman
Berlin, Germany
aisha.rahman@example.com

Summary
Electrical engineering graduate focused on smart grids, renewable energy systems, and power system modelling.

Experience
Research Assistant, Sustainable Power Lab
- Built a MATLAB simulation for load balancing across three renewable microgrid scenarios.
- Coordinated data collection for a funded smart-meter pilot involving 120 households.

Projects
- Designed a solar forecasting dashboard using Python and time-series analysis.
- Led a four-person capstone team on grid fault detection and reporting.

Education
MSc Electrical Engineering

Skills
Python, MATLAB, Power Systems, Data Analysis, Technical Writing
`;

function buildTimestamp() {
  return new Date().toISOString().replaceAll(":", "-");
}

function buildBuilderFilename(extension) {
  return `anchorcv-cv-${buildTimestamp()}${extension}`;
}

function buildTargetPayload(target, guidanceText, specialInstructions) {
  const sections = [];

  if (target.trim()) {
    sections.push(`Primary target role or program: ${target.trim()}`);
  }

  if (guidanceText.trim()) {
    sections.push(`Job description / requirements:\n${guidanceText.trim()}`);
  }

  if (specialInstructions && specialInstructions.trim()) {
    sections.push(`Special instructions from the user:\n${specialInstructions.trim()}`);
  }

  return sections.join("\n\n");
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function readExportError(response) {
  try {
    const body = await response.json();
    return body?.detail || body?.error || `PDF export failed (${response.status}).`;
  } catch {
    const text = await response.text().catch(() => "");
    return text || `PDF export failed (${response.status}).`;
  }
}

async function readPdfBytes(response) {
  if (!response.ok) {
    throw new Error(await readExportError(response));
  }

  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const header = new TextDecoder("ascii").decode(bytes.slice(0, 5));
  if (bytes.length < 500 || header !== "%PDF-") {
    throw new Error("PDF export returned an empty or invalid PDF file.");
  }
  return bytes;
}

export default function BuilderPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const hydrateAuth = useAuthStore((state) => state.hydrate);
  const accessStatus = useAuthStore((state) => state.accessStatus);
  const isBlocked = accessStatus?.access === "blocked";

  const file = useCvWorkspaceStore((state) => state.uploadedResumeFile);
  const setUploadedResumeFile = useCvWorkspaceStore(
    (state) => state.setUploadedResumeFile
  );
  const clearUploadedResume = useCvWorkspaceStore(
    (state) => state.clearUploadedResume
  );
  const selectedFormat = useCvWorkspaceStore(
    (state) => state.builderSelectedFormat
  );
  const setSelectedFormat = useCvWorkspaceStore(
    (state) => state.setBuilderSelectedFormat
  );
  const target = useCvWorkspaceStore((state) => state.builderTarget);
  const setTarget = useCvWorkspaceStore((state) => state.setBuilderTarget);
  const guidanceText = useCvWorkspaceStore((state) => state.builderGuidanceText);
  const setGuidanceText = useCvWorkspaceStore(
    (state) => state.setBuilderGuidanceText
  );
  const tone = useCvWorkspaceStore((state) => state.builderTone);
  const setTone = useCvWorkspaceStore((state) => state.setBuilderTone);
  const language = useCvWorkspaceStore((state) => state.builderLanguage);
  const setLanguage = useCvWorkspaceStore((state) => state.setBuilderLanguage);
  const length = useCvWorkspaceStore((state) => state.builderLength);
  const setLength = useCvWorkspaceStore((state) => state.setBuilderLength);
  const colorTheme = useCvWorkspaceStore((state) => state.builderColorTheme);
  const setColorTheme = useCvWorkspaceStore(
    (state) => state.setBuilderColorTheme
  );
  const enhance = useCvWorkspaceStore((state) => state.builderEnhance);
  const setEnhance = useCvWorkspaceStore((state) => state.setBuilderEnhance);
  const sections = useCvWorkspaceStore((state) => state.builderSections);
  const setSections = useCvWorkspaceStore((state) => state.setBuilderSections);
  const specialInstructions = useCvWorkspaceStore((state) => state.builderSpecialInstructions);
  const setSpecialInstructions = useCvWorkspaceStore((state) => state.setBuilderSpecialInstructions);
  const result = useCvWorkspaceStore((state) => state.builderResult);
  const setResult = useCvWorkspaceStore((state) => state.setBuilderResult);
  const clearBuilder = useCvWorkspaceStore((state) => state.clearBuilder);
  const cvRequirementPrefill = useCvWorkspaceStore(
    (state) => state.cvRequirementPrefill
  );
  const clearCvRequirementPrefill = useCvWorkspaceStore(
    (state) => state.clearCvRequirementPrefill
  );

  useEffect(() => {
    document.title = "Builder - AnchorCV";
    if (!guidanceText.trim() && cvRequirementPrefill.trim()) {
      setGuidanceText(cvRequirementPrefill);
    }
  }, [cvRequirementPrefill, guidanceText, setGuidanceText]);

  const buildMutation = useMutation({
    mutationFn: async (overrideFile) => {
      const sourceFile = overrideFile || file;
      const formData = new FormData();
      formData.append("file", sourceFile);
      formData.append("target", buildTargetPayload(target, guidanceText, specialInstructions));
      formData.append("format", selectedFormat);
      formData.append("tone", tone);
      formData.append("language", language);
      formData.append("length", length);
      formData.append("color_theme", colorTheme);
      formData.append("sections", JSON.stringify(sections));
      formData.append("enhance", String(enhance));
      return postMultipart("/build-cv", formData);
    },
    onSuccess: (data) => {
      setResult(data);
      toast.success("CV generated.");
    },
    onError: (error) => {
      toast.error(error.message || "Unable to build CV.");
    },
  });

  const docxMutation = useMutation({
    mutationFn: () =>
      postJson("/export/docx", {
        html: result.html,
        cv_data: result.cv_data,
        filename: buildBuilderFilename(".docx"),
      }),
    onSuccess: (blob) => downloadBlob(blob, buildBuilderFilename(".docx")),
    onError: (error) => {
      toast.error(error.message || "Unable to export DOCX.");
    },
  });

  const pdfMutation = useMutation({
    mutationFn: () =>
      postJson("/export/pdf", {
        html: result.html,
        filename: buildBuilderFilename(".pdf"),
      }),
    onSuccess: (blob) => downloadBlob(blob, buildBuilderFilename(".pdf")),
    onError: (error) => {
      toast.error(error.message || "Unable to export PDF.");
    },
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const pdfResponse = await fetch("/api/export/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          html: result.html,
          filename: buildBuilderFilename(".pdf"),
        }),
        credentials: "include",
      });

      const pdfBytes = await readPdfBytes(pdfResponse);
      if (pdfBytes.length < 500) {
        throw new Error("PDF export returned an empty file - check backend logs.");
      }

      const formData = new FormData();
      const pdfFile = new File([pdfBytes], buildBuilderFilename(".pdf"), {
        type: "application/pdf",
      });
      formData.append("file", pdfFile);
      return uploadFile(formData);
    },
    onSuccess: async () => {
      toast.success("CV saved to your files.");
      await queryClient.invalidateQueries({ queryKey: ["files"] });
      await hydrateAuth();
    },
    onError: (error) => {
      toast.error(error.message || "Unable to save CV.");
    },
  });

  function handleClear() {
    clearUploadedResume();
    clearBuilder();
  }

  function handleToggleSection(name) {
    setSections({ ...sections, [name]: !sections[name] });
  }

  function handleLoadSampleCv() {
    const sampleFile = new File([SAMPLE_CV_TEXT], "anchorcv-sample-cv.txt", {
      type: "text/plain",
    });
    setUploadedResumeFile(sampleFile);
    if (!target.trim()) {
      setTarget("Graduate engineer or sustainability-focused research program");
    }
    buildMutation.mutate(sampleFile);
  }

  return (
    <section className="stack page-enter">
      <div className="panel stack">
        <div>
          <p className="eyebrow">Builder</p>
          <h2 className="page-title">Professional CV Builder</h2>
          <p className="muted-copy" style={{ margin: 0 }}>
            Turn your resume and analysis into a polished CV with the right
            structure, language, and export format.
          </p>
        </div>
      </div>

      <div className="grid two-up builder-layout">
        <div className="panel stack builder-form">
          <details className="workspace-section" open>
            <summary>
              <span>Resume Upload + Format</span>
              <span className="muted-copy">Required</span>
            </summary>
            <div className="workspace-section-content stack">
              <FileDropzone
                label="Resume upload"
                file={file}
                onChange={setUploadedResumeFile}
                accept=".pdf,.docx,.txt"
              />
              <button
                type="button"
                className="text-link-button"
                onClick={handleLoadSampleCv}
              >
                Try with a sample CV {"->"}
              </button>

              <div className="format-card-grid">
                {FORMATS.map((format) => (
                  <FormatCard
                    key={format.value}
                    selected={selectedFormat === format.value}
                    title={format.label}
                    badge={format.badge}
                    description={format.description}
                    onClick={() => setSelectedFormat(format.value)}
                  />
                ))}
              </div>
            </div>
          </details>

          <details className="workspace-section">
            <summary>
              <span>Customize</span>
              <span className="muted-copy">Role, notes, and guidance</span>
            </summary>
            <div className="workspace-section-content stack">
              <input
                placeholder="Target role or program"
                value={target}
                onChange={(event) => setTarget(event.target.value)}
              />

              <label className="stack tight">
                <span className="eyebrow">Job / scholarship description</span>
                <textarea
                  rows={8}
                  placeholder="Paste the job posting, scholarship description, or role requirements here. The AI will tailor your CV to match. You can also paste or edit the output from Resume Intelligence."
                  value={guidanceText}
                  onChange={(event) => setGuidanceText(event.target.value)}
                />
              </label>

              {cvRequirementPrefill ? (
                <div className="analysis-meta-card">
                  <strong>Latest analysis available</strong>
                  <p className="muted-copy" style={{ margin: "0.4rem 0 0" }}>
                    The last Resume Intelligence output can be reused here and
                    edited before you generate the final CV.
                  </p>
                  <div
                    className="button-row"
                    style={{ justifyContent: "flex-start", marginTop: "0.85rem" }}
                  >
                    <button
                      className="secondary-button"
                      onClick={() => setGuidanceText(cvRequirementPrefill)}
                    >
                      Use latest analysis
                    </button>
                    <button
                      className="secondary-button"
                      onClick={() => clearCvRequirementPrefill()}
                    >
                      Dismiss analysis prefill
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </details>

          <details className="workspace-section">
            <summary>
              <span>Advanced Options</span>
              <span className="muted-copy">Tone, color, sections</span>
            </summary>
            <div className="workspace-section-content stack">
              <div className="grid three-up">
                <select value={tone} onChange={(event) => setTone(event.target.value)}>
                  <option>Professional</option>
                  <option>Academic</option>
                  <option>Concise</option>
                </select>
                <select
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                >
                  <option>English</option>
                  <option>Spanish</option>
                  <option>French</option>
                  <option>German</option>
                  <option>Italian</option>
                  <option>Portuguese</option>
                  <option>Arabic</option>
                </select>
                <select
                  value={length}
                  onChange={(event) => setLength(event.target.value)}
                >
                  <option>Full</option>
                  <option>Condensed</option>
                  <option>Minimal</option>
                </select>
              </div>

              <div className="stack tight">
                <span className="eyebrow">Accent color</span>
                <div className="swatch-row">
                  {COLOR_SWATCHES.map((swatch) => (
                    <button
                      key={swatch}
                      type="button"
                      className={`swatch-button ${
                        colorTheme === swatch ? "selected" : ""
                      }`}
                      style={{ background: swatch }}
                      onClick={() => setColorTheme(swatch)}
                      aria-label={`Select ${swatch} color theme`}
                    />
                  ))}
                </div>
              </div>

              <div className="stack tight">
                <span className="eyebrow">Sections</span>
                {Object.entries(sections).map(([name, value]) => (
                  <label key={name} className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={value}
                      onChange={() => handleToggleSection(name)}
                    />
                    <span>{name}</span>
                  </label>
                ))}
              </div>

              <label className="stack tight">
                <span className="eyebrow">Special instructions</span>
                <textarea
                  rows={3}
                  placeholder="e.g., Emphasise leadership experience. Use UK spelling. Target healthcare sector. Keep it concise."
                  value={specialInstructions}
                  onChange={(event) => setSpecialInstructions(event.target.value)}
                />
                <span className="muted-copy" style={{ fontSize: "0.8rem" }}>
                  Extra guidance for the AI — stacked on top of the job description above.
                </span>
              </label>

              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={enhance}
                  onChange={() => setEnhance(!enhance)}
                />
                <span>
                  AI Enhance
                  <span className="muted-copy" style={{ marginLeft: "0.45rem" }}>
                    Rewrite bullet points for impact using AI. Adds [SUGGESTED]
                    metrics where appropriate.
                  </span>
                </span>
              </label>
            </div>
          </details>

          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <button
              className="primary-button-glow"
              disabled={isBlocked || !file || buildMutation.isPending}
              onClick={() => buildMutation.mutate()}
              title={isBlocked ? "Upgrade required" : undefined}
            >
              {buildMutation.isPending ? "Building CV..." : "Build CV"}
            </button>
            {isBlocked ? (
              <button
                type="button"
                className="secondary-button"
                onClick={() => navigate("/payment")}
              >
                Upgrade to Premium
              </button>
            ) : null}
            <button
              className="secondary-button"
              disabled={!result}
              onClick={handleClear}
            >
              Clear
            </button>
          </div>
        </div>

        <div className="panel stack builder-preview">
          <div className="button-row" style={{ justifyContent: "space-between" }}>
            <strong>Live preview</strong>
            {result ? (
              <div className="button-row" style={{ justifyContent: "flex-start" }}>
                <button
                  className="secondary-button"
                  onClick={() => docxMutation.mutate()}
                  disabled={docxMutation.isPending || !result.cv_data}
                >
                  {docxMutation.isPending ? "Preparing DOCX..." : "Export DOCX"}
                </button>
                <button
                  className="secondary-button"
                  onClick={() => pdfMutation.mutate()}
                  disabled={pdfMutation.isPending}
                >
                  {pdfMutation.isPending ? "Preparing PDF..." : "Export PDF"}
                </button>
                <button
                  className="secondary-button"
                  onClick={() => saveMutation.mutate()}
                  disabled={saveMutation.isPending}
                >
                  {saveMutation.isPending ? "Saving..." : "Save to Cloud"}
                </button>
              </div>
            ) : null}
          </div>

          {buildMutation.isPending ? (
            <LoadingQuotes
              quotes={LOADING_QUOTES}
              note="This usually takes 15-30 seconds. Please do not close the page."
            />
          ) : result ? (
            <>
              <p className="muted-copy" style={{ margin: 0 }}>
                This preview stays available while you move between pages and
                only resets when you clear it.
              </p>
              <iframe className="preview-frame" title="CV preview" srcDoc={result.html} />
            </>
          ) : (
            <div className="preview-empty-state">
              <div className="preview-empty-card">
                <div className="preview-wireframe">
                  <div className="preview-wireframe-bar hero" />
                  <div className="preview-wireframe-bar short" />
                  <div className="preview-wireframe-bar long" />
                  <div className="preview-wireframe-bar mid" />
                  <div className="preview-wireframe-bar long" />
                  <div className="preview-wireframe-bar short" />
                </div>
                <p className="muted-copy" style={{ margin: 0, textAlign: "center" }}>
                  Your CV preview will appear here.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
