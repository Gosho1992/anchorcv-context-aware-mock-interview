import { useEffect, useMemo, useRef, useState } from "react";
import StepWrapper from "../StepWrapper";
import { postJson, postMultipart, submitContextEvidenceAnswer } from "../../../api/client";
import useCanvasStore from "../../../store/useCanvasStore";
import { trackCanvasEvent } from "../../../utils/canvasAnalytics";

const TEACH_THRESHOLD = 60;

function DimensionBar({ label, value }) {
  const numeric = Number.isFinite(Number(value)) ? Number(value) : 0;
  const pct = Math.max(0, Math.min(10, numeric)) * 10;
  const color = numeric >= 7 ? "var(--teal, #2dd4a8)" : numeric >= 5 ? "#f59e0b" : "#ef4444";

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem" }}>
        <span>{label}</span>
        <span style={{ color, fontWeight: 700 }}>{numeric}/10</span>
      </div>
      <div
        aria-hidden="true"
        style={{
          height: "6px",
          borderRadius: "3px",
          background: "var(--border)",
          overflow: "hidden",
          margin: "0.2rem 0 0.5rem",
        }}
      >
        <div style={{ width: `${pct}%`, height: "100%", background: color }} />
      </div>
    </div>
  );
}

function evidenceTone(strength = "") {
  const normalized = String(strength || "").toLowerCase();
  if (normalized === "strong") {
    return "teal";
  }
  if (normalized === "moderate") {
    return "";
  }
  return "warn";
}

function getQuestionTypeLabel(type = "") {
  const normalized = String(type || "").toLowerCase();
  if (normalized === "technical") return "Technical";
  if (normalized === "behavioral") return "Behavioral";
  if (normalized === "executive") return "Executive / Leadership";
  if (normalized === "case") return "Case Study";
  return "Mixed";
}

function formatClock(totalSeconds = 0) {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const minutes = String(Math.floor(safe / 60)).padStart(2, "0");
  const seconds = String(safe % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function toBackendDifficulty(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "beginner") return "entry";
  if (normalized === "intermediate") return "mid";
  if (normalized === "senior") return "senior";
  if (normalized === "expert") return "lead";
  return "mid";
}

function shouldProbeForClarification({ answerText, expectedKeywords, followUpCount }) {
  const text = String(answerText || "").trim();
  const words = text.split(/\s+/).filter(Boolean);
  const hasNumber = /\d/.test(text);
  const hasReasoning = /\b(because|therefore|trade[- ]off|decid|chose|constraint|impact|result)\b/i.test(text);

  let keywordMatches = 0;
  for (const keyword of expectedKeywords || []) {
    if (!keyword) continue;
    if (text.toLowerCase().includes(String(keyword).toLowerCase())) {
      keywordMatches += 1;
    }
  }

  if (followUpCount >= 2) {
    return { shouldProbe: false, reason: "enough_clarification" };
  }
  if (words.length < 18) {
    return { shouldProbe: true, reason: "too_short" };
  }
  if (!hasReasoning) {
    return { shouldProbe: true, reason: "missing_reasoning" };
  }
  if (!hasNumber && words.length < 40) {
    return { shouldProbe: true, reason: "missing_specifics" };
  }
  if ((expectedKeywords || []).length >= 2 && keywordMatches === 0) {
    return { shouldProbe: true, reason: "missing_expected_topics" };
  }

  return { shouldProbe: false, reason: "sufficient" };
}

function mapInterviewEvidenceState({ activeClarificationPrompt, interviewEvidenceEvaluation }) {
  if (activeClarificationPrompt) {
    return "Needs Clarification";
  }

  const strength = String(interviewEvidenceEvaluation?.evidence_strength || "").toLowerCase();
  if (strength === "strong") {
    return "Well Supported";
  }
  if (strength === "moderate") {
    return "Needs Clarification";
  }
  if (strength === "weak") {
    return "Needs More Evidence";
  }
  if (strength === "unsupported") {
    return "Unsupported";
  }
  return "Needs Clarification";
}

function buildAdaptiveFollowUpPrompt(question, followUpCount, reason) {
  const areas = Array.isArray(question?.follow_up_areas) ? question.follow_up_areas : [];
  if (areas[followUpCount]) {
    return `Can you go deeper on "${areas[followUpCount]}" with concrete details from your own work?`;
  }

  const type = String(question?.type || "mixed").toLowerCase();
  if (type === "technical") {
    if (reason === "missing_reasoning") return "Why did you choose that approach over alternatives, and what trade-offs did you evaluate?";
    if (reason === "missing_specifics") return "What specific architecture, tools, and implementation details can you share?";
    return "How did you validate quality, performance, or reliability in that implementation?";
  }
  if (type === "behavioral") {
    return "What was your exact role, what challenge did you face, and what was the measurable outcome?";
  }
  if (type === "executive") {
    return "How did your decision align with business priorities, and what outcomes did it drive?";
  }
  if (type === "case") {
    return "What decision framework did you use, and which trade-offs shaped your final recommendation?";
  }

  return "Can you add concrete details about what you did, why you did it, and the measurable result?";
}

function composeEvaluatedAnswer({ primaryAnswer, followUpPairs, latestAnswer, activeFollowUpPrompt }) {
  const blocks = [];
  const primary = String(primaryAnswer || "").trim();
  if (primary) {
    blocks.push(primary);
  }

  for (const item of followUpPairs || []) {
    if (item?.question && item?.answer) {
      blocks.push(`Follow-up: ${item.question}\nCandidate: ${item.answer}`);
    }
  }

  const latest = String(latestAnswer || "").trim();
  if (latest) {
    if (activeFollowUpPrompt) {
      blocks.push(`Follow-up: ${activeFollowUpPrompt}\nCandidate: ${latest}`);
    } else if (!primary) {
      blocks.push(latest);
    }
  }

  return blocks.join("\n\n").trim();
}

export default function StepInterviewSession({ onComplete, onBack }) {
  const questions = useCanvasStore((state) => state.interviewQuestions);
  const answers = useCanvasStore((state) => state.interviewAnswers);
  const config = useCanvasStore((state) => state.interviewConfig);
  const selectedModel = useCanvasStore((state) => state.selectedModel);
  const contextEvidenceSessionId = useCanvasStore((state) => state.contextEvidenceSessionId);
  const contextEvidenceEvaluations = useCanvasStore((state) => state.contextEvidenceEvaluations);

  const setInterviewAnswer = useCanvasStore((state) => state.setInterviewAnswer);
  const setContextEvidenceAnswer = useCanvasStore((state) => state.setContextEvidenceAnswer);
  const setContextEvidenceEvaluation = useCanvasStore((state) => state.setContextEvidenceEvaluation);

  const [index, setIndex] = useState(() => {
    const firstOpen = questions.findIndex((q) => !answers[q.id]?.evaluation);
    return firstOpen === -1 ? 0 : firstOpen;
  });
  const [answerText, setAnswerText] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [teaching, setTeaching] = useState(null);
  const [teachLoading, setTeachLoading] = useState(false);
  const [evaluation, setEvaluation] = useState(null);
  const [interviewEvidenceEvaluation, setInterviewEvidenceEvaluation] = useState(null);
  const [followUpPrompt, setFollowUpPrompt] = useState("");
  const [followUpPairs, setFollowUpPairs] = useState([]);
  const [primaryAnswer, setPrimaryAnswer] = useState("");
  const [clarificationNotice, setClarificationNotice] = useState("");
  const [attempts, setAttempts] = useState(1);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const [micError, setMicError] = useState("");
  const [sessionNow, setSessionNow] = useState(Date.now());

  const mediaRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);
  const timeLimitHandledRef = useRef(false);

  const question = questions[index];
  const total = questions.length;
  const answeredCount = questions.filter((q) => answers[q.id]?.evaluation).length;

  const timeLimitMinutes = useMemo(() => {
    const parsed = Number(config?.timeLimitMinutes);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [config?.timeLimitMinutes]);

  const startedAt = Number(config?.startedAt || 0);
  const deadlineMs = timeLimitMinutes && startedAt ? startedAt + timeLimitMinutes * 60 * 1000 : null;
  const remainingSeconds = deadlineMs ? Math.ceil((deadlineMs - sessionNow) / 1000) : null;
  const isTimeExpired = Number.isFinite(remainingSeconds) ? remainingSeconds <= 0 : false;

  useEffect(
    () => () => {
      clearInterval(timerRef.current);
      if (mediaRef.current?.state === "recording") {
        mediaRef.current.stop();
      }
      mediaRef.current?.stream?.getTracks?.().forEach((track) => track.stop());
    },
    []
  );

  useEffect(() => {
    if (!timeLimitMinutes || !deadlineMs) {
      return undefined;
    }

    const interval = setInterval(() => {
      setSessionNow(Date.now());
    }, 1000);

    return () => clearInterval(interval);
  }, [timeLimitMinutes, deadlineMs]);

  useEffect(() => {
    if (!question) {
      setAnswerText("");
      setEvaluation(null);
      setInterviewEvidenceEvaluation(null);
      setFollowUpPrompt("");
      setFollowUpPairs([]);
      setPrimaryAnswer("");
      setClarificationNotice("");
      setTeaching(null);
      setError("");
      setMicError("");
      setAttempts(1);
      setSeconds(0);
      return;
    }

    const saved = answers[question.id];
    setAnswerText(saved?.evaluation ? "" : saved?.draft_answer || saved?.answer_text || "");
    setEvaluation(saved?.evaluation || null);
    setFollowUpPrompt(saved?.pending_follow_up_prompt || "");
    setFollowUpPairs(Array.isArray(saved?.follow_up_pairs) ? saved.follow_up_pairs : []);
    setPrimaryAnswer(saved?.primary_answer || "");
    setClarificationNotice("");
    setTeaching(null);
    setError("");
    setMicError("");
    setSeconds(0);
    setAttempts(saved?.attempts || 1);

    const contextEvidenceQuestionId = question.context_evidence_question_id;
    if (contextEvidenceQuestionId) {
      setInterviewEvidenceEvaluation(contextEvidenceEvaluations[contextEvidenceQuestionId] || saved?.context_evidence_evaluation || null);
    } else {
      setInterviewEvidenceEvaluation(null);
    }
  }, [question?.id, answers, contextEvidenceEvaluations, question]);

  useEffect(() => {
    if (!isTimeExpired || timeLimitHandledRef.current) {
      return;
    }

    timeLimitHandledRef.current = true;
    if (mediaRef.current?.state === "recording") {
      mediaRef.current.stop();
    }
    onComplete?.();
  }, [isTimeExpired, onComplete]);

  async function startRecording() {
    setMicError("");
    setError("");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data?.size) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        clearInterval(timerRef.current);
        setRecording(false);

        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        if (!blob.size) {
          return;
        }

        setTranscribing(true);
        try {
          const formData = new FormData();
          formData.append("audio", new File([blob], "answer.webm", { type: blob.type }));
          const response = await postMultipart("/interview/transcribe", formData);
          const text = String(response?.text || "").trim();
          setAnswerText((current) => (current ? `${current} ${text}` : text));
        } catch (err) {
          setMicError(err?.message || "Transcription failed. Please type your answer below.");
          trackCanvasEvent("canvas_error_shown", {
            flow: "interview",
            step_name: "interviewSession",
            error_type: "transcription_failed",
            message: err?.message || "",
          });
        } finally {
          setTranscribing(false);
        }
      };

      mediaRef.current = recorder;
      recorder.start();
      setRecording(true);
      setSeconds(0);
      timerRef.current = setInterval(() => setSeconds((value) => value + 1), 1000);
    } catch {
      setMicError("Microphone unavailable or permission denied. Please type your answer.");
    }
  }

  function stopRecording() {
    if (mediaRef.current?.state === "recording") {
      mediaRef.current.stop();
    }
  }

  async function submitAnswer() {
    const text = answerText.trim();
    if (!text || !question || isTimeExpired) {
      if (isTimeExpired) {
        setError("Time limit reached. Interview completed.");
      }
      return;
    }

    setError("");
    setTeaching(null);
    setClarificationNotice("");

    const activeFollowUpPrompt = followUpPrompt || "";
    const nextPrimaryAnswer = primaryAnswer || text;
    const nextFollowUpPairs = activeFollowUpPrompt
      ? [...followUpPairs, { question: activeFollowUpPrompt, answer: text }]
      : [...followUpPairs];

    const probeDecision = shouldProbeForClarification({
      answerText: activeFollowUpPrompt ? text : nextPrimaryAnswer,
      expectedKeywords: question.expected_keywords || [],
      followUpCount: nextFollowUpPairs.length,
    });

    if (probeDecision.shouldProbe) {
      const nextPrompt = buildAdaptiveFollowUpPrompt(question, nextFollowUpPairs.length, probeDecision.reason);

      setPrimaryAnswer(nextPrimaryAnswer);
      setFollowUpPairs(nextFollowUpPairs);
      setFollowUpPrompt(nextPrompt);
      setClarificationNotice("Thanks. Before scoring, one clarification question:");
      setAnswerText("");

      setInterviewAnswer(question.id, {
        question_id: question.id,
        question_order: index + 1,
        question: question.question,
        type: question.type,
        draft_answer: "",
        answer_text: nextPrimaryAnswer,
        attempts,
        primary_answer: nextPrimaryAnswer,
        follow_up_pairs: nextFollowUpPairs,
        pending_follow_up_prompt: nextPrompt,
        evaluation: null,
        context_evidence_question_id: question.context_evidence_question_id || null,
      });
      return;
    }

    setEvaluating(true);

    const combinedAnswer = composeEvaluatedAnswer({
      primaryAnswer: nextPrimaryAnswer,
      followUpPairs: nextFollowUpPairs,
      latestAnswer: activeFollowUpPrompt ? "" : text,
      activeFollowUpPrompt,
    });

    try {
      const result = await postJson("/interview/evaluate", {
        question: question.question,
        expected_keywords: question.expected_keywords || [],
        answer_text: combinedAnswer,
        difficulty: config?.difficultyBackend || toBackendDifficulty(config?.difficulty),
        model: selectedModel || "",
      });

      setEvaluation(result);

      let contextEvidenceResult = null;
      if (contextEvidenceSessionId && question.context_evidence_question_id) {
        try {
          contextEvidenceResult = await submitContextEvidenceAnswer(contextEvidenceSessionId, {
            question_id: question.context_evidence_question_id,
            answer_text: combinedAnswer,
          });

          setContextEvidenceAnswer(question.context_evidence_question_id, combinedAnswer);
          setContextEvidenceEvaluation(contextEvidenceResult);
          setInterviewEvidenceEvaluation(contextEvidenceResult);
        } catch (contextEvidenceError) {
          setError(
            contextEvidenceError?.message ||
              "Answer scored, but context evidence evaluation failed for this claim. You can continue."
          );
          trackCanvasEvent("canvas_error_shown", {
            flow: "interview",
            step_name: "interviewSession",
            error_type: "context_evaluation_failed",
            message: contextEvidenceError?.message || "",
          });
        }
      }

      setFollowUpPrompt("");
      setClarificationNotice("");

      setInterviewAnswer(question.id, {
        question_id: question.id,
        question_order: index + 1,
        question: question.question,
        type: question.type,
        answer_text: combinedAnswer,
        overall_score: result.overall_score,
        scores: result.scores,
        evaluation: result,
        attempts,
        context_evidence_question_id: question.context_evidence_question_id || null,
        context_evidence_evaluation: contextEvidenceResult,
        primary_answer: nextPrimaryAnswer,
        follow_up_pairs: nextFollowUpPairs,
        pending_follow_up_prompt: "",
      });

      if (result.overall_score < TEACH_THRESHOLD) {
        setTeachLoading(true);
        try {
          const lesson = await postJson("/interview/teach", {
            question: question.question,
            answer_text: combinedAnswer,
            overall_score: result.overall_score,
            weaknesses: result.weaknesses || [],
            model: selectedModel || "",
          });
          setTeaching(lesson);
        } catch {
          // Coaching is an enhancement and should not block scoring feedback.
        } finally {
          setTeachLoading(false);
        }
      }
    } catch (err) {
      const message = err?.message || "Evaluation failed. Try submitting again.";
      setError(message);
      trackCanvasEvent("canvas_error_shown", {
        flow: "interview",
        step_name: "interviewSession",
        error_type: "evaluation_failed",
        message,
      });
    } finally {
      setEvaluating(false);
    }
  }

  function tryAgain() {
    setAttempts((value) => value + 1);
    setAnswerText("");
    setEvaluation(null);
    setInterviewEvidenceEvaluation(null);
    setFollowUpPrompt("");
    setFollowUpPairs([]);
    setPrimaryAnswer("");
    setClarificationNotice("");
    setTeaching(null);
    setSeconds(0);
  }

  function goNext() {
    if (index + 1 < total) {
      setIndex(index + 1);
      return;
    }
    onComplete?.();
  }

  if (!question) {
    return (
      <StepWrapper title="Interview" description="No questions found." onBack={onBack}>
        <div className="analysis-meta-card warn">
          <p style={{ margin: 0 }}>No questions in this session. Go back and start again.</p>
        </div>
      </StepWrapper>
    );
  }

  const isLast = index + 1 >= total;
  const activePrompt = followUpPrompt || question.question;
  const interviewEvidenceState = mapInterviewEvidenceState({
    activeClarificationPrompt: followUpPrompt,
    interviewEvidenceEvaluation,
  });
  const descriptionParts = [
    getQuestionTypeLabel(question.type),
    question.category || "Contextual",
    `${answeredCount}/${total} answered`,
  ];

  if (followUpPrompt) {
    descriptionParts.push(`Clarification ${followUpPairs.length + 1}`);
  }

  if (timeLimitMinutes) {
    descriptionParts.push(
      isTimeExpired ? "Time limit reached" : `Time left ${formatClock(remainingSeconds || 0)}`
    );
  }

  return (
    <StepWrapper
      title={`Question ${index + 1} of ${total}`}
      description={descriptionParts.join(" · ")}
      onBack={onBack}
      maxWidth="860px"
    >
      <div className="stack">
        <div
          aria-hidden="true"
          style={{ height: "6px", borderRadius: "3px", background: "var(--border)", overflow: "hidden" }}
        >
          <div
            style={{
              width: `${total > 0 ? (answeredCount / total) * 100 : 0}%`,
              height: "100%",
              background: "linear-gradient(90deg, var(--accent, #7c6ff7), var(--teal, #2dd4a8))",
              transition: "width .4s",
            }}
          />
        </div>

        {timeLimitMinutes ? (
          <div className={`analysis-meta-card ${isTimeExpired ? "warn" : ""}`.trim()}>
            <p style={{ margin: 0 }}>
              <strong>Session time:</strong>{" "}
              {isTimeExpired
                ? "Time limit reached. Finishing interview..."
                : `${formatClock(remainingSeconds || 0)} remaining`}
            </p>
          </div>
        ) : null}

        <div className="analysis-meta-card" style={{ fontSize: "1.05rem", lineHeight: 1.5 }}>
          <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>
            {followUpPrompt ? "Clarification Question" : "Interview Question"}
          </p>
          <p style={{ margin: 0 }}>{activePrompt}</p>
        </div>

        {primaryAnswer ? (
          <div className="analysis-meta-card">
            <p className="eyebrow" style={{ marginBottom: "0.35rem" }}>Current Evidence Thread</p>
            <p className="muted-copy" style={{ margin: "0 0 0.45rem" }}>
              <strong>Initial answer:</strong> {primaryAnswer}
            </p>
            {(followUpPairs || []).map((item, idx) => (
              <p key={`fup-thread-${idx}`} className="muted-copy" style={{ margin: "0 0 0.35rem" }}>
                <strong>Follow-up {idx + 1}:</strong> {item.question} <br />
                <strong>Your response:</strong> {item.answer}
              </p>
            ))}
          </div>
        ) : null}

        {followUpPrompt && !evaluation ? (
          <div className="analysis-meta-card">
            <p style={{ margin: 0 }}><strong>Interview Evidence Status:</strong> Needs Clarification</p>
          </div>
        ) : null}

        {!evaluation ? (
          <>
            <div className="button-row" style={{ justifyContent: "flex-start", alignItems: "center" }}>
              {!recording ? (
                <button
                  type="button"
                  className="primary-button"
                  onClick={startRecording}
                  disabled={transcribing || evaluating || isTimeExpired}
                >
                  {answerText ? "Record more" : "Answer with voice"}
                </button>
              ) : (
                <button type="button" className="secondary-button" onClick={stopRecording}>
                  Stop recording · {formatClock(seconds)}
                </button>
              )}
              {recording ? (
                <span
                  aria-live="polite"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.45rem",
                    color: "#ef4444",
                    fontWeight: 700,
                  }}
                >
                  <span
                    style={{
                      width: "10px",
                      height: "10px",
                      borderRadius: "50%",
                      background: "#ef4444",
                      animation: "pulse 1.2s infinite",
                    }}
                  />
                  Recording
                </span>
              ) : null}
              {transcribing ? <span className="muted-copy">Transcribing your answer...</span> : null}
            </div>

            {micError ? (
              <p className="muted-copy" style={{ margin: 0, color: "#f59e0b" }}>
                {micError}
              </p>
            ) : null}

            <label className="stack tight">
              <span className="eyebrow">
                {followUpPrompt ? "Your clarification response" : "Your answer (edit transcript or type directly)"}
              </span>
              <textarea
                className="input-modern"
                rows={7}
                value={answerText}
                onChange={(event) => setAnswerText(event.target.value)}
                placeholder={followUpPrompt
                  ? "Answer this follow-up with specific details..."
                  : "Speak using the button above, or type your answer here..."}
              />
            </label>

            {clarificationNotice ? (
              <div className="analysis-meta-card">
                <p style={{ margin: 0 }}>{clarificationNotice}</p>
              </div>
            ) : null}

            {error ? (
              <div className="analysis-meta-card warn">
                <p style={{ margin: 0 }}>{error}</p>
              </div>
            ) : null}

            <div className="button-row" style={{ justifyContent: "flex-start" }}>
              <button
                type="button"
                className="primary-button"
                onClick={submitAnswer}
                disabled={!answerText.trim() || evaluating || recording || transcribing || isTimeExpired}
              >
                {evaluating ? "Evaluating..." : followUpPrompt ? "Submit Clarification" : "Submit Answer"}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={goNext}
                disabled={evaluating || recording}
              >
                Skip question
              </button>
            </div>
          </>
        ) : (
          <div className="stack">
            <div
              className="analysis-meta-card"
              style={{ display: "flex", gap: "1.2rem", alignItems: "center", flexWrap: "wrap" }}
            >
              <div
                role="img"
                aria-label={`Score ${evaluation.overall_score} out of 100`}
                style={{
                  width: "76px",
                  height: "76px",
                  borderRadius: "50%",
                  display: "grid",
                  placeItems: "center",
                  fontSize: "1.35rem",
                  fontWeight: 800,
                  color: "#fff",
                  flexShrink: 0,
                  background:
                    evaluation.overall_score >= 75
                      ? "var(--teal, #2dd4a8)"
                      : evaluation.overall_score >= TEACH_THRESHOLD
                        ? "#f59e0b"
                        : "#ef4444",
                }}
              >
                {evaluation.overall_score}
              </div>
              <div style={{ flex: 1, minWidth: "220px" }}>
                <DimensionBar label="Relevance" value={evaluation.scores?.relevance} />
                <DimensionBar label="Completeness" value={evaluation.scores?.completeness} />
                <DimensionBar label="Clarity" value={evaluation.scores?.clarity} />
                <DimensionBar label="Communication" value={evaluation.scores?.communication} />
              </div>
            </div>

            <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
              <div className="analysis-meta-card teal">
                <p style={{ margin: "0 0 0.4rem", fontWeight: 700 }}>Strengths</p>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(evaluation.strengths || []).map((item, idx) => (
                    <li
                      key={`strength-${idx}-${item}`}
                      className="muted-copy"
                      style={{ marginBottom: "0.25rem" }}
                    >
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="analysis-meta-card warn">
                <p style={{ margin: "0 0 0.4rem", fontWeight: 700 }}>To improve</p>
                <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {(evaluation.weaknesses || []).map((item, idx) => (
                    <li
                      key={`weakness-${idx}-${item}`}
                      className="muted-copy"
                      style={{ marginBottom: "0.25rem" }}
                    >
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            {interviewEvidenceEvaluation ? (
              <div className={`analysis-meta-card ${evidenceTone(interviewEvidenceEvaluation.evidence_strength)}`}>
                <p style={{ margin: "0 0 0.45rem", fontWeight: 700 }}>
                  Interview Evidence Status: {interviewEvidenceState}
                </p>
                <p className="muted-copy" style={{ margin: "0 0 0.45rem" }}>
                  Confidence: {Math.round(Number(interviewEvidenceEvaluation.confidence || 0) * 100)}%
                </p>
                <p style={{ margin: "0 0 0.55rem" }}>{interviewEvidenceEvaluation.explanation}</p>

                {(interviewEvidenceEvaluation.missing_evidence || []).length > 0 ? (
                  <div style={{ marginBottom: "0.5rem" }}>
                    <p className="eyebrow" style={{ marginBottom: "0.3rem" }}>Missing Evidence</p>
                    <ul style={{ margin: 0, paddingLeft: "1.15rem" }}>
                      {interviewEvidenceEvaluation.missing_evidence.map((item, idx) => (
                        <li
                          key={`missing-${idx}-${item}`}
                          className="muted-copy"
                          style={{ marginBottom: "0.2rem" }}
                        >
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {interviewEvidenceEvaluation.suggested_follow_up_question ? (
                  <p style={{ margin: 0 }}>
                    <strong>Suggested follow-up:</strong> {interviewEvidenceEvaluation.suggested_follow_up_question}
                  </p>
                ) : null}
              </div>
            ) : null}

            {teachLoading ? (
              <p className="muted-copy" style={{ margin: 0 }}>
                Your coach is preparing a lesson...
              </p>
            ) : null}

            {teaching ? (
              <div className="analysis-meta-card" style={{ borderColor: "rgba(245,158,11,0.45)" }}>
                <p style={{ margin: "0 0 0.5rem", fontWeight: 700 }}>Coaching moment</p>
                <p className="muted-copy" style={{ margin: "0 0 0.5rem" }}>{teaching.validation}</p>
                <p className="muted-copy" style={{ margin: "0 0 0.5rem" }}>
                  <strong>The gap:</strong> {teaching.gap_explanation}
                </p>
                <p className="muted-copy" style={{ margin: "0 0 0.5rem" }}>
                  <strong>Technique:</strong> {teaching.teaching_point}
                </p>
                <p className="muted-copy" style={{ margin: "0 0 0.5rem", fontStyle: "italic" }}>
                  "{teaching.improved_answer_example}"
                </p>
                <p style={{ margin: 0, fontWeight: 600 }}>{teaching.encouragement}</p>
              </div>
            ) : evaluation.improved_answer ? (
              <details className="analysis-meta-card">
                <summary style={{ cursor: "pointer", fontWeight: 700 }}>
                  See a stronger version of your answer
                </summary>
                <p className="muted-copy" style={{ margin: "0.6rem 0 0", fontStyle: "italic" }}>
                  "{evaluation.improved_answer}"
                </p>
              </details>
            ) : null}

            <div className="button-row" style={{ justifyContent: "flex-start" }}>
              {evaluation.overall_score < TEACH_THRESHOLD ? (
                <button type="button" className="primary-button" onClick={tryAgain}>
                  Try Again (attempt {attempts + 1})
                </button>
              ) : null}
              <button
                type="button"
                className={evaluation.overall_score < TEACH_THRESHOLD ? "secondary-button" : "primary-button"}
                onClick={goNext}
              >
                {isLast ? "Finish -> See My Report" : "Next Question ->"}
              </button>
            </div>
          </div>
        )}
      </div>
    </StepWrapper>
  );
}
