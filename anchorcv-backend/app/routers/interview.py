"""
AI Interview Coach: personalized questions from the candidate's CV + JD,
Whisper transcription, per-answer evaluation, a teaching loop for weak
answers, and a final report.

All heavy text generation goes through the multi-provider routed client, so
the user's chosen model (GPT-4o or Claude) applies here too. Transcription
always uses OpenAI Whisper.
"""
import io
import json
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.deps.auth import require_active_access
from app.services.llm import get_routed_client, resolve_model

router = APIRouter(prefix="/interview", tags=["interview"])
logger = logging.getLogger(__name__)

MAX_CV_CHARS = 12000
MAX_JD_CHARS = 8000
VALID_STYLES = {"technical", "behavioral", "mixed", "executive", "case"}
VALID_DIFFICULTIES = {"entry", "mid", "senior", "lead"}


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text[:limit]


def _chat_json(model: str, system: str, user: str, temperature: float, max_tokens: int) -> dict:
    client = get_routed_client()
    response = client.chat.completions.create(
        model=resolve_model(model),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    raw = (response.choices[0].message.content or "{}").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def _score_clamp(value) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _dim_clamp(value) -> int:
    try:
        return max(1, min(10, int(round(float(value)))))
    except (TypeError, ValueError):
        return 1


# ── 1. Question generation ──────────────────────────────────────────────────

class GenerateQuestionsRequest(BaseModel):
    cv_text: str = Field(..., min_length=100)
    job_description: str = Field(default="")
    style: str = "mixed"
    difficulty: str = "mid"
    num_questions: int = Field(default=6, ge=3, le=10)
    model: str = ""


_QUESTION_SYSTEM = """You are an expert interviewer at a top organization. You generate \
personalized interview questions grounded in the candidate's ACTUAL CV — their real \
projects, roles, skills, and gaps. Questions are conversational, never robotic. \
You always return valid JSON only."""

_QUESTION_USER = """### CANDIDATE CV:
{cv_text}

### JOB DESCRIPTION (may be empty — if so, infer the target role from the CV):
{job_description}

### INTERVIEW STYLE: {style}
### DIFFICULTY LEVEL: {difficulty}

### INSTRUCTIONS:
1. Every question must reference something SPECIFIC from the CV (a project, role, skill, or claim).
2. Mix per the style: for "mixed" use 2-3 technical, 2-3 behavioral, 1-2 problem-solving; \
for other styles weight accordingly but keep at least one behavioral question.
3. Include at least 1 question probing a weakness or gap visible in the CV.
4. Match difficulty to the level: {difficulty}.
5. Keep each question under 60 words, conversational.

Return JSON:
{{
  "questions": [
    {{
      "id": 1,
      "type": "technical|behavioral|problem_solving",
      "category": "short topic label",
      "question": "...",
      "difficulty": "easy|medium|hard",
      "expected_keywords": ["...", "..."],
      "reason_for_asking": "one sentence"
    }}
  ]
}}
Generate exactly {num_questions} questions."""


@router.post("/generate-questions")
def generate_questions(
    payload: GenerateQuestionsRequest,
    user: dict = Depends(require_active_access),
):
    style = payload.style if payload.style in VALID_STYLES else "mixed"
    difficulty = payload.difficulty if payload.difficulty in VALID_DIFFICULTIES else "mid"

    try:
        data = _chat_json(
            payload.model,
            _QUESTION_SYSTEM,
            _QUESTION_USER.format(
                cv_text=_truncate(payload.cv_text, MAX_CV_CHARS),
                job_description=_truncate(payload.job_description, MAX_JD_CHARS) or "(none provided)",
                style=style,
                difficulty=difficulty,
                num_questions=payload.num_questions,
            ),
            temperature=0.7,
            max_tokens=3000,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Question generation returned an unexpected response. Try again.") from exc
    except Exception as exc:
        logger.exception("Interview question generation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Question generation is temporarily unavailable.") from exc

    questions = []
    for index, item in enumerate(data.get("questions") or []):
        if not isinstance(item, dict) or not str(item.get("question") or "").strip():
            continue
        questions.append({
            "id": index + 1,
            "type": str(item.get("type") or "mixed"),
            "category": str(item.get("category") or ""),
            "question": str(item.get("question")).strip(),
            "difficulty": str(item.get("difficulty") or "medium"),
            "expected_keywords": [str(k) for k in (item.get("expected_keywords") or [])][:8],
            "reason_for_asking": str(item.get("reason_for_asking") or ""),
        })

    if not questions:
        raise HTTPException(status_code=502, detail="No questions could be generated. Try again.")
    return {"questions": questions, "style": style, "difficulty": difficulty}


# ── 2. Whisper transcription ────────────────────────────────────────────────

@router.post("/transcribe")
async def transcribe_answer(
    audio: UploadFile = File(...),
    user: dict = Depends(require_active_access),
):
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Voice transcription is not configured. Type your answer instead.")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio recording.")
    if len(audio_bytes) > 24 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Recording too large. Keep answers under ~3 minutes.")

    filename = audio.filename or "answer.webm"
    try:
        client = OpenAI(api_key=settings.openai_api_key)
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, io.BytesIO(audio_bytes), audio.content_type or "audio/webm"),
        )
        text = (getattr(result, "text", "") or "").strip()
    except Exception as exc:
        logger.exception("Whisper transcription failed: %s", exc)
        raise HTTPException(status_code=502, detail="Transcription failed. You can type your answer instead.") from exc

    if not text:
        raise HTTPException(status_code=422, detail="No speech detected. Try again or type your answer.")
    return {"text": text}


# ── 3. Answer evaluation ────────────────────────────────────────────────────

class EvaluateRequest(BaseModel):
    question: str
    expected_keywords: list[str] = Field(default_factory=list)
    answer_text: str = Field(..., min_length=2)
    difficulty: str = "mid"
    model: str = ""


_EVAL_SYSTEM = """You are a senior interviewer scoring a candidate's answer, honestly but \
constructively. You never invent things the candidate did not say. You always return valid JSON only."""

_EVAL_USER = """### QUESTION:
{question}

### EXPECTED KEYWORDS/CONCEPTS (guidance, not a strict checklist):
{expected_keywords}

### CANDIDATE'S ANSWER (transcribed from voice — ignore transcription artifacts like \
missing punctuation; judge substance):
{answer_text}

### TARGET LEVEL: {difficulty}

Score 4 dimensions (1-10): relevance (directly addresses the question), completeness \
(covers the key aspects), clarity (structured, easy to follow), communication \
(confident, professional). overall_score = average of the four, scaled to 0-100.

Return JSON:
{{
  "scores": {{"relevance": n, "completeness": n, "clarity": n, "communication": n}},
  "overall_score": 0-100,
  "strengths": ["2-3 specific things done well, quoting their own words where possible"],
  "weaknesses": ["2-3 specific gaps"],
  "improved_answer": "A stronger 60-120 word version of THEIR answer, using only facts they mentioned",
  "verdict": "pass" | "needs_improvement" | "fail"
}}
Verdict rules: pass if overall_score >= 75, needs_improvement if 50-74, fail below 50."""


@router.post("/evaluate")
def evaluate_answer(
    payload: EvaluateRequest,
    user: dict = Depends(require_active_access),
):
    try:
        data = _chat_json(
            payload.model,
            _EVAL_SYSTEM,
            _EVAL_USER.format(
                question=_truncate(payload.question, 1000),
                expected_keywords=", ".join(payload.expected_keywords[:10]) or "(none)",
                answer_text=_truncate(payload.answer_text, 6000),
                difficulty=payload.difficulty,
            ),
            temperature=0.3,
            max_tokens=1200,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Evaluation returned an unexpected response. Try again.") from exc
    except Exception as exc:
        logger.exception("Interview evaluation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Evaluation is temporarily unavailable.") from exc

    scores = data.get("scores") or {}
    return {
        "scores": {
            "relevance": _dim_clamp(scores.get("relevance")),
            "completeness": _dim_clamp(scores.get("completeness")),
            "clarity": _dim_clamp(scores.get("clarity")),
            "communication": _dim_clamp(scores.get("communication")),
        },
        "overall_score": _score_clamp(data.get("overall_score")),
        "strengths": [str(s) for s in (data.get("strengths") or [])][:4],
        "weaknesses": [str(s) for s in (data.get("weaknesses") or [])][:4],
        "improved_answer": str(data.get("improved_answer") or ""),
        "verdict": data.get("verdict") if data.get("verdict") in ("pass", "needs_improvement", "fail") else "needs_improvement",
    }


# ── 4. Teaching moment ──────────────────────────────────────────────────────

class TeachRequest(BaseModel):
    question: str
    answer_text: str
    overall_score: int = 0
    weaknesses: list[str] = Field(default_factory=list)
    model: str = ""


_TEACH_SYSTEM = """You are a patient, supportive interview coach helping a candidate improve a \
weak answer. Warm but concrete — no empty cheerleading. You always return valid JSON only."""

_TEACH_USER = """### QUESTION:
{question}

### CANDIDATE'S ANSWER (scored {overall_score}/100):
{answer_text}

### EVALUATOR'S NOTED WEAKNESSES:
{weaknesses}

Create a teaching moment. Return JSON:
{{
  "validation": "one warm sentence acknowledging what worked",
  "gap_explanation": "1-2 sentences: the most important thing missing and WHY it matters to interviewers",
  "teaching_point": "the framework or technique to apply (e.g. STAR: Situation, Task, Action, Result), in 2-3 sentences",
  "improved_answer_example": "a 60-120 word model answer built ONLY from facts the candidate mentioned, with [add your specific detail] placeholders where needed",
  "encouragement": "one short energizing sentence inviting them to try again"
}}"""


@router.post("/teach")
def teaching_moment(
    payload: TeachRequest,
    user: dict = Depends(require_active_access),
):
    try:
        data = _chat_json(
            payload.model,
            _TEACH_SYSTEM,
            _TEACH_USER.format(
                question=_truncate(payload.question, 1000),
                answer_text=_truncate(payload.answer_text, 4000),
                overall_score=_score_clamp(payload.overall_score),
                weaknesses="\n".join(f"- {w}" for w in payload.weaknesses[:5]) or "(none noted)",
            ),
            temperature=0.5,
            max_tokens=900,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Coaching returned an unexpected response. Try again.") from exc
    except Exception as exc:
        logger.exception("Interview teaching failed: %s", exc)
        raise HTTPException(status_code=502, detail="Coaching is temporarily unavailable.") from exc

    return {
        "validation": str(data.get("validation") or ""),
        "gap_explanation": str(data.get("gap_explanation") or ""),
        "teaching_point": str(data.get("teaching_point") or ""),
        "improved_answer_example": str(data.get("improved_answer_example") or ""),
        "encouragement": str(data.get("encouragement") or ""),
    }


# ── 5. Final report ─────────────────────────────────────────────────────────

class QAPair(BaseModel):
    question: str
    type: str = "mixed"
    answer_text: str = ""
    overall_score: int = 0
    scores: dict = Field(default_factory=dict)
    attempts: int = 1


class ReportRequest(BaseModel):
    name: str = "Candidate"
    difficulty: str = "mid"
    qa_pairs: list[QAPair]
    model: str = ""


_REPORT_SYSTEM = """You are writing a professional, actionable interview feedback report. \
Honest, specific, encouraging. You always return valid JSON only."""

_REPORT_USER = """### CANDIDATE: {name}
### TARGET LEVEL: {difficulty}

### QUESTIONS & ANSWERS (with per-answer scores):
{qa_json}

### PRE-COMPUTED AGGREGATES:
{aggregates}

Return JSON:
{{
  "executive_summary": "one paragraph, specific to this candidate",
  "overall_score": 0-100,
  "category_scores": {{"technical": 0-100, "behavioral": 0-100, "communication": 0-100}},
  "strengths": ["3 specific strengths with evidence from their answers"],
  "weaknesses": ["3 specific weaknesses with evidence"],
  "recommendations": ["3 concrete practice actions"],
  "best_answer": {{"question": "...", "why": "one sentence"}},
  "worst_answer": {{"question": "...", "why": "one sentence"}},
  "comparison": "one sentence on how this compares to typical candidates at the {difficulty} level"
}}"""


@router.post("/report")
def generate_report(
    payload: ReportRequest,
    user: dict = Depends(require_active_access),
):
    if not payload.qa_pairs:
        raise HTTPException(status_code=400, detail="No answers to report on.")

    answered = [qa for qa in payload.qa_pairs if qa.answer_text.strip()]
    scores = [qa.overall_score for qa in answered] or [0]
    by_type: dict[str, list[int]] = {}
    comm_scores: list[int] = []
    for qa in answered:
        by_type.setdefault("technical" if qa.type == "technical" else "behavioral", []).append(qa.overall_score)
        comm = qa.scores.get("communication")
        if isinstance(comm, (int, float)):
            comm_scores.append(int(comm * 10))

    aggregates = {
        "answered": len(answered),
        "total_questions": len(payload.qa_pairs),
        "mean_score": round(sum(scores) / len(scores)),
        "technical_mean": round(sum(by_type.get("technical", [0])) / max(1, len(by_type.get("technical", [1])))),
        "behavioral_mean": round(sum(by_type.get("behavioral", [0])) / max(1, len(by_type.get("behavioral", [1])))),
        "communication_mean": round(sum(comm_scores) / len(comm_scores)) if comm_scores else None,
        "retries_used": sum(max(0, qa.attempts - 1) for qa in answered),
    }

    qa_json = json.dumps(
        [
            {
                "question": _truncate(qa.question, 400),
                "type": qa.type,
                "answer": _truncate(qa.answer_text, 1500),
                "score": qa.overall_score,
                "dimension_scores": qa.scores,
                "attempts": qa.attempts,
            }
            for qa in payload.qa_pairs
        ],
        ensure_ascii=False,
    )

    try:
        data = _chat_json(
            payload.model,
            _REPORT_SYSTEM,
            _REPORT_USER.format(
                name=_truncate(payload.name, 80) or "Candidate",
                difficulty=payload.difficulty,
                qa_json=qa_json,
                aggregates=json.dumps(aggregates),
            ),
            temperature=0.4,
            max_tokens=1800,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Report generation returned an unexpected response. Try again.") from exc
    except Exception as exc:
        logger.exception("Interview report failed: %s", exc)
        raise HTTPException(status_code=502, detail="Report generation is temporarily unavailable.") from exc

    cat = data.get("category_scores") or {}
    return {
        "executive_summary": str(data.get("executive_summary") or ""),
        "overall_score": _score_clamp(data.get("overall_score") or aggregates["mean_score"]),
        "category_scores": {
            "technical": _score_clamp(cat.get("technical")),
            "behavioral": _score_clamp(cat.get("behavioral")),
            "communication": _score_clamp(cat.get("communication")),
        },
        "strengths": [str(s) for s in (data.get("strengths") or [])][:5],
        "weaknesses": [str(s) for s in (data.get("weaknesses") or [])][:5],
        "recommendations": [str(s) for s in (data.get("recommendations") or [])][:5],
        "best_answer": data.get("best_answer") or {},
        "worst_answer": data.get("worst_answer") or {},
        "comparison": str(data.get("comparison") or ""),
        "aggregates": aggregates,
    }
