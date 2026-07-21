import { useMemo, useState } from "react";
import ModelSelect from "../../ModelSelect";
import StepWrapper from "../StepWrapper";
import {
  postJson,
  startContextEvidenceSession,
} from "../../../api/client";
import useCanvasStore from "../../../store/useCanvasStore";
import { trackCanvasEvent } from "../../../utils/canvasAnalytics";

const INTERVIEW_STYLES = [
  { value: "mixed", label: "Mixed (Default)", hint: "Balanced technical, behavioral, and problem-solving coverage." },
  { value: "technical", label: "Technical", hint: "Emphasis on systems, implementation details, and tools." },
  { value: "behavioral", label: "Behavioral", hint: "STAR stories, collaboration, and communication depth." },
  { value: "executive", label: "Executive / Leadership", hint: "Leadership decisions, scope, and strategic outcomes." },
  { value: "case", label: "Case Study", hint: "Structured problem-solving under constraints." },
];

const DIFFICULTIES = [
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "senior", label: "Senior" },
  { value: "expert", label: "Expert" },
];

const QUESTION_OPTIONS = [5, 10, 15, 20, "custom"];

const FOCUS_AREAS = [
  "Resume Projects",
  "Technical Skills",
  "Behavioral",
  "Leadership",
  "Communication",
  "Problem Solving",
  "Career History",
  "Achievements",
  "System Design",
];

const TIME_LIMIT_OPTIONS = [
  { value: "", label: "No Limit" },
  { value: "10", label: "10 Minutes" },
  { value: "20", label: "20 Minutes" },
  { value: "30", label: "30 Minutes" },
  { value: "45", label: "45 Minutes" },
];

function stripHtml(html = "") {
  return String(html || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function toBackendDifficulty(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "beginner") return "entry";
  if (normalized === "intermediate") return "mid";
  if (normalized === "senior") return "senior";
  if (normalized === "expert") return "lead";
  return "mid";
}

function buildAnalysisContext(results) {
  if (!results || typeof results !== "object") {
    return "";
  }

  const priorityOrder = [
    "Application_Strategy",
    "Resume_Optimization",
    "ATS_Optimization",
    "Job_Match_Score",
    "ATS_Report",
  ];

  const orderedEntries = [
    ...priorityOrder
      .filter((key) => results[key])
      .map((key) => [key, results[key]]),
    ...Object.entries(results).filter(([key]) => !priorityOrder.includes(key)),
  ];

  const chunks = [];
  for (const [key, payload] of orderedEntries) {
    const raw = payload?.result_text || stripHtml(payload?.result_html || "");
    if (!raw) {
      continue;
    }
    chunks.push(`[${String(key).replaceAll("_", " ")}] ${raw}`);
    if (chunks.length >= 3) {
      break;
    }
  }

  return chunks.join("\n\n").slice(0, 28000);
}

function extractAtsMissingKeywords(results) {
  if (!results || typeof results !== "object") {
    return [];
  }

  const candidates = [
    results?.ATS_Optimization?.keywords?.missing,
    results?.ATS_Optimization?.missing_keywords,
    results?.ATS_Report?.keywords?.missing,
    results?.Job_Match_Score?.missing_keywords,
    results?.Job_Match_Score?.keyword_gaps,
  ];

  const out = [];
  for (const item of candidates) {
    if (!Array.isArray(item)) {
      continue;
    }
    for (const keyword of item) {
      if (typeof keyword === "string" && keyword.trim()) {
        out.push(keyword.trim());
      }
    }
  }

  return [...new Set(out)].slice(0, 25);
}

function extractAtsScore(results) {
  if (!results || typeof results !== "object") {
    return null;
  }

  const candidates = [
    results?.ATS_Optimization?.score,
    results?.ATS_Optimization?.ats_score,
    results?.ATS_Report?.score,
    results?.ATS_Report?.ats_score,
  ];

  for (const value of candidates) {
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }

  return null;
}

const NAME_STOP_WORDS = new Set([
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
  "linkedin",
  "github",
  "portfolio",
]);

function formatCandidateName(value = "") {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) {
    return "";
  }

  const alpha = text.replace(/[^A-Za-z ]/g, "").trim();
  if (alpha && alpha === alpha.toUpperCase()) {
    return alpha
      .toLowerCase()
      .replace(/\b([a-z])/g, (char) => char.toUpperCase());
  }

  return text;
}

function looksLikeCandidateName(value = "") {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text || text.length < 3 || text.length > 60) {
    return false;
  }
  if (/@/.test(text) || /\d/.test(text) || /https?:\/\//i.test(text)) {
    return false;
  }

  const words = text.split(" ").filter(Boolean);
  if (words.length < 2 || words.length > 4) {
    return false;
  }

  if (words.some((word) => NAME_STOP_WORDS.has(word.toLowerCase()))) {
    return false;
  }

  return words.every((word) => /^[A-Za-z][A-Za-z'.-]*$/.test(word));
}

function extractResumeCandidateName(resumeText = "") {
  const lines = String(resumeText || "")
    .split(/\r?\n/)
    .map((line) => line.replace(/^\uFEFF/, "").trim())
    .filter(Boolean)
    .slice(0, 60);

  for (const rawLine of lines) {
    const line = rawLine.replace(/^[\-•*]+\s*/, "").trim();
    if (!line) {
      continue;
    }

    const chunks = line
      .split(/[|•·,–—]/)
      .map((part) => part.trim())
      .filter(Boolean);

    const candidates = chunks.length > 0 ? chunks : [line];

    for (const candidate of candidates) {
      const stripped = candidate.replace(/^name\s*:\s*/i, "").trim();
      const tokens = stripped.split(/\s+/).filter(Boolean);

      if (looksLikeCandidateName(stripped)) {
        return formatCandidateName(stripped);
      }

      for (let size = Math.min(4, tokens.length); size >= 2; size -= 1) {
        const head = tokens.slice(0, size).join(" ");
        if (looksLikeCandidateName(head)) {
          return formatCandidateName(head);
        }
      }
    }
  }

  return "";
}

function extractStructuredCandidateName(results) {
  if (!results || typeof results !== "object") {
    return "";
  }

  const nameKeys = new Set(["candidate_name", "full_name", "name", "resume_name", "applicant_name", "person_name"]);
  const queue = [results];
  const visited = new Set();

  while (queue.length > 0) {
    const node = queue.shift();
    if (!node || typeof node !== "object" || visited.has(node)) {
      continue;
    }
    visited.add(node);

    for (const [key, value] of Object.entries(node)) {
      const normalizedKey = String(key || "").toLowerCase();

      if (typeof value === "string") {
        if ((nameKeys.has(normalizedKey) || normalizedKey.endsWith("_name")) && looksLikeCandidateName(value)) {
          return formatCandidateName(value);
        }
      } else if (value && typeof value === "object") {
        queue.push(value);
      }
    }
  }

  return "";
}

function extractCandidatePronouns(text = "") {
  const match = String(text || "").match(/\b(she\/?her|he\/?him|they\/?them)\b/i);
  if (!match) {
    return "";
  }

  return match[1]
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace("sheher", "she/her")
    .replace("hehim", "he/him")
    .replace("theythem", "they/them");
}

function resolveCandidateIdentityForInterview(resumeText, generatedResults) {
  const parsedName = extractResumeCandidateName(resumeText);
  const structuredName = extractStructuredCandidateName(generatedResults);
  const pronouns = extractCandidatePronouns(resumeText);

  const name = parsedName || structuredName || "";
  return {
    name,
    pronouns,
    displayName: pronouns && name ? `${name} (${pronouns})` : name,
    source: parsedName ? "parsed_resume_name" : structuredName ? "structured_resume_metadata" : "unknown",
  };
}

function buildInterviewContextText({ jdText, targetRole, styleLabel, difficultyLabel, focusAreas, timeLimitLabel, questionCount }) {
  const blocks = [
    (jdText || "").trim(),
    targetRole ? `Target role: ${targetRole}` : "",
    focusAreas.length > 0 ? `Focus areas: ${focusAreas.join(", ")}` : "",
    `Preferred interview style: ${styleLabel}`,
    `Difficulty level: ${difficultyLabel}`,
    questionCount ? `Planned questions: ${questionCount}` : "",
    timeLimitLabel ? `Session time limit: ${timeLimitLabel}` : "",
  ].filter(Boolean);

  return blocks.join("\n\n").trim();
}

function guessCategoryFromClaim(claim, style, focusAreas) {
  const claimType = String(claim?.claim_type || "").toLowerCase();
  const claimText = String(claim?.claim_text || "").toLowerCase();
  const focus = focusAreas.map((item) => item.toLowerCase());

  if (style === "behavioral") {
    return claimType === "ownership" ? "leadership" : "behavioral";
  }
  if (style === "executive") {
    return "leadership";
  }
  if (style === "case") {
    return "problem";
  }

  if (focus.includes("leadership") || claimType === "ownership") {
    return "leadership";
  }
  if (
    focus.includes("behavioral") ||
    focus.includes("communication") ||
    /collaborat|stakeholder|mentor|lead|team|conflict/.test(claimText)
  ) {
    return "behavioral";
  }
  if (focus.includes("problem solving") || /optimi|trade[- ]off|debug|resolve|incident/.test(claimText)) {
    return "problem";
  }
  if (focus.includes("resume projects") || focus.includes("achievements") || claimType === "impact") {
    return "project";
  }
  return "technical";
}

function inferPriorityLabel(priorityNumber, jobAlignment, claimType) {
  const priority = Number(priorityNumber || 0);
  const alignment = String(jobAlignment || "").toLowerCase();
  const type = String(claimType || "").toLowerCase();

  if (priority >= 4 || alignment === "high") {
    return "High";
  }
  if (priority >= 3 || type === "impact" || type === "ownership") {
    return "Medium";
  }
  return "Low";
}

function shouldIgnoreClaim(claim, focusAreas) {
  const source = String(claim?.source || "").toLowerCase();
  const text = String(claim?.claim_text || "").trim();
  const focus = focusAreas.map((item) => item.toLowerCase());

  if (!text) {
    return true;
  }

  const isLikelyHeader = text.length < 18 || /^(education|experience|skills|summary)$/i.test(text);
  if (isLikelyHeader) {
    return true;
  }

  if (source.includes("education") && !focus.includes("career history")) {
    return true;
  }

  return false;
}

function buildFollowUpAreas(claim, category) {
  const keywords = Array.isArray(claim?.matched_job_keywords) ? claim.matched_job_keywords : [];
  const atsGaps = Array.isArray(claim?.related_ats_weaknesses) ? claim.related_ats_weaknesses : [];
  const out = [];

  for (const item of keywords.slice(0, 2)) {
    out.push(`Depth on ${item}`);
  }
  for (const item of atsGaps.slice(0, 2)) {
    out.push(`Evidence for ${item}`);
  }

  if (category === "technical") {
    out.push("Architecture trade-offs", "Scalability and reliability", "Testing and quality controls");
  } else if (category === "project") {
    out.push("Business impact and measurable outcomes", "Execution challenges", "Cross-functional collaboration");
  } else if (category === "behavioral") {
    out.push("Stakeholder management", "Conflict resolution", "Communication under pressure");
  } else if (category === "leadership") {
    out.push("Decision ownership", "Coaching and delegation", "Prioritization strategy");
  } else if (category === "problem") {
    out.push("Root-cause analysis", "Decision framework", "Risk mitigation");
  }

  return [...new Set(out)].slice(0, 5);
}

function buildInterviewBlueprint({ claims, style, focusAreas, targetRole, jdText, resolvedQuestionCount }) {
  const filtered = [];

  for (const claim of claims || []) {
    if (shouldIgnoreClaim(claim, focusAreas)) {
      continue;
    }

    const matchCount = Array.isArray(claim?.matched_job_keywords) ? claim.matched_job_keywords.length : 0;
    const hasAtsGap = Array.isArray(claim?.related_ats_weaknesses) && claim.related_ats_weaknesses.length > 0;
    const priority = Number(claim?.priority || 0);

    if (priority < 2 && matchCount === 0 && !hasAtsGap) {
      continue;
    }

    filtered.push(claim);
  }

  const ranked = [...filtered].sort((a, b) => {
    const scoreA = Number(a?.priority || 0) * 3 + (a?.matched_job_keywords?.length || 0) * 2 + (a?.related_ats_weaknesses?.length || 0);
    const scoreB = Number(b?.priority || 0) * 3 + (b?.matched_job_keywords?.length || 0) * 2 + (b?.related_ats_weaknesses?.length || 0);
    return scoreB - scoreA;
  });

  const cap = Math.max(resolvedQuestionCount * 2, 10);
  const selectedClaims = ranked.slice(0, cap);

  const topics = selectedClaims.map((claim, index) => {
    const category = guessCategoryFromClaim(claim, style, focusAreas);
    const priority = inferPriorityLabel(claim?.priority, claim?.job_alignment, claim?.claim_type);
    const matchedKeywords = Array.isArray(claim?.matched_job_keywords) ? claim.matched_job_keywords : [];
    const matchingRequirement = matchedKeywords.length
      ? `JD alignment: ${matchedKeywords.join(", ")}`
      : targetRole
        ? `Role alignment for ${targetRole}`
        : (jdText || "").trim()
          ? "General alignment to the target job requirements"
          : "Validate real experience and measurable outcomes";

    return {
      id: `bp_${String(index + 1).padStart(2, "0")}`,
      claim_id: claim.claim_id,
      topic: claim.claim_text,
      category,
      priority,
      why_it_matters:
        category === "technical"
          ? "This topic verifies implementation depth, architecture choices, and technical reasoning."
          : category === "project"
            ? "This topic validates measurable project impact and execution ownership."
            : category === "leadership"
              ? "This topic tests leadership decisions, influence, and accountability."
              : category === "behavioral"
                ? "This topic assesses collaboration, communication, and situational judgment."
                : "This topic checks structured problem solving and trade-off decisions.",
      matching_jd_requirement: matchingRequirement,
      suggested_follow_up_areas: buildFollowUpAreas(claim, category),
      expected_keywords: [...new Set([...(matchedKeywords || []), ...(claim?.related_ats_weaknesses || [])])].slice(0, 8),
    };
  });

  return {
    generated_at: new Date().toISOString(),
    target_role: targetRole || "",
    style,
    focus_areas: focusAreas,
    total_topics: topics.length,
    topics,
  };
}

function buildCategorySlots(totalQuestions, style, focusAreas) {
  const count = Math.max(1, Math.floor(Number(totalQuestions) || 10));
  if (count === 1) {
    return ["intro"];
  }
  if (count === 2) {
    return ["intro", "closing"];
  }

  const weights = {
    technical: 3,
    project: 2,
    behavioral: 2,
    problem: 2,
    leadership: 1,
  };

  if (style === "technical") {
    weights.technical += 4;
    weights.project += 2;
    weights.problem += 2;
  } else if (style === "behavioral") {
    weights.behavioral += 5;
    weights.leadership += 2;
  } else if (style === "executive") {
    weights.leadership += 5;
    weights.behavioral += 2;
    weights.problem += 1;
  } else if (style === "case") {
    weights.problem += 5;
    weights.technical += 2;
  }

  const focus = focusAreas.map((item) => item.toLowerCase());
  if (focus.includes("resume projects")) weights.project += 3;
  if (focus.includes("technical skills")) weights.technical += 2;
  if (focus.includes("system design")) {
    weights.technical += 2;
    weights.problem += 1;
  }
  if (focus.includes("behavioral")) weights.behavioral += 2;
  if (focus.includes("leadership")) weights.leadership += 3;
  if (focus.includes("communication")) weights.behavioral += 2;
  if (focus.includes("problem solving")) weights.problem += 3;
  if (focus.includes("career history")) {
    weights.behavioral += 1;
    weights.leadership += 1;
  }
  if (focus.includes("achievements")) {
    weights.project += 2;
    weights.technical += 1;
  }

  const middleCount = count - 2;
  const used = {
    technical: 0,
    project: 0,
    behavioral: 0,
    problem: 0,
    leadership: 0,
  };

  const middleSlots = [];
  for (let i = 0; i < middleCount; i += 1) {
    let best = "technical";
    let bestScore = -1;

    for (const key of Object.keys(weights)) {
      const score = weights[key] / (used[key] + 1);
      if (score > bestScore) {
        bestScore = score;
        best = key;
      }
    }

    middleSlots.push(best);
    used[best] += 1;
  }

  return ["intro", ...middleSlots, "closing"];
}

function buildBlueprintSummaryText(blueprint) {
  const lines = [];
  for (const topic of blueprint?.topics || []) {
    lines.push(
      `- [${topic.priority}] ${topic.category}: ${topic.topic} | Why: ${topic.why_it_matters} | JD: ${topic.matching_jd_requirement}`
    );
  }
  return lines.join("\n").slice(0, 5000);
}

function mapSlotToQuestionType(slot, style) {
  if (slot === "technical") return "technical";
  if (slot === "project") return "mixed";
  if (slot === "behavioral") return "behavioral";
  if (slot === "leadership") return style === "executive" ? "executive" : "behavioral";
  if (slot === "problem") return style === "case" ? "case" : "technical";
  return style || "mixed";
}

function createIntroQuestion(style) {
  return {
    id: "q_intro_1",
    context_evidence_question_id: null,
    question: "Tell me about yourself.",
    type: style || "mixed",
    category: "Introduction",
    expected_keywords: [],
    is_intro: true,
    follow_up_areas: ["Career trajectory", "Recent high-impact work", "Role alignment"],
  };
}

function createClosingQuestion(style) {
  return {
    id: "q_closing_1",
    context_evidence_question_id: null,
    question: "What kind of role are you targeting next, and why are you the right fit for it?",
    type: style || "mixed",
    category: "Closing",
    expected_keywords: [],
    is_closing: true,
    follow_up_areas: ["Motivation", "Role fit", "Growth priorities"],
  };
}

function createQuestionFromBlueprint(topic, slot, sequenceIndex, style, contextEvidenceQuestion) {
  if (contextEvidenceQuestion?.question) {
    return {
      id: `q_ctx_${sequenceIndex}`,
      context_evidence_question_id: contextEvidenceQuestion.question_id || null,
      question: contextEvidenceQuestion.question,
      type: mapSlotToQuestionType(slot, style),
      category: topic.category,
      expected_keywords: topic.expected_keywords || [],
      blueprint_topic: topic.topic,
      blueprint_priority: topic.priority,
      follow_up_areas: topic.suggested_follow_up_areas || [],
    };
  }

  let questionText = `Can you walk me through ${topic.topic}?`;
  if (slot === "technical") {
    questionText = `For ${topic.topic}, what architecture or implementation approach did you choose, and why?`;
  } else if (slot === "project") {
    questionText = `For ${topic.topic}, what were the business goals, your actions, and measurable outcomes?`;
  } else if (slot === "leadership") {
    questionText = `In ${topic.topic}, what leadership decisions did you personally own and what changed because of them?`;
  } else if (slot === "behavioral") {
    questionText = `Describe a challenging situation around ${topic.topic} and how you handled communication and collaboration.`;
  } else if (slot === "problem") {
    questionText = `In ${topic.topic}, what trade-offs did you evaluate and how did you decide under constraints?`;
  }

  return {
    id: `q_ctx_${sequenceIndex}`,
    context_evidence_question_id: null,
    question: questionText,
    type: mapSlotToQuestionType(slot, style),
    category: topic.category,
    expected_keywords: topic.expected_keywords || [],
    blueprint_topic: topic.topic,
    blueprint_priority: topic.priority,
    follow_up_areas: topic.suggested_follow_up_areas || [],
  };
}

function pickBlueprintTopicForSlot(topics, slot, usedTopicIds) {
  const priorities = { High: 3, Medium: 2, Low: 1 };

  const candidates = (topics || []).filter((item) => item.category === slot && !usedTopicIds.has(item.id));
  const sorted = [...candidates].sort(
    (a, b) => (priorities[b.priority] || 0) - (priorities[a.priority] || 0)
  );

  if (sorted.length > 0) {
    return sorted[0];
  }

  const backup = (topics || []).find((item) => !usedTopicIds.has(item.id));
  return backup || null;
}

function normalizeLegacyQuestion(rawQuestion, index, style) {
  const questionText = String(rawQuestion?.question || rawQuestion?.prompt || "").trim();
  if (!questionText) {
    return null;
  }

  return {
    id: String(rawQuestion?.id || `q_extra_${index + 1}`),
    context_evidence_question_id: null,
    question: questionText,
    type: String(rawQuestion?.type || style || "mixed").toLowerCase(),
    category: String(rawQuestion?.category || "contextual"),
    expected_keywords: Array.isArray(rawQuestion?.expected_keywords)
      ? rawQuestion.expected_keywords.slice(0, 8)
      : [],
  };
}

export default function StepInterviewSetup({ onComplete, onBack }) {
  const cvText = useCanvasStore((state) => state.cvText);
  const jdText = useCanvasStore((state) => state.jdText);
  const setJD = useCanvasStore((state) => state.setJD);
  const selectedModel = useCanvasStore((state) => state.selectedModel);
  const setSelectedModel = useCanvasStore((state) => state.setSelectedModel);
  const setInterviewConfig = useCanvasStore((state) => state.setInterviewConfig);
  const setInterviewQuestions = useCanvasStore((state) => state.setInterviewQuestions);
  const setContextEvidenceSession = useCanvasStore((state) => state.setContextEvidenceSession);
  const clearContextEvidence = useCanvasStore((state) => state.clearContextEvidence);
  const generatedResults = useCanvasStore((state) => state.generatedResults);

  const [targetRole, setTargetRole] = useState("");
  const [style, setStyle] = useState("mixed");
  const [difficulty, setDifficulty] = useState("intermediate");
  const [questionChoice, setQuestionChoice] = useState("10");
  const [customQuestions, setCustomQuestions] = useState("");
  const [focusAreas, setFocusAreas] = useState([]);
  const [timeLimitChoice, setTimeLimitChoice] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("");
  const [error, setError] = useState("");

  const hasCV = Boolean((cvText || "").trim());

  const styleLabel = useMemo(
    () => INTERVIEW_STYLES.find((item) => item.value === style)?.label || "Mixed (Default)",
    [style]
  );

  const difficultyLabel = useMemo(
    () => DIFFICULTIES.find((item) => item.value === difficulty)?.label || "Intermediate",
    [difficulty]
  );

  const resolvedQuestionCount = useMemo(() => {
    if (questionChoice === "custom") {
      const parsed = Number(customQuestions);
      if (!Number.isFinite(parsed)) {
        return 0;
      }
      return Math.max(1, Math.min(40, Math.floor(parsed)));
    }
    const parsed = Number(questionChoice);
    return Number.isFinite(parsed) ? parsed : 10;
  }, [questionChoice, customQuestions]);

  const timeLimitMinutes = useMemo(() => {
    const parsed = Number(timeLimitChoice);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [timeLimitChoice]);

  const timeLimitLabel = useMemo(
    () => TIME_LIMIT_OPTIONS.find((item) => item.value === timeLimitChoice)?.label || "No Limit",
    [timeLimitChoice]
  );

  function toggleFocusArea(area) {
    setFocusAreas((current) =>
      current.includes(area) ? current.filter((item) => item !== area) : [...current, area]
    );
  }

  async function fetchSupplementalQuestions({
    neededCount,
    styleValue,
    backendDifficulty,
    contextText,
    blueprintText,
    existingQuestionText,
  }) {
    const collected = [];
    let attempts = 0;

    while (collected.length < neededCount && attempts < 4) {
      attempts += 1;
      const requestCount = Math.max(3, Math.min(10, neededCount - collected.length + 2));

      const fallback = await postJson("/interview/generate-questions", {
        cv_text: cvText,
        job_description: `${contextText}\n\nInterview Blueprint (internal planning context):\n${blueprintText}`.slice(0, 7800),
        style: styleValue,
        difficulty: backendDifficulty,
        num_questions: requestCount,
        model: selectedModel || "",
      });

      const normalized = (fallback?.questions || [])
        .map((question, index) => normalizeLegacyQuestion(question, index + attempts * 100, styleValue))
        .filter(Boolean);

      for (const item of normalized) {
        if (collected.length >= neededCount) {
          break;
        }
        const key = item.question.toLowerCase();
        if (existingQuestionText.has(key)) {
          continue;
        }
        existingQuestionText.add(key);
        collected.push(item);
      }
    }

    return collected;
  }

  async function handleStart() {
    setError("");

    if (!hasCV) {
      setError("No resume context found. Go back and upload your resume first.");
      return;
    }

    if (!resolvedQuestionCount || resolvedQuestionCount < 1) {
      setError("Please select a valid number of questions.");
      return;
    }

    setLoading(true);
    setLoadingMessage("Planning interview strategy...");

    const contextualRequirement = buildInterviewContextText({
      jdText,
      targetRole: targetRole.trim(),
      styleLabel,
      difficultyLabel,
      focusAreas,
      timeLimitLabel,
      questionCount: resolvedQuestionCount,
    });

    const interviewQuestions = [];
    const usedTopicIds = new Set();
    let contextEvidenceQuestionCount = 0;
    let supplementalQuestionCount = 0;
    let contextEvidenceEnabled = false;

    try {
      clearContextEvidence();

      setLoadingMessage("Analyzing resume and job context...");
      const contextEvidenceSession = await startContextEvidenceSession({
        resume_text: cvText,
        job_description: contextualRequirement,
        analysis_output: buildAnalysisContext(generatedResults),
        ats_missing_keywords: extractAtsMissingKeywords(generatedResults),
        ats_score: extractAtsScore(generatedResults),
        model: selectedModel || "",
      });

      setContextEvidenceSession(contextEvidenceSession);
      contextEvidenceEnabled = Boolean(contextEvidenceSession?.session_id);

      setLoadingMessage("Building internal interview blueprint...");
      const blueprint = buildInterviewBlueprint({
        claims: contextEvidenceSession?.claims || [],
        style,
        focusAreas,
        targetRole: targetRole.trim(),
        jdText,
        resolvedQuestionCount,
      });

      const blueprintText = buildBlueprintSummaryText(blueprint);
      const slotPlan = buildCategorySlots(resolvedQuestionCount, style, focusAreas);

      const contextEvidenceQuestionMap = new Map(
        (contextEvidenceSession?.questions || []).map((question) => [question.claim_id, question])
      );

      interviewQuestions.push(createIntroQuestion(style));

      let sequenceIndex = 2;
      for (const slot of slotPlan.slice(1, -1)) {
        if (interviewQuestions.length >= Math.max(1, resolvedQuestionCount - 1)) {
          break;
        }

        const topic = pickBlueprintTopicForSlot(blueprint.topics, slot, usedTopicIds);
        if (!topic) {
          continue;
        }

        usedTopicIds.add(topic.id);

        const contextEvidenceQuestion = contextEvidenceQuestionMap.get(topic.claim_id) || null;
        const question = createQuestionFromBlueprint(topic, slot, sequenceIndex, style, contextEvidenceQuestion);

        if (question) {
          interviewQuestions.push(question);
          if (question.context_evidence_question_id) {
            contextEvidenceQuestionCount += 1;
          }
          sequenceIndex += 1;
        }
      }

      if (interviewQuestions.length < resolvedQuestionCount) {
        const existingQuestionText = new Set(
          interviewQuestions.map((item) => String(item.question || "").toLowerCase())
        );

        setLoadingMessage("Generating contextual interview questions...");
        const supplemental = await fetchSupplementalQuestions({
          neededCount: Math.max(0, resolvedQuestionCount - interviewQuestions.length - 1),
          styleValue: style,
          backendDifficulty: toBackendDifficulty(difficulty),
          contextText: contextualRequirement,
          blueprintText,
          existingQuestionText,
        });

        for (const item of supplemental) {
          if (interviewQuestions.length >= Math.max(1, resolvedQuestionCount - 1)) {
            break;
          }

          interviewQuestions.push({
            ...item,
            id: `q_extra_${interviewQuestions.length + 1}`,
            type: item.type || mapSlotToQuestionType("technical", style),
            category: item.category || "Contextual",
            blueprint_topic: "Supplemental contextual probe",
            blueprint_priority: "Medium",
            follow_up_areas: [],
          });
          supplementalQuestionCount += 1;
        }
      }

      if (resolvedQuestionCount > 1) {
        interviewQuestions.push(createClosingQuestion(style));
      }

      const finalQuestions = interviewQuestions.slice(0, resolvedQuestionCount).map((item, index) => ({
        ...item,
        id: String(item.id || `q_${index + 1}`),
      }));

      if (!finalQuestions.length) {
        throw new Error("No interview questions were generated. Please try again.");
      }

      const candidateIdentity = resolveCandidateIdentityForInterview(cvText, generatedResults);
      const interviewCandidateIdentity = candidateIdentity?.name
        ? candidateIdentity
        : { name: "Candidate", pronouns: "", displayName: "Candidate", source: "fallback_unknown" };

      setInterviewConfig({
        mode: "context_aware_mock_interview",
        targetRole: targetRole.trim(),
        style,
        styleLabel,
        candidateIdentity: interviewCandidateIdentity,
        difficulty,
        difficultyBackend: toBackendDifficulty(difficulty),
        difficultyLabel,
        numQuestions: resolvedQuestionCount,
        focusAreas,
        timeLimitMinutes,
        strategyText:
          "Interview Planning has personalized this interview using your resume and target job description. Questions focus on the experiences and skills most relevant to your target role.",
        contextEvidenceEnabled,
        contextEvidenceQuestionCount,
        supplementalQuestionCount,
        planning: {
          created_at: new Date().toISOString(),
          slots: slotPlan,
          blueprint,
        },
        startedAt: Date.now(),
      });

      setInterviewQuestions(finalQuestions);
      onComplete?.();
    } catch (err) {
      const message = err?.message || "Could not prepare your context-aware interview. Please retry.";
      setError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: "interview",
        step_name: "interviewSetup",
        error_type: "context_interview_setup_failed",
        message,
      });
    } finally {
      setLoading(false);
      setLoadingMessage("");
    }
  }

  return (
    <StepWrapper
      title="Context-Aware Mock Interview"
      description="A personalized interview generated from your resume and target job description."
      onBack={onBack}
      maxWidth="920px"
    >
      <div className="stack">
        {!hasCV ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>
              No resume loaded yet. Go back one step and upload your resume first.
            </p>
          </div>
        ) : null}

        <label className="stack tight">
          <span className="eyebrow">Target Role</span>
          <input
            className="input-modern"
            value={targetRole}
            onChange={(event) => setTargetRole(event.target.value)}
            placeholder="e.g., Senior Data Analyst"
          />
        </label>

        <label className="stack tight">
          <span className="eyebrow">Job Description (optional but recommended)</span>
          <textarea
            className="input-modern"
            rows={6}
            value={jdText || ""}
            onChange={(event) => setJD(event.target.value)}
            placeholder="Paste your target job description to personalize interview context..."
          />
        </label>

        <div className="stack tight">
          <span className="eyebrow">Interview Style</span>
          <div className="button-row" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
            {INTERVIEW_STYLES.map((item) => (
              <button
                key={item.value}
                type="button"
                className={item.value === style ? "primary-button compact-button" : "secondary-button compact-button"}
                onClick={() => setStyle(item.value)}
                title={item.hint}
                aria-pressed={item.value === style}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="button-row" style={{ justifyContent: "flex-start", flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="stack tight">
            <span className="eyebrow">Questions</span>
            <select
              className="input-modern"
              value={questionChoice}
              onChange={(event) => setQuestionChoice(event.target.value)}
              style={{ minWidth: "140px" }}
            >
              {QUESTION_OPTIONS.map((option) => (
                <option key={String(option)} value={String(option)}>
                  {option === "custom" ? "Custom" : option}
                </option>
              ))}
            </select>
          </label>

          {questionChoice === "custom" ? (
            <label className="stack tight">
              <span className="eyebrow">Custom count</span>
              <input
                className="input-modern"
                type="number"
                min={1}
                max={40}
                value={customQuestions}
                onChange={(event) => setCustomQuestions(event.target.value)}
                placeholder="Enter questions"
                style={{ minWidth: "130px" }}
              />
            </label>
          ) : null}

          <label className="stack tight">
            <span className="eyebrow">Difficulty</span>
            <select
              className="input-modern"
              value={difficulty}
              onChange={(event) => setDifficulty(event.target.value)}
              style={{ minWidth: "170px" }}
            >
              {DIFFICULTIES.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
          </label>

          <label className="stack tight">
            <span className="eyebrow">Time Limit</span>
            <select
              className="input-modern"
              value={timeLimitChoice}
              onChange={(event) => setTimeLimitChoice(event.target.value)}
              style={{ minWidth: "150px" }}
            >
              {TIME_LIMIT_OPTIONS.map((item) => (
                <option key={item.label} value={item.value}>{item.label}</option>
              ))}
            </select>
          </label>

          <ModelSelect value={selectedModel} onChange={setSelectedModel} disabled={loading} compact />
        </div>

        <div className="stack tight">
          <span className="eyebrow">Focus Areas</span>
          <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
            {FOCUS_AREAS.map((area) => {
              const checked = focusAreas.includes(area);
              return (
                <label key={area} className="analysis-meta-card" style={{ display: "flex", alignItems: "center", gap: "0.55rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleFocusArea(area)}
                    aria-label={area}
                  />
                  <span>{area}</span>
                </label>
              );
            })}
          </div>
        </div>

        <div className="analysis-meta-card">
          <p className="eyebrow" style={{ marginBottom: "0.5rem" }}>Interview Summary</p>
          <div className="stack tight">
            <p style={{ margin: 0 }}><strong>Context-Aware Mock Interview</strong></p>
            <p style={{ margin: 0 }}><strong>Role:</strong> {targetRole.trim() || "Not specified"}</p>
            <p style={{ margin: 0 }}><strong>Interview Style:</strong> {styleLabel}</p>
            <p style={{ margin: 0 }}><strong>Difficulty:</strong> {difficultyLabel}</p>
            <p style={{ margin: 0 }}><strong>Questions:</strong> {resolvedQuestionCount || 10}</p>
            <p style={{ margin: 0 }}>
              <strong>Focus:</strong> {focusAreas.length > 0 ? focusAreas.join(", ") : "General coverage"}
            </p>
            <p style={{ margin: 0 }}><strong>Time Limit:</strong> {timeLimitLabel}</p>
            <p className="muted-copy" style={{ margin: 0 }}>
              <strong>Strategy:</strong> This interview has been personalized using your resume and target job description. Questions will focus on the experiences and skills most relevant to the target role.
            </p>
          </div>
        </div>

        {error ? (
          <div className="analysis-meta-card warn">
            <p style={{ margin: 0 }}>{error}</p>
          </div>
        ) : null}

        {loading && loadingMessage ? (
          <p className="muted-copy" style={{ margin: 0 }}>{loadingMessage}</p>
        ) : null}

        <div className="button-row" style={{ justifyContent: "flex-start" }}>
          <button
            type="button"
            className="primary-button"
            onClick={handleStart}
            disabled={!hasCV || loading}
          >
            {loading ? "Preparing your interview..." : "Start Context-Aware Mock Interview"}
          </button>
        </div>
      </div>
    </StepWrapper>
  );
}
