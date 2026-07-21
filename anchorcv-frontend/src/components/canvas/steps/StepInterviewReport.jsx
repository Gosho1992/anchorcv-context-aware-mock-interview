import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import StepWrapper from "../StepWrapper";
import {
  getInterviewEvidenceMatrix,
  getInterviewEvidenceRewrites,
  postJson,
} from "../../../api/client";
import useAuthStore from "../../../store/useAuthStore";
import useCanvasStore from "../../../store/useCanvasStore";
import { trackCanvasEvent } from "../../../utils/canvasAnalytics";

function scoreColor(score) {
  if (score >= 75) return "var(--teal, #2dd4a8)";
  if (score >= 55) return "#f59e0b";
  return "#ef4444";
}

function CategoryBar({ label, score }) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem" }}>
        <span>{label}</span>
        <span style={{ color: scoreColor(score), fontWeight: 700 }}>{score}%</span>
      </div>
      <div
        aria-hidden="true"
        style={{
          height: "7px",
          borderRadius: "4px",
          background: "var(--border)",
          overflow: "hidden",
          margin: "0.25rem 0 0.7rem",
        }}
      >
        <div style={{ width: `${score}%`, height: "100%", background: scoreColor(score) }} />
      </div>
    </div>
  );
}

function SummaryStat({ label, value, className = "" }) {
  return (
    <div className={`analysis-meta-card ${className}`.trim()}>
      <p className="eyebrow" style={{ margin: 0 }}>{label}</p>
      <p style={{ margin: "0.35rem 0 0", fontSize: "1.35rem", fontWeight: 800 }}>{value}</p>
    </div>
  );
}

function MatrixEntry({ entry }) {
  return (
    <div className="panel stack tight" style={{ gap: "0.55rem" }}>
      <p style={{ margin: 0 }}><strong>Resume Claim:</strong> {entry.resume_claim}</p>
      {entry.related_job_requirement ? (
        <p className="muted-copy" style={{ margin: 0 }}>
          <strong>Related Job Requirement:</strong> {entry.related_job_requirement}
        </p>
      ) : null}
      <p className="muted-copy" style={{ margin: 0 }}>
        <strong>Interview Question:</strong> {entry.interview_question}
      </p>
      {entry.user_answer ? (
        <p className="muted-copy" style={{ margin: 0 }}>
          <strong>User Answer:</strong> {entry.user_answer}
        </p>
      ) : null}
      <p style={{ margin: 0 }}><strong>Explanation:</strong> {entry.explanation}</p>

      {(entry.missing_evidence || []).length > 0 ? (
        <div>
          <p className="eyebrow" style={{ marginBottom: "0.3rem" }}>Missing Evidence</p>
          <ul style={{ margin: 0, paddingLeft: "1.15rem" }}>
            {entry.missing_evidence.map((item, index) => (
              <li key={`${item}-${index}`} className="muted-copy" style={{ marginBottom: "0.2rem" }}>
                {item}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {entry.suggested_follow_up_question ? (
        <p className="muted-copy" style={{ margin: 0 }}>
          <strong>Suggested Follow-up:</strong> {entry.suggested_follow_up_question}
        </p>
      ) : null}

      <p style={{ margin: 0 }}><strong>Recommendation:</strong> {entry.recommendation}</p>
    </div>
  );
}

function GroupBlock({ title, entries, toneClass = "" }) {
  if (!entries?.length) {
    return null;
  }

  return (
    <div className="stack">
      <div className={`analysis-meta-card ${toneClass}`.trim()}>
        <p style={{ margin: 0, fontWeight: 700 }}>
          {title} ({entries.length})
        </p>
      </div>
      <div className="stack">
        {entries.map((entry) => (
          <MatrixEntry key={`${entry.claim_id}-${entry.question_id}`} entry={entry} />
        ))}
      </div>
    </div>
  );
}

function RewriteSummaryStat({ label, value, tone = "" }) {
  return (
    <div className={`analysis-meta-card ${tone}`.trim()}>
      <p className="eyebrow" style={{ margin: 0 }}>{label}</p>
      <p style={{ margin: "0.35rem 0 0", fontSize: "1.35rem", fontWeight: 800 }}>{value}</p>
    </div>
  );
}

function RewriteEntryCard({ entry }) {
  return (
    <div className="panel stack">
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", flexWrap: "wrap" }}>
        <strong>Evidence: {entry.evidence_strength}</strong>
        {entry.related_job_requirement ? (
          <span className="muted-copy" style={{ fontSize: "0.84rem" }}>
            Job alignment: {entry.related_job_requirement}
          </span>
        ) : null}
      </div>

      <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))" }}>
        <div className="analysis-meta-card warn">
          <p className="eyebrow" style={{ marginBottom: "0.3rem" }}>Before</p>
          <p style={{ margin: 0 }}>{entry.original_resume_claim}</p>
        </div>
        <div className={`analysis-meta-card ${entry.insufficient_evidence ? "warn" : "teal"}`}>
          <p className="eyebrow" style={{ marginBottom: "0.3rem" }}>
            {entry.insufficient_evidence ? "After (insufficient evidence)" : "After"}
          </p>
          <p style={{ margin: 0 }}>
            {entry.improved_resume_claim || "Insufficient evidence to produce a truthful rewrite."}
          </p>
        </div>
      </div>

      <p style={{ margin: 0 }}>
        <strong>Reason for weakness:</strong> {entry.reason_for_weakness}
      </p>
      <p className="muted-copy" style={{ margin: 0 }}>
        <strong>Explanation of changes:</strong> {entry.explanation_of_changes}
      </p>
    </div>
  );
}

function buildReportHtml(candidateLabel, report, matrix, rewrites, interviewConfiguration, benchmarkText) {
  const esc = (value) =>
    String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  const list = (items) => (items || []).map((item) => `<li>${esc(item)}</li>`).join("");

  const groupedClaims = matrix?.grouped_claims || {};
  const matrixRows = [
    ["Strong", groupedClaims.strong || []],
    ["Moderate", groupedClaims.moderate || []],
    ["Weak", groupedClaims.weak || []],
    ["Unsupported", groupedClaims.unsupported || []],
  ]
    .flatMap(([title, entries]) =>
      (entries || []).map(
        (entry) => `<li><strong>${title}</strong> - ${esc(entry.resume_claim)}<br>
${entry.related_job_requirement ? `Job Requirement: ${esc(entry.related_job_requirement)}<br>` : ""}
Evidence: ${esc(entry.evidence_strength)}<br>
Explanation: ${esc(entry.explanation)}<br>
${(entry.missing_evidence || []).length ? `Missing: ${esc(entry.missing_evidence.join(", "))}<br>` : ""}
${entry.recommendation ? `Recommendation: ${esc(entry.recommendation)}` : ""}</li>`
      )
    )
    .join("");

  const rewriteRows = (rewrites?.entries || [])
    .map(
      (entry) => `<li><strong>${esc(entry.evidence_strength)}</strong><br>
Before: ${esc(entry.original_resume_claim)}<br>
After: ${esc(entry.improved_resume_claim || "Insufficient evidence for grounded rewrite")}
<br>Reason: ${esc(entry.reason_for_weakness)}
<br>Explanation: ${esc(entry.explanation_of_changes)}</li>`
    )
    .join("");

  const configRows = [
    ["Interview Style", interviewConfiguration?.style || "Mixed"],
    ["Difficulty", interviewConfiguration?.difficulty || "Intermediate"],
    ["Questions", interviewConfiguration?.questions || "-"],
    ["Focus Areas", interviewConfiguration?.focusAreas || "General coverage"],
    ["Time Limit", interviewConfiguration?.timeLimit || "No Limit"],
  ]
    .map(([label, value]) => `<li><strong>${esc(label)}:</strong> ${esc(value)}</li>`)
    .join("");

  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Context-Aware Mock Interview Report</title>
<style>
body{font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:2rem;color:#1a1a1a;line-height:1.55}
h1{color:#1e3a5f}h2{color:#1e3a5f;border-bottom:1px solid #d1d5db;padding-bottom:4px}
.score{font-size:2.4rem;font-weight:800;color:#1e3a5f}
small{color:#6b7280}
</style></head><body>
<h1>AnchorCV Context-Aware Mock Interview Report</h1>
<p><strong>Candidate:</strong> ${esc(candidateLabel)}</p>
<p class="score">${report.overall_score}/100</p>
<h2>Interview Configuration</h2><ul>${configRows}</ul>
<h2>Interview Readiness</h2><p>${esc(report.executive_summary)}</p>
<p><strong>Benchmark:</strong> ${esc(benchmarkText || "")}</p>
<h2>Category Scores</h2><ul>
<li>Technical: ${report.category_scores?.technical ?? "-"}%</li>
<li>Behavioral: ${report.category_scores?.behavioral ?? "-"}%</li>
<li>Communication: ${report.category_scores?.communication ?? "-"}%</li></ul>
<h2>Strong Areas</h2><ul>${list(report.strengths)}</ul>
<h2>Needs Improvement</h2><ul>${list(report.weaknesses)}</ul>
<h2>Recommended Practice Areas</h2><ol>${list(report.recommendations)}</ol>
${report.best_answer?.question ? `<h2>Best Answer</h2><p><strong>${esc(report.best_answer.question)}</strong><br>${esc(report.best_answer.why)}</p>` : ""}
${report.worst_answer?.question ? `<h2>Toughest Answer</h2><p><strong>${esc(report.worst_answer.question)}</strong><br>${esc(report.worst_answer.why)}</p>` : ""}

${matrix ? `<h2>Interview Evidence Analysis</h2>
<ul>
<li>Total Claims: ${matrix.summary?.total_claims ?? 0}</li>
<li>Strong: ${matrix.summary?.strong_claims ?? 0}</li>
<li>Moderate: ${matrix.summary?.moderate_claims ?? 0}</li>
<li>Weak: ${matrix.summary?.weak_claims ?? 0}</li>
<li>Unsupported: ${matrix.summary?.unsupported_claims ?? 0}</li>
</ul>
<p>${esc(matrix.narrative_summary || "")}</p>
<ul>${matrixRows}</ul>` : ""}
${rewrites ? `<h2>Optional Resume Improvement</h2>
<ul>
<li>Targeted Claims: ${rewrites.summary?.targeted_claims ?? 0}</li>
<li>Rewritten: ${rewrites.summary?.rewritten_claims ?? 0}</li>
<li>Insufficient Evidence: ${rewrites.summary?.insufficient_evidence_claims ?? 0}</li>
</ul>
${rewriteRows ? `<ol>${rewriteRows}</ol>` : "<p>No rewrite actions required.</p>"}` : ""}
</body></html>`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

const DIFFICULTY_LABELS = {
  entry: "Beginner",
  mid: "Intermediate",
  senior: "Senior",
  lead: "Expert",
};

const STYLE_LABELS = {
  mixed: "Mixed",
  technical: "Technical",
  behavioral: "Behavioral",
  executive: "Executive / Leadership",
  case: "Case Study",
};

const RESUME_NAME_BLOCK_WORDS = new Set([
  "resume",
  "curriculum",
  "vitae",
  "summary",
  "profile",
  "experience",
  "education",
  "skills",
  "projects",
  "certifications",
  "contact",
  "phone",
  "email",
  "address",
]);

function toTitleCase(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\b([a-z])/g, (char) => char.toUpperCase());
}

function looksLikeCandidateName(value) {
  const text = String(value || "").trim();
  if (!text || text.length < 3 || text.length > 60) return false;
  if (/@/.test(text) || /https?:\/\//i.test(text) || /\d/.test(text)) return false;

  const compact = text.replace(/[|•·]/g, " ").replace(/\s+/g, " ").trim();
  const words = compact.split(" ");
  if (words.length < 2 || words.length > 4) return false;
  if (words.some((word) => RESUME_NAME_BLOCK_WORDS.has(word.toLowerCase()))) return false;

  return words.every((word) => /^[A-Za-z][A-Za-z'.-]*$/.test(word));
}

function normalizeCandidateName(value) {
  const compact = String(value || "").replace(/\s+/g, " ").trim();
  if (!compact) return "";

  const alpha = compact.replace(/[^A-Za-z ]/g, "").trim();
  const allUpper = alpha && alpha === alpha.toUpperCase();
  return allUpper ? toTitleCase(compact) : compact;
}

function extractResumeCandidateName(cvText) {
  const lines = String(cvText || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 30);

  for (const line of lines) {
    const primary = line.split(/[|•·]/)[0].trim();
    if (looksLikeCandidateName(primary)) {
      return normalizeCandidateName(primary);
    }
  }

  return "";
}

function extractPronounsFromText(text) {
  const match = String(text || "").match(/\b(she\/?her|he\/?him|they\/?them)\b/i);
  if (!match) return "";

  return match[1]
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace("sheher", "she/her")
    .replace("hehim", "he/him")
    .replace("theythem", "they/them");
}

function inferPronounsFromGender(genderValue) {
  const gender = String(genderValue || "").toLowerCase();
  if (gender.startsWith("f")) return "she/her";
  if (gender.startsWith("m")) return "he/him";
  if (gender.includes("non") || gender.includes("nb") || gender.includes("they")) return "they/them";
  return "";
}

function extractStructuredIdentity(generatedResults) {
  if (!generatedResults || typeof generatedResults !== "object") {
    return { name: "", pronouns: "", gender: "" };
  }

  const nameKeys = new Set(["candidate_name", "full_name", "name", "resume_name", "applicant_name", "person_name"]);
  const pronounKeys = new Set(["pronouns", "pronoun"]);
  const genderKeys = new Set(["gender", "sex"]);

  let name = "";
  let pronouns = "";
  let gender = "";
  const seen = new Set();
  const queue = [generatedResults];

  while (queue.length > 0) {
    const node = queue.shift();
    if (!node || typeof node !== "object" || seen.has(node)) continue;
    seen.add(node);

    for (const [key, value] of Object.entries(node)) {
      const normalizedKey = String(key || "").toLowerCase();

      if (typeof value === "string") {
        if (!name && (nameKeys.has(normalizedKey) || normalizedKey.endsWith("_name")) && looksLikeCandidateName(value)) {
          name = normalizeCandidateName(value);
        }
        if (!pronouns && pronounKeys.has(normalizedKey)) {
          pronouns = extractPronounsFromText(value);
        }
        if (!gender && genderKeys.has(normalizedKey)) {
          gender = String(value || "").trim().toLowerCase();
        }
      } else if (value && typeof value === "object") {
        queue.push(value);
      }
    }
  }

  return { name, pronouns, gender };
}

function resolveCandidateIdentity(cvText, generatedResults, user) {
  const parsedName = extractResumeCandidateName(cvText);
  const parsedPronouns = extractPronounsFromText(cvText);
  const structured = extractStructuredIdentity(generatedResults);

  const accountName = (String(user?.first_name || "") + " " + String(user?.last_name || "")).trim();
  const fallbackName = accountName || user?.name || user?.full_name || "Candidate";

  const name = parsedName || structured.name || fallbackName;
  const pronouns = parsedPronouns || structured.pronouns || inferPronounsFromGender(structured.gender);

  return {
    name,
    pronouns,
    displayName: pronouns ? (name + " (" + pronouns + ")") : name,
  };
}

function resolveDifficultyBackend(config) {
  const backend = String(config?.difficultyBackend || "").toLowerCase();
  if (["entry", "mid", "senior", "lead"].includes(backend)) return backend;

  const value = String(config?.difficulty || "").toLowerCase();
  if (value === "beginner" || value === "entry") return "entry";
  if (value === "intermediate" || value === "mid") return "mid";
  if (value === "senior") return "senior";
  if (value === "expert" || value === "lead") return "lead";
  return "mid";
}

function resolveDifficultyLabel(config) {
  const explicit = String(config?.difficultyLabel || "").replace("(Default)", "").trim();
  if (explicit) return explicit;
  return DIFFICULTY_LABELS[resolveDifficultyBackend(config)] || "Intermediate";
}

function resolveInterviewStyleLabel(config) {
  const explicit = String(config?.styleLabel || "").replace("(Default)", "").trim();
  if (explicit) return explicit;
  return STYLE_LABELS[String(config?.style || "mixed").toLowerCase()] || "Mixed";
}

function resolveTimeLimitLabel(config) {
  const minutes = Number(config?.timeLimitMinutes);
  if (!Number.isFinite(minutes) || minutes <= 0) return "No Limit";
  return String(minutes) + " Minutes";
}

function resolveFocusAreasLabel(config) {
  const focusAreas = Array.isArray(config?.focusAreas)
    ? config.focusAreas.filter((item) => typeof item === "string" && item.trim())
    : [];
  return focusAreas.length > 0 ? focusAreas.join(", ") : "General coverage";
}

function buildInterviewConfigurationSummary(config, totalQuestions) {
  const count = Number(config?.numQuestions);
  return {
    style: resolveInterviewStyleLabel(config),
    difficulty: resolveDifficultyLabel(config),
    questions: Number.isFinite(count) && count > 0 ? count : totalQuestions,
    focusAreas: resolveFocusAreasLabel(config),
    timeLimit: resolveTimeLimitLabel(config),
  };
}

function normalizeBenchmarkText(comparison, difficultyLabel) {
  const selected = String(difficultyLabel || "Intermediate").trim();
  const fallback = "Benchmarked against " + selected + " difficulty.";
  const raw = String(comparison || "").trim();
  if (!raw) return fallback;

  const replaced = raw
    .replace(/\bentry(?:-level)?\b/gi, selected)
    .replace(/\bbeginner\b/gi, selected)
    .replace(/\bmid(?:\s|-)?level\b/gi, selected)
    .replace(/\bintermediate\b/gi, selected)
    .replace(/\bsenior\b/gi, selected)
    .replace(/\blead\b/gi, selected)
    .replace(/\bexpert\b/gi, selected);

  if (!/benchmark|benchmarked/i.test(replaced)) {
    return replaced + " Benchmarked against " + selected + " difficulty.";
  }

  return replaced;
}

function deriveReadiness(report, matrix, difficultyLabel) {
  const overall = Number(report?.overall_score || 0);
  const weak = Number(matrix?.summary?.weak_claims || 0);
  const unsupported = Number(matrix?.summary?.unsupported_claims || 0);
  const benchmark = String(difficultyLabel || "Intermediate");

  if (overall >= 78 && weak + unsupported <= 1) {
    return {
      level: "high",
      label: "High Interview Readiness",
      recommendation: "Your readiness is strong for a " + benchmark + " benchmark. Focus on practicing weaker interview areas before final interviews.",
    };
  }

  if (overall >= 60) {
    return {
      level: "moderate",
      label: "Moderate Interview Readiness",
      recommendation: "You are progressing well for a " + benchmark + " benchmark. Strengthen weak and unsupported topics with targeted practice.",
    };
  }

  return {
    level: "low",
    label: "Low Interview Readiness",
    recommendation: "Critical gaps remain for a " + benchmark + " benchmark. Choose focused practice first, and rewrite weak resume claims only when needed.",
  };
}

export default function StepInterviewReport({ onBack, onRestart }) {
  const user = useAuthStore((state) => state.user);
  const questions = useCanvasStore((state) => state.interviewQuestions);
  const answers = useCanvasStore((state) => state.interviewAnswers);
  const config = useCanvasStore((state) => state.interviewConfig);
  const selectedModel = useCanvasStore((state) => state.selectedModel);
  const cvText = useCanvasStore((state) => state.cvText);
  const generatedResults = useCanvasStore((state) => state.generatedResults);
  const report = useCanvasStore((state) => state.interviewReport);

  const contextEvidenceSessionId = useCanvasStore((state) => state.contextEvidenceSessionId);
  const matrix = useCanvasStore((state) => state.interviewEvidence);
  const rewrites = useCanvasStore((state) => state.interviewEvidenceRewrites);

  const setInterviewReport = useCanvasStore((state) => state.setInterviewReport);
  const setInterviewQuestions = useCanvasStore((state) => state.setInterviewQuestions);
  const setInterviewEvidence = useCanvasStore((state) => state.setInterviewEvidence);
  const setInterviewEvidenceRewrites = useCanvasStore((state) => state.setInterviewEvidenceRewrites);
  const clearContextEvidence = useCanvasStore((state) => state.clearContextEvidence);

  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [interviewEvidenceLoading, setInterviewEvidenceLoading] = useState(false);
  const [interviewEvidenceError, setInterviewEvidenceError] = useState("");
  const [rewriteLoading, setRewriteLoading] = useState(false);
  const [rewriteError, setRewriteError] = useState("");
  const requestedRef = useRef(false);
  const interviewEvidenceRequestedRef = useRef(false);

  const candidateIdentity = useMemo(() => {
    const configured = config?.candidateIdentity || null;
    const configuredName = String(configured?.name || "").trim();
    const configuredPronouns = String(configured?.pronouns || "").trim();

    if (configuredName) {
      return {
        name: configuredName,
        pronouns: configuredPronouns,
        displayName: configuredPronouns ? `${configuredName} (${configuredPronouns})` : configuredName,
        source: configured?.source || "interview_config",
      };
    }

    return resolveCandidateIdentity(cvText, generatedResults, user);
  }, [config?.candidateIdentity, cvText, generatedResults, user]);

  const answeredPairs = useMemo(
    () =>
      questions
        .map((question, index) => {
          const answer = answers[question.id];
          if (!answer || !answer.answer_text || !answer.evaluation) {
            return null;
          }

          if (answer.question_id && answer.question_id !== question.id) {
            return null;
          }

          return {
            question: String(question.question || answer.question || "").trim(),
            type: question.type || answer.type || "mixed",
            answer_text: answer.answer_text,
            overall_score: answer.overall_score || 0,
            scores: answer.scores || {},
            attempts: answer.attempts || 1,
            question_id: question.id,
            question_order: index + 1,
          };
        })
        .filter(Boolean),
    [questions, answers]
  );

  const interviewConfiguration = useMemo(
    () => buildInterviewConfigurationSummary(config, questions.length),
    [config, questions.length]
  );

  const selectedDifficultyBackend = useMemo(() => resolveDifficultyBackend(config), [config]);

  const hasResolvedDifficulty = useMemo(
    () => Boolean(config && (String(config?.difficultyBackend || "").trim() || String(config?.difficulty || "").trim())),
    [config]
  );

  const contextEvidenceEnabled = useMemo(
    () => Boolean(config?.contextEvidenceEnabled && contextEvidenceSessionId),
    [config?.contextEvidenceEnabled, contextEvidenceSessionId]
  );

  const benchmarkText = useMemo(
    () => normalizeBenchmarkText(report?.comparison, interviewConfiguration.difficulty),
    [report?.comparison, interviewConfiguration.difficulty]
  );

  const readiness = useMemo(
    () => deriveReadiness(report, matrix, interviewConfiguration.difficulty),
    [report, matrix, interviewConfiguration.difficulty]
  );

  const highRiskTopics = useMemo(() => {
    const unsupported = matrix?.grouped_claims?.unsupported || [];
    const weak = matrix?.grouped_claims?.weak || [];
    return [...unsupported, ...weak].slice(0, 5);
  }, [matrix]);

  const shouldOfferRewrite = readiness.level === "low";

  useEffect(() => {
    if (report || requestedRef.current || answeredPairs.length === 0 || !hasResolvedDifficulty) {
      return;
    }

    requestedRef.current = true;

    async function fetchReport() {
      setLoading(true);
      setError("");
      try {
        const result = await postJson("/interview/report", {
          name: candidateIdentity.name,
          difficulty: selectedDifficultyBackend,
          qa_pairs: answeredPairs.map((item) => ({
            question: item.question,
            type: item.type || "mixed",
            answer_text: item.answer_text,
            overall_score: item.overall_score || 0,
            scores: item.scores || {},
            attempts: item.attempts || 1,
          })),
          model: selectedModel || "",
        });

        setInterviewReport(result);
      } catch (err) {
        const message = err?.message || "Report generation failed.";
        setError(message);
        requestedRef.current = false;
        trackCanvasEvent("canvas_error_shown", {
          flow: "interview",
          step_name: "interviewReport",
          error_type: "report_failed",
          message,
        });
      } finally {
        setLoading(false);
      }
    }

    fetchReport();
  }, [
    report,
    answeredPairs,
    candidateIdentity.name,
    selectedDifficultyBackend,
    selectedModel,
    setInterviewReport,
    hasResolvedDifficulty,
  ]);

  useEffect(() => {
    if (!contextEvidenceEnabled || interviewEvidenceRequestedRef.current) {
      return;
    }

    interviewEvidenceRequestedRef.current = true;

    async function loadInterviewEvidenceMatrix() {
      setInterviewEvidenceLoading(true);
      setInterviewEvidenceError("");

      try {
        const matrixPayload = matrix || (await getInterviewEvidenceMatrix(contextEvidenceSessionId));
        if (!matrix) {
          setInterviewEvidence(matrixPayload);
        }
      } catch (err) {
        const message = err?.message || "Could not load interview evidence analysis for this session.";
        setInterviewEvidenceError(message);
        interviewEvidenceRequestedRef.current = false;
        trackCanvasEvent("canvas_error_shown", {
          flow: "interview",
          step_name: "interviewReport",
          error_type: "context_outputs_failed",
          message,
        });
      } finally {
        setInterviewEvidenceLoading(false);
      }
    }

    loadInterviewEvidenceMatrix();
  }, [contextEvidenceEnabled, contextEvidenceSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadRewritesOnDemand() {
    if (!contextEvidenceSessionId) {
      return;
    }

    setRewriteLoading(true);
    setRewriteError("");
    try {
      const payload = rewrites || (await getInterviewEvidenceRewrites(contextEvidenceSessionId));
      if (!rewrites) {
        setInterviewEvidenceRewrites(payload);
      }
    } catch (err) {
      const message = err?.message || "Could not generate grounded rewrites for this session.";
      setRewriteError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: "interview",
        step_name: "interviewReport",
        error_type: "rewrite_load_failed",
        message,
      });
    } finally {
      setRewriteLoading(false);
    }
  }

  async function exportPdf() {
    if (!report) {
      return;
    }

    setExporting(true);
    try {
      const html = buildReportHtml(candidateIdentity.displayName, report, matrix, rewrites, interviewConfiguration, benchmarkText);
      const filename = "anchorcv-context-aware-interview-report.pdf";
      const blob = await postJson("/export/pdf", { html, filename });
      downloadBlob(blob, filename);
      toast.success("Report downloaded.");
    } catch (err) {
      setError(err?.message || "PDF export failed.");
    } finally {
      setExporting(false);
    }
  }

  function practiceAgain() {
    setInterviewQuestions([]);
    setInterviewReport(null);
    clearContextEvidence();
    onRestart?.();
  }

  return (
    <StepWrapper
      title="Context-Aware Mock Interview Report"
      description={`${candidateIdentity.displayName} · ${answeredPairs.length}/${questions.length} questions answered`}
      onBack={onBack}
      maxWidth="980px"
    >
      <div className="stack">
        {answeredPairs.length === 0 ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>No answers recorded. Go back and answer at least one question.</p>
          </div>
        ) : null}

        {loading ? (
          <p className="muted-copy" style={{ margin: 0 }}>
            Generating Interview Report...
          </p>
        ) : null}

        {error ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>{error}</p>
            <button
              type="button"
              className="secondary-button compact-button"
              style={{ marginTop: "0.6rem" }}
              onClick={() => {
                requestedRef.current = false;
                setInterviewReport(null);
                setError("");
              }}
            >
              Retry
            </button>
          </div>
        ) : null}

        {report ? (
          <div className="stack result-reveal">
            <div className="analysis-meta-card">
              <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>Interview Configuration</p>
              <div className="stack tight">
                <p style={{ margin: 0 }}><strong>Interview Style:</strong> {interviewConfiguration.style}</p>
                <p style={{ margin: 0 }}><strong>Difficulty:</strong> {interviewConfiguration.difficulty}</p>
                <p style={{ margin: 0 }}><strong>Questions:</strong> {interviewConfiguration.questions}</p>
                <p style={{ margin: 0 }}><strong>Focus Areas:</strong> {interviewConfiguration.focusAreas}</p>
                <p style={{ margin: 0 }}><strong>Time Limit:</strong> {interviewConfiguration.timeLimit}</p>
              </div>
            </div>

            <div
              className="analysis-meta-card"
              style={{ display: "flex", gap: "1.2rem", alignItems: "center", flexWrap: "wrap" }}
            >
              <div
                role="img"
                aria-label={`Overall score ${report.overall_score} out of 100`}
                style={{
                  width: "92px",
                  height: "92px",
                  borderRadius: "50%",
                  display: "grid",
                  placeItems: "center",
                  fontSize: "1.6rem",
                  fontWeight: 800,
                  color: "#fff",
                  flexShrink: 0,
                  background: scoreColor(report.overall_score),
                }}
              >
                {report.overall_score}
              </div>
              <div style={{ flex: 1, minWidth: "240px" }}>
                <CategoryBar label="Technical" score={report.category_scores?.technical || 0} />
                <CategoryBar label="Behavioral" score={report.category_scores?.behavioral || 0} />
                <CategoryBar label="Communication" score={report.category_scores?.communication || 0} />
              </div>
            </div>

            <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
              <div className="analysis-meta-card">
                <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>Communication</p>
                <p style={{ margin: 0 }}>
                  Score: {report.category_scores?.communication || 0}%
                </p>
              </div>
              <div className="analysis-meta-card">
                <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>Technical Depth</p>
                <p style={{ margin: 0 }}>
                  Score: {report.category_scores?.technical || 0}%
                </p>
              </div>
              <div className="analysis-meta-card">
                <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>Behavioral Performance</p>
                <p style={{ margin: 0 }}>
                  Score: {report.category_scores?.behavioral || 0}%
                </p>
              </div>
            </div>

            <div className="analysis-meta-card">
              <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>Overall Interview Readiness</p>
              <p style={{ margin: "0 0 0.35rem", fontWeight: 700 }}>{readiness.label}</p>
              <p style={{ margin: "0 0 0.35rem" }}>{report.executive_summary}</p>
              <p className="muted-copy" style={{ margin: 0 }}>{readiness.recommendation}</p>
            </div>

            <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
              <div className="analysis-meta-card teal">
                <p style={{ margin: "0 0 0.4rem", fontWeight: 700 }}>Strong Areas</p>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(report.strengths || []).map((item, index) => (
                    <li key={`strength-${index}-${item}`} className="muted-copy" style={{ marginBottom: "0.3rem" }}>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="analysis-meta-card warn">
                <p style={{ margin: "0 0 0.4rem", fontWeight: 700 }}>Needs Improvement</p>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(report.weaknesses || []).map((item, index) => (
                    <li key={`weakness-${index}-${item}`} className="muted-copy" style={{ marginBottom: "0.3rem" }}>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="analysis-meta-card">
                <p style={{ margin: "0 0 0.4rem", fontWeight: 700 }}>Recommended Practice Areas</p>
                <ol style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(report.recommendations || []).map((item, index) => (
                    <li key={`plan-${index}-${item}`} className="muted-copy" style={{ marginBottom: "0.3rem" }}>
                      {item}
                    </li>
                  ))}
                </ol>
              </div>
            </div>

            {benchmarkText ? (
              <p className="subtle-copy" style={{ margin: 0 }}><strong>Benchmark:</strong> {benchmarkText}</p>
            ) : null}

            {contextEvidenceEnabled ? (
              <div className="stack">
                <div className="analysis-meta-card">
                  <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>Interview Evidence Analysis</p>
                  <p style={{ margin: 0 }}>
                    This section validates whether your answers genuinely support interview claims from your resume
                    against your target job requirements.
                  </p>
                </div>

                {interviewEvidenceLoading ? (
                  <p className="muted-copy" style={{ margin: 0 }}>
                    Loading interview evidence matrix...
                  </p>
                ) : null}

                {interviewEvidenceError ? (
                  <div className="analysis-meta-card warn">
                    <p style={{ margin: 0 }}>{interviewEvidenceError}</p>
                    <button
                      type="button"
                      className="secondary-button compact-button"
                      style={{ marginTop: "0.6rem" }}
                      onClick={() => {
                        interviewEvidenceRequestedRef.current = false;
                        setInterviewEvidenceError("");
                      }}
                    >
                      Retry
                    </button>
                  </div>
                ) : null}

                {matrix ? (
                  <>
                    <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
                      <SummaryStat label="Total Claims" value={matrix.summary?.total_claims ?? 0} />
                      <SummaryStat label="Strong" value={matrix.summary?.strong_claims ?? 0} className="teal" />
                      <SummaryStat label="Moderate" value={matrix.summary?.moderate_claims ?? 0} />
                      <SummaryStat label="Weak" value={matrix.summary?.weak_claims ?? 0} className="warn" />
                      <SummaryStat label="Unsupported" value={matrix.summary?.unsupported_claims ?? 0} className="warn" />
                    </div>

                    <div className="analysis-meta-card">
                      <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>Narrative Summary</p>
                      <p style={{ margin: 0 }}>{matrix.narrative_summary}</p>
                    </div>

                    <GroupBlock title="Strong Evidence" entries={matrix.grouped_claims?.strong || []} toneClass="teal" />
                    <GroupBlock title="Moderate Evidence" entries={matrix.grouped_claims?.moderate || []} />
                    <GroupBlock title="Weak Evidence" entries={matrix.grouped_claims?.weak || []} toneClass="warn" />
                    <GroupBlock title="Unsupported Claims" entries={matrix.grouped_claims?.unsupported || []} toneClass="warn" />

                    {highRiskTopics.length > 0 ? (
                      <div className="analysis-meta-card warn">
                        <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>High-Risk Topics</p>
                        <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                          {highRiskTopics.map((item, index) => (
                            <li key={`risk-${index}-${item.claim_id || item.resume_claim}`} className="muted-copy" style={{ marginBottom: "0.3rem" }}>
                              {item.resume_claim}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </>
                ) : null}

                {!shouldOfferRewrite ? (
                  <div className="analysis-meta-card teal">
                    <p style={{ margin: 0 }}>
                      Interview readiness is healthy. Continue practicing weak interview topics before your real interview.
                    </p>
                  </div>
                ) : null}

                {shouldOfferRewrite && !rewrites ? (
                  <div className="analysis-meta-card warn">
                    <p style={{ margin: "0 0 0.6rem" }}>
                      Interview readiness is currently low. Choose one next action:
                    </p>
                    <div className="button-row" style={{ justifyContent: "flex-start" }}>
                      <button type="button" className="secondary-button" onClick={practiceAgain}>
                        Option 1: Practice weak topics
                      </button>
                      <button
                        type="button"
                        className="primary-button"
                        onClick={loadRewritesOnDemand}
                        disabled={rewriteLoading}
                      >
                        {rewriteLoading ? "Preparing rewrites..." : "Option 2: Rewrite related resume bullets"}
                      </button>
                    </div>
                    {rewriteError ? (
                      <p className="muted-copy" style={{ margin: "0.6rem 0 0", color: "#ef4444" }}>
                        {rewriteError}
                      </p>
                    ) : null}
                  </div>
                ) : null}

                {rewrites ? (
                  <>
                    <div className="analysis-meta-card">
                      <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>Optional Resume Improvement</p>
                      <p style={{ margin: 0 }}>
                        These suggestions are optional and grounded in your interview evidence.
                      </p>
                    </div>
                    <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                      <RewriteSummaryStat label="Targeted Claims" value={rewrites.summary?.targeted_claims ?? 0} />
                      <RewriteSummaryStat label="Rewritten" value={rewrites.summary?.rewritten_claims ?? 0} tone="teal" />
                      <RewriteSummaryStat
                        label="Insufficient Evidence"
                        value={rewrites.summary?.insufficient_evidence_claims ?? 0}
                        tone="warn"
                      />
                      <RewriteSummaryStat label="Moderate" value={rewrites.summary?.moderate_claims ?? 0} />
                      <RewriteSummaryStat label="Weak" value={rewrites.summary?.weak_claims ?? 0} tone="warn" />
                    </div>

                    {(rewrites.entries || []).length > 0 ? (
                      <div className="stack">
                        {rewrites.entries.map((entry) => (
                          <RewriteEntryCard key={`${entry.claim_id}-${entry.question_id}`} entry={entry} />
                        ))}
                      </div>
                    ) : (
                      <div className="analysis-meta-card teal">
                        <p style={{ margin: 0 }}>
                          No rewrite actions are required. Your evaluated claims are already strongly defended.
                        </p>
                      </div>
                    )}
                  </>
                ) : null}
              </div>
            ) : null}

            <div className="button-row" style={{ justifyContent: "flex-start" }}>
              <button
                type="button"
                className="primary-button"
                onClick={exportPdf}
                disabled={exporting || loading || rewriteLoading || (contextEvidenceEnabled && (!matrix || interviewEvidenceLoading))}
              >
                {loading || (contextEvidenceEnabled && interviewEvidenceLoading) ? "Generating Interview Report..." : exporting ? "Preparing Download..." : "Download Report (PDF)"}
              </button>
              <button type="button" className="secondary-button" onClick={practiceAgain}>
                Practice Again
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </StepWrapper>
  );
}
