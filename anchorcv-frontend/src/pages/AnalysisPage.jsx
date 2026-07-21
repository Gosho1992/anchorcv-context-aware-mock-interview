import { useMutation, useQueryClient } from "@tanstack/react-query";
import { openGmailCompose, buildApplicationSubject, htmlToPlainText, firstNonEmptyLine } from "../utils/gmail";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { postJson, postMultipart, uploadFile } from "../api/client";
import FileDropzone from "../components/FileDropzone";
import LoadingQuotes from "../components/LoadingQuotes";
import MatchScoreCard from "../components/MatchScoreCard";
import ModelSelect from "../components/ModelSelect";
import OutputTypeCards from "../components/OutputTypeCards";
import useAuthStore from "../store/useAuthStore";
import useCvWorkspaceStore from "../store/useCvWorkspaceStore";

const MOJIBAKE_MAP = [
  [/Ã¢â‚¬Â¢/g, "\u2022"],          // triple-encoded bullet → •
  [/â€¢/g, "\u2022"], // â€¢ → •
  [/Ã¢â‚¬”/g, "â€”"],
  [/Ã¢â‚¬"/g, "â€”"],
  [/Ã¢â‚¬Ëœ/g, "\u2018"],
  [/Ã¢â‚¬â„¢/g, "\u2019"],
  [/Ã¢â‚¬Å“/g, "\u201C"],
  [/Ã¢â‚¬\u009D/g, "\u201D"],
  [/Ã¢â‚¬/g, "\u201D"],
  [/Ã¢â€ '/g, "\u2192"],
  [/Ã¢â€ "/g, "\u2190"],
  [/Ã¢â€ "/g, "\u2194"],
  [/Ã¢â€°Â¥/g, "â‰¥"],
  [/Ã¢â€°Â¤/g, "â‰¤"],
  [/ÃƒÂ©/g, "Ã©"],
  [/ÃƒÂ¨/g, "Ã¨"],
  [/Ãƒ /g, "Ã "],
  [/ÃƒÂ¢/g, "Ã¢"],
  [/ÃƒÂ®/g, "Ã®"],
  [/ÃƒÂ´/g, "Ã´"],
  [/ÃƒÂ¹/g, "Ã¹"],
  [/ÃƒÂ»/g, "Ã»"],
  [/ÃƒÂ«/g, "Ã«"],
  [/ÃƒÂ¯/g, "Ã¯"],
  [/ÃƒÂ¼/g, "Ã¼"],
  [/ÃƒÂ¶/g, "Ã¶"],
  [/ÃƒÂ¤/g, "Ã¤"],
  [/ÃƒÂ±/g, "Ã±"],
];

const LOADING_QUOTES = [
  "Analysing your CV against the role requirements...",
  "Identifying strengths, gaps, and opportunities...",
  "Calculating your fit score...",
  "Matching your experience to what recruiters look for...",
  "Building your personalised action plan...",
  "Great applications start with great analysis...",
  "Scanning for ATS keywords and formatting issues...",
  "Tailored for international job seekers and scholars...",
  "Almost there - your insights are being prepared...",
  "Your next opportunity is one good analysis away...",
];

const JD_REQUIRED_TYPES = [
  "Application_Strategy",
  "Job_Match_Score",
  "Cover_Letter",
  "Email_Template",
];

const JD_QUESTIONS_TYPES = ["Resume_Optimization"];

const INDUSTRY_OPTIONS = [
  "Technology",
  "Finance & Banking",
  "Healthcare",
  "Engineering",
  "Business & Management",
  "Education & Academia",
  "Law",
  "Marketing & Media",
  "Other",
];

const LEVEL_OPTIONS = [
  "Entry-level (0-2 years)",
  "Mid-level (3-5 years)",
  "Senior (6+ years)",
  "Executive / Leadership",
];

const GOAL_OPTIONS = [
  "Get more job interviews",
  "Switch industry or role",
  "Apply for Master's / PhD",
  "Apply for a scholarship",
  "Get promoted or raise salary",
];

const JD_REQUIRED_LABELS = {
  Application_Strategy: "Application Strategy",
  Job_Match_Score: "Job Match Score",
  Cover_Letter: "Cover Letter",
  Email_Template: "Email to Professor",
};

function fixMojibake(html) {
  if (!html) {
    return html;
  }

  let output = html;
  for (const [pattern, replacement] of MOJIBAKE_MAP) {
    output = output.replace(pattern, replacement);
  }
  return output;
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function buildTimestamp() {
  return new Date().toISOString().replaceAll(":", "-");
}

function buildAnalysisFilename(extension) {
  return `anchorcv-analysis-${buildTimestamp()}${extension}`;
}

function buildAnalysisDocument(result) {
  const htmlBody =
    result?.result_html || `<pre>${escapeHtml(result?.result_text || "")}</pre>`;

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>AnchorCV Analysis</title>
    <style>
      * { color: #1a1a1a !important; background: white !important; border-color: #d1d5db !important; }
      body { font-family: Arial, sans-serif; padding: 2rem; max-width: 820px; margin: 0 auto; }
      h1, h2, h3, h4, h5, h6 { color: #1e3a5f !important; }
      a { color: #2563eb !important; }
      pre, code { background: #f3f4f6 !important; color: #111 !important; }
    </style>
  </head>
  <body>${htmlBody}</body>
</html>`;
}

function buildMatchScoreDocument(result) {
  function scoreCircle(value, label) {
    const numeric = Number(value || 0);
    const color =
      numeric >= 70 ? "#16a34a" : numeric >= 45 ? "#d97706" : "#dc2626";
    return `<div style="display:inline-block;text-align:center;margin:0 16px 20px;vertical-align:top">
      <div style="width:76px;height:76px;border-radius:50%;border:3px solid ${color};
        display:flex;align-items:center;justify-content:center;
        font-size:1.5rem;font-weight:700;color:${color};margin:0 auto 8px">${numeric}</div>
      <div style="font-size:0.82rem;color:#555">${label}</div>
    </div>`;
  }

  const warnings = (result?.warnings || []).length
    ? `<div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:8px;padding:14px 18px;margin:0 0 20px">
        <strong style="color:#dc2626">Integrity Flags</strong>
        <ul style="margin:8px 0 0;padding-left:18px;color:#dc2626">
          ${result.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}
        </ul>
      </div>`
    : "";

  const scores = `<div style="margin:20px 0 24px">
    ${scoreCircle(result?.overall_score, "Overall")}
    ${scoreCircle(result?.skill_match_score, "Skills")}
    ${scoreCircle(result?.experience_match_score, "Experience")}
    ${scoreCircle(result?.keyword_match_score, "Keywords")}
  </div>`;

  const summary = result?.summary
    ? `<h3 style="color:#1e3a5f">Summary</h3><p>${escapeHtml(result.summary)}</p>`
    : "";

  const strengths = (result?.strengths || []).length
    ? `<h3 style="color:#1e3a5f">Strengths</h3><ul>${result.strengths
        .map((strength) => `<li>${escapeHtml(strength)}</li>`)
        .join("")}</ul>`
    : "";

  const keywords = (result?.missing_keywords || []).length
    ? `<h3 style="color:#1e3a5f">Missing Keywords</h3>
       <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">
         ${result.missing_keywords
           .map(
             (keyword) =>
               `<span style="padding:4px 10px;border-radius:999px;background:#fff7ed;border:1px solid #fb923c;color:#c2410c;font-size:0.85rem">${escapeHtml(keyword)}</span>`
           )
           .join("")}
       </div>`
    : "";

  const improvements = (result?.improvements || []).length
    ? `<h3 style="color:#1e3a5f">Improvements</h3>
       <table style="width:100%;border-collapse:collapse;font-size:0.88rem">
         <thead>
           <tr style="background:#f1f5f9;text-align:left">
             <th style="padding:8px 10px;border:1px solid #e2e8f0">Area</th>
             <th style="padding:8px 10px;border:1px solid #e2e8f0">Current State</th>
             <th style="padding:8px 10px;border:1px solid #e2e8f0">Recommendation</th>
             <th style="padding:8px 10px;border:1px solid #e2e8f0">Priority</th>
           </tr>
         </thead>
         <tbody>
           ${result.improvements
             .map(
               (item) => `
           <tr>
             <td style="padding:8px 10px;border:1px solid #e2e8f0;vertical-align:top">${escapeHtml(item.area || "")}</td>
             <td style="padding:8px 10px;border:1px solid #e2e8f0;vertical-align:top">${escapeHtml(item.current_state || "")}</td>
             <td style="padding:8px 10px;border:1px solid #e2e8f0;vertical-align:top">${escapeHtml(item.recommendation || "")}</td>
             <td style="padding:8px 10px;border:1px solid #e2e8f0;vertical-align:top">${escapeHtml(item.priority || "")}</td>
           </tr>`
             )
             .join("")}
         </tbody>
       </table>`
    : "";

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>AnchorCV Job Match Score</title>
    <style>
      body { font-family: Arial, sans-serif; padding: 2rem; max-width: 820px; margin: 0 auto; color: #1a1a1a; }
      h1 { color: #1e3a5f; border-bottom: 2px solid #2563eb; padding-bottom: 8px; }
      h3 { color: #1e3a5f; margin: 20px 0 8px; }
      ul { padding-left: 1.4rem; margin: 0; }
      li { margin-bottom: 4px; }
    </style>
  </head>
  <body>
    <h1>Job Match Score Report</h1>
    ${warnings}
    ${scores}
    ${summary}
    ${strengths}
    ${keywords}
    ${improvements}
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

export default function AnalysisPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const hydrateAuth = useAuthStore((state) => state.hydrate);
  const accessStatus = useAuthStore((state) => state.accessStatus);
  const isBlocked = accessStatus?.access === "blocked";

  const [jobFile, setJobFile] = useState(null);
  const [industry, setIndustry] = useState("");
  const [careerLevel, setCareerLevel] = useState("");
  const [goal, setGoal] = useState("");
  const [resultTheme, setResultTheme] = useState("light");
  const [selectedModel, setSelectedModel] = useState("");

  const file = useCvWorkspaceStore((state) => state.uploadedResumeFile);
  const setUploadedResumeFile = useCvWorkspaceStore(
    (state) => state.setUploadedResumeFile
  );
  const clearUploadedResume = useCvWorkspaceStore(
    (state) => state.clearUploadedResume
  );
  const requirementText = useCvWorkspaceStore(
    (state) => state.analysisRequirementText
  );
  const setRequirementText = useCvWorkspaceStore(
    (state) => state.setAnalysisRequirementText
  );
  const outputType = useCvWorkspaceStore((state) => state.analysisOutputType);
  const setOutputType = useCvWorkspaceStore(
    (state) => state.setAnalysisOutputType
  );
  const result = useCvWorkspaceStore((state) => state.analysisResult);
  const setResult = useCvWorkspaceStore((state) => state.setAnalysisResult);
  const showFullPreview = useCvWorkspaceStore(
    (state) => state.analysisShowFullPreview
  );
  const setShowFullPreview = useCvWorkspaceStore(
    (state) => state.setAnalysisShowFullPreview
  );
  const clearAnalysis = useCvWorkspaceStore((state) => state.clearAnalysis);
  const setCvRequirementPrefill = useCvWorkspaceStore(
    (state) => state.setCvRequirementPrefill
  );

  const isMatchScore = outputType === "Job_Match_Score";
  const showBuilderButton = [
    "Application_Strategy",
    "ATS_Optimization",
    "Resume_Optimization",
  ].includes(outputType);
  const requiresJD = JD_REQUIRED_TYPES.includes(outputType);
  const showQuestionsMode =
    JD_QUESTIONS_TYPES.includes(outputType) &&
    !requirementText.trim() &&
    !jobFile;
  const jdMissing = requiresJD && !requirementText.trim() && !jobFile;

  useEffect(() => {
    document.title = "Analysis - AnchorCV";
  }, []);

  async function handleJobFileChange(nextFile) {
    setJobFile(nextFile);
    if (!nextFile || !nextFile.name.toLowerCase().endsWith(".txt")) {
      return;
    }

    try {
      const text = await nextFile.text();
      if (text.trim()) {
        setRequirementText(text);
      }
    } catch {
      toast.error("Failed to read the uploaded requirements file.");
    }
  }

  const mutation = useMutation({
    mutationFn: async () => {
      const formData = new FormData();

      if (selectedModel) {
        formData.append("model", selectedModel);
      }

      if (isMatchScore) {
        formData.append("resume_file", file);
        if (jobFile) {
          formData.append("requirement_file", jobFile);
        }
        if (requirementText.trim()) {
          formData.append("requirement_text", requirementText);
        }
        return postMultipart("/match", formData);
      }

      formData.append("file", file);
      let finalRequirementText = requirementText;
      if (showQuestionsMode && (industry || careerLevel || goal)) {
        finalRequirementText = [
          industry ? `Target industry: ${industry}` : "",
          careerLevel ? `Career level: ${careerLevel}` : "",
          goal ? `Main goal: ${goal}` : "",
        ]
          .filter(Boolean)
          .join("\n");
      }

      formData.append("requirement_text", finalRequirementText);
      formData.append("output_type", outputType);
      if (jobFile) {
        formData.append("requirement_file", jobFile);
      }
      return postMultipart("/analyse", formData);
    },
    onSuccess: (data) => {
      const cleaned = {
        ...data,
        result_html: fixMojibake(data?.result_html || ""),
        result_text: fixMojibake(data?.result_text || ""),
      };

      setResult(cleaned);
      setShowFullPreview(false);
      setCvRequirementPrefill(cleaned.result_text || "");

      if (!useAuthStore.getState().user?.onboarded_at) {
        postJson("/auth/me/onboard", {})
          .then(() => useAuthStore.getState().hydrate())
          .catch(() => {});
      }
    },
    onError: (error) => {
      toast.error(error.message || "Unable to run analysis.");
    },
  });

  const pdfMutation = useMutation({
    mutationFn: () => {
      const document = isMatchScore
        ? buildMatchScoreDocument(result)
        : buildAnalysisDocument(result);
      return postJson("/export/pdf", {
        html: document,
        filename: buildAnalysisFilename(".pdf"),
      });
    },
    onSuccess: (blob) => downloadBlob(blob, buildAnalysisFilename(".pdf")),
    onError: (error) => {
      toast.error(error.message || "Unable to export PDF.");
    },
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const document = isMatchScore
        ? buildMatchScoreDocument(result)
        : buildAnalysisDocument(result);

      const pdfResponse = await fetch("/api/export/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          html: document,
          filename: buildAnalysisFilename(".pdf"),
        }),
        credentials: "include",
      });

      const pdfBytes = await readPdfBytes(pdfResponse);
      if (pdfBytes.length < 500) {
        throw new Error("PDF export returned an empty file - check backend logs.");
      }

      const formData = new FormData();
      const fileToUpload = new File([pdfBytes], buildAnalysisFilename(".pdf"), {
        type: "application/pdf",
      });
      formData.append("file", fileToUpload);
      return uploadFile(formData);
    },
    onSuccess: async () => {
      toast.success("Analysis saved to your files.");
      await queryClient.invalidateQueries({ queryKey: ["files"] });
      await hydrateAuth();
    },
    onError: (error) => {
      toast.error(error.message || "Unable to save analysis.");
    },
  });

  const resultText = result?.result_html || "";
  const resumePreview = result?.resume_text || "";
  const previewText = showFullPreview
    ? resumePreview
    : resumePreview.slice(0, 300);
  const resultHeading = useMemo(
    () => (isMatchScore ? "Job Match Score" : "Result preview"),
    [isMatchScore]
  );

  function handleClear() {
    clearUploadedResume();
    setJobFile(null);
    clearAnalysis();
  }

  return (
    <section className="stack page-enter">
      <div className="panel stack">
        <div>
          <p className="eyebrow">Analysis</p>
          <h2 className="page-title">Resume Intelligence</h2>
          <p className="muted-copy" style={{ margin: 0 }}>
            Upload your CV, add a role or scholarship target, and turn the raw
            match into a concrete application plan.
          </p>
        </div>
      </div>

      <div className="grid two-up analysis-layout">
        <div className="panel stack analysis-left">
          <FileDropzone
            label="Upload your CV"
            file={file}
            onChange={setUploadedResumeFile}
          />
          <FileDropzone
            label="Upload job description or scholarship details"
            file={jobFile}
            onChange={handleJobFileChange}
            accept=".pdf,.docx,.txt"
          />

          <div className="stack tight">
            <span className="eyebrow">Choose output</span>
            <OutputTypeCards
              selectedOutputs={[outputType]}
              onToggle={setOutputType}
            />
          </div>

          <ModelSelect value={selectedModel} onChange={setSelectedModel} compact />

          <label className="stack tight">
            <span className="eyebrow">Requirements</span>
            <textarea
              rows={8}
              placeholder={
                requiresJD
                  ? `Paste the job or scholarship requirements for ${
                      JD_REQUIRED_LABELS[outputType] || "this output"
                    }.`
                  : "Paste job or scholarship requirements for best results, or leave blank for a broader review."
              }
              value={requirementText}
              onChange={(event) => setRequirementText(event.target.value)}
            />
          </label>

          {jdMissing ? (
            <div className="analysis-meta-card warn">
              <p style={{ margin: 0 }}>
                <strong>{JD_REQUIRED_LABELS[outputType]}</strong> needs job or
                scholarship requirements. Paste them above or upload a file to
                generate a meaningful result.
              </p>
            </div>
          ) : null}

          {showQuestionsMode ? (
            <div className="analysis-meta-card teal stack">
              <p style={{ margin: 0 }}>
                No requirements pasted yet. Answer these and AnchorCV will still
                tailor the improvement report.
              </p>
              <label className="stack tight">
                <span className="muted-copy">Target industry</span>
                <select
                  value={industry}
                  onChange={(event) => setIndustry(event.target.value)}
                >
                  <option value="">Select industry...</option>
                  {INDUSTRY_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label className="stack tight">
                <span className="muted-copy">Career level</span>
                <select
                  value={careerLevel}
                  onChange={(event) => setCareerLevel(event.target.value)}
                >
                  <option value="">Select level...</option>
                  {LEVEL_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label className="stack tight">
                <span className="muted-copy">Main goal</span>
                <select
                  value={goal}
                  onChange={(event) => setGoal(event.target.value)}
                >
                  <option value="">Select goal...</option>
                  {GOAL_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ) : null}

          {outputType === "ATS_Optimization" &&
          !requirementText.trim() &&
          !jobFile ? (
            <div className="analysis-meta-card">
              <p className="muted-copy" style={{ margin: 0 }}>
                Without requirements, this returns a general ATS formatting
                review. Add a target to also check keyword alignment.
              </p>
            </div>
          ) : null}

          <div className="button-row" style={{ justifyContent: "flex-start" }}>
            <button
              className="primary-button"
              disabled={isBlocked || !file || mutation.isPending || jdMissing}
              onClick={() => mutation.mutate()}
              title={isBlocked ? "Upgrade required" : undefined}
            >
              {mutation.isPending
                ? isMatchScore
                  ? "Calculating score..."
                  : "Running analysis..."
                : "Generate output"}
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

        <div className="panel stack analysis-right">
          <div className="analysis-result-head">
            <div className="stack tight" style={{ gap: "0.3rem" }}>
              <strong>{resultHeading}</strong>
              <span className="muted-copy" style={{ fontSize: "0.82rem" }}>
                Light mode is easier for CV readability. Dark mode is for
                night-time review only.
              </span>
            </div>
            <div className="analysis-theme-toggle">
              <button
                type="button"
                className={resultTheme === "light" ? "active" : ""}
                onClick={() => setResultTheme("light")}
              >
                Light
              </button>
              <button
                type="button"
                className={resultTheme === "dark" ? "active" : ""}
                onClick={() => setResultTheme("dark")}
              >
                Dark
              </button>
            </div>
          </div>

          {result ? (
            <div className="button-row" style={{ justifyContent: "flex-start" }}>
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
              <button
                className="secondary-button"
                onClick={() =>
                  openGmailCompose({
                    subject: buildApplicationSubject(
                      firstNonEmptyLine(requirementText),
                      firstNonEmptyLine(result?.resume_text)
                    ),
                    body:
                      result?.result_text ||
                      htmlToPlainText(result?.result_html || ""),
                  })
                }
              >
                Send via Gmail
              </button>
              {showBuilderButton ? (
                <button
                  className="secondary-button"
                  onClick={() => navigate("/builder")}
                >
                  Use in CV Builder
                </button>
              ) : null}
            </div>
          ) : null}

          {mutation.isPending ? (
            <LoadingQuotes
              quotes={LOADING_QUOTES}
              note="This usually takes 10-20 seconds. Please do not close the page."
            />
          ) : result ? (
            <>
              {result.requirement_extraction_failed && (
                <div
                  className="panel"
                  style={{
                    background: "var(--amber-soft, rgba(251,191,36,0.12))",
                    border: "1px solid var(--amber, #f59e0b)",
                    borderRadius: "var(--radius)",
                    padding: "1rem 1.25rem",
                    display: "flex",
                    gap: "0.75rem",
                    alignItems: "flex-start",
                  }}
                >
                  <span style={{ fontSize: "1.1rem", lineHeight: 1 }}>⚠️</span>
                  <div>
                    <strong style={{ display: "block", fontSize: "0.95rem", marginBottom: "0.25rem" }}>
                      Job description file could not be read
                    </strong>
                    <p className="muted-copy" style={{ margin: 0, fontSize: "0.88rem" }}>
                      We couldn't extract text from your uploaded file — it may be a scanned document
                      or image-based PDF. The analysis below ran without any job description and may not
                      reflect your target role.{" "}
                      <strong>Paste the job or program requirements directly into the text box and run again.</strong>
                    </p>
                  </div>
                </div>
              )}
              <p className="muted-copy" style={{ margin: 0 }}>
                This result stays available while you move between pages. The
                latest full text is also ready for the Builder guidance field.
              </p>

              <div className="result-reveal">
                <div
                  className={`preview-panel result-surface ${resultTheme}`}
                  style={{ minHeight: "320px", padding: "1.5rem" }}
                >
                  {isMatchScore ? (
                    <MatchScoreCard result={result} theme={resultTheme} />
                  ) : outputType === "Cover_Letter" || outputType === "Email_Template" ? (
                    <div className="ai-result-content">
                      <div
                        className={resultTheme === "dark" ? "" : "letter-preview"}
                        dangerouslySetInnerHTML={{ __html: resultText }}
                      />
                    </div>
                  ) : (
                    <div className="ai-result-content">
                      <div dangerouslySetInnerHTML={{ __html: resultText }} />
                    </div>
                  )}
                </div>
              </div>

              {!isMatchScore && resumePreview ? (
                <details className="preview-toggle-panel">
                  <summary>Extracted text preview</summary>
                  <div className="stack tight" style={{ marginTop: "1rem" }}>
                    <p className="muted-copy extract-preview-copy">
                      {previewText}
                      {!showFullPreview && resumePreview.length > 300 ? "..." : ""}
                    </p>
                    {resumePreview.length > 300 ? (
                      <button
                        type="button"
                        className="secondary-button compact-button"
                        onClick={() => setShowFullPreview(!showFullPreview)}
                      >
                        {showFullPreview ? "Show less" : "Show more"}
                      </button>
                    ) : null}
                  </div>
                </details>
              ) : null}
               </>
          ) : (
            <p
              className="muted-copy"
              style={{ margin: "2rem auto", textAlign: "center" }}
            >
              Run analysis to see results here.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
