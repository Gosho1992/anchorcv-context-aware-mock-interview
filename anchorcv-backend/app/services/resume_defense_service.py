import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from html import escape
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.resume_defense import (
    ResumeDefenseAnswerSubmitRequest,
    ResumeDefenseCareerReadinessSummary,
    ResumeDefenseClaim,
    ResumeDefenseEvaluationResult,
    ResumeDefenseIntegratedReportResponse,
    ResumeDefenseMatrixEntry,
    ResumeDefenseMatrixGroupedClaims,
    ResumeDefenseMatrixResponse,
    ResumeDefenseMatrixSummary,
    ResumeDefenseQuestion,
    ResumeDefenseReportingArtifact,
    ResumeDefenseRewriteEntry,
    ResumeDefenseRewriteResponse,
    ResumeDefenseRewriteSummary,
    ResumeDefenseSessionResponse,
    ResumeDefenseSignalSummary,
    ResumeDefenseStartRequest,
)
from app.services.ats_keywords import compare_keywords, extract_keywords_deterministic

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "discovery_cache.db"
MAX_CLAIMS = 12
EVIDENCE_CATEGORIES = ("Strong", "Moderate", "Weak", "Unsupported")
REWRITE_TARGET_STRENGTHS = {"Moderate", "Weak"}

_IMPACT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|k|m|b|x)?\b|\$\s*\d", re.IGNORECASE)
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")

_REWRITE_ACTION_VERBS = (
    "led",
    "managed",
    "built",
    "designed",
    "implemented",
    "owned",
    "delivered",
    "developed",
    "coordinated",
    "supported",
)

_CLAIM_VERBS = {
    "led",
    "managed",
    "built",
    "designed",
    "implemented",
    "delivered",
    "increased",
    "reduced",
    "optimized",
    "improved",
    "launched",
    "owned",
    "architected",
    "developed",
}

_GENERIC_ANSWER_PHRASES = {
    "i am not sure",
    "not sure",
    "hard to say",
    "i don't know",
    "cant remember",
    "cannot remember",
    "as mentioned",
    "same as resume",
}

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "were",
    "was",
    "have",
    "has",
    "had",
    "into",
    "over",
    "under",
    "your",
    "their",
    "they",
    "them",
    "ours",
    "our",
    "you",
    "about",
    "within",
    "across",
    "through",
    "during",
    "where",
    "when",
    "which",
    "while",
    "would",
    "could",
    "should",
    "also",
    "then",
    "than",
    "been",
    "being",
    "after",
    "before",
    "because",
    "there",
    "here",
}


class ResumeDefenseNotFoundError(ValueError):
    pass


class ResumeDefenseValidationError(ValueError):
    pass


def _get_db_path() -> Path:
    configured = (os.getenv("ANCHORCV_RESUME_DEFENSE_DB_PATH") or "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_DB_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_text(value: str) -> str:
    normalized = " ".join((value or "").lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@contextmanager
def _connect():
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_defense_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resume_hash TEXT NOT NULL,
            job_hash TEXT,
            model TEXT,
            resume_excerpt TEXT NOT NULL,
            analysis_excerpt TEXT,
            job_excerpt TEXT,
            ats_score REAL,
            signal_summary_json TEXT NOT NULL,
            claims_json TEXT NOT NULL,
            questions_json TEXT NOT NULL
        )
        """
    )
    _add_column_if_missing(conn, "resume_defense_sessions", "evaluations_json", "TEXT NOT NULL DEFAULT '[]'")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_defense_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            claim_text TEXT NOT NULL,
            claim_type TEXT NOT NULL,
            source TEXT NOT NULL,
            priority INTEGER NOT NULL,
            job_alignment TEXT NOT NULL,
            matched_job_keywords_json TEXT NOT NULL,
            related_ats_weaknesses_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES resume_defense_sessions(session_id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_defense_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            answer_text TEXT NOT NULL,
            evidence_strength TEXT NOT NULL,
            confidence REAL NOT NULL,
            explanation TEXT NOT NULL,
            missing_evidence_json TEXT NOT NULL,
            suggested_follow_up_question TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES resume_defense_sessions(session_id)
        )
        """
    )

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_resume_defense_eval_session_question ON resume_defense_evaluations (session_id, question_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_resume_defense_sessions_user_created ON resume_defense_sessions (user_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_resume_defense_claims_session ON resume_defense_claims (session_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_resume_defense_evals_session ON resume_defense_evaluations (session_id, updated_at DESC)"
    )


def _clean_line(value: str) -> str:
    line = _BULLET_PREFIX_RE.sub("", (value or "").strip())
    line = re.sub(r"\s+", " ", line)
    return line.strip(" -\u2022\t")


def _is_claim_candidate(line: str) -> bool:
    if not line:
        return False
    if len(line) < 28 or len(line) > 260:
        return False
    lower = line.lower()
    if _IMPACT_RE.search(line):
        return True
    return any(f" {verb} " in f" {lower} " for verb in _CLAIM_VERBS)


def _extract_from_analysis_output(analysis_output: str) -> list[str]:
    claims: list[str] = []
    for raw in (analysis_output or "").splitlines():
        line = _clean_line(raw)
        if _is_claim_candidate(line):
            claims.append(line)
    return claims


def _extract_from_resume_text(resume_text: str) -> list[str]:
    claims: list[str] = []
    for raw in (resume_text or "").splitlines():
        line = _clean_line(raw)
        if _is_claim_candidate(line):
            claims.append(line)
    return claims


def _dedupe_preserve_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = re.sub(r"[^a-z0-9]+", " ", line.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _classify_claim_type(text: str) -> str:
    lower = text.lower()
    if _IMPACT_RE.search(text):
        return "impact"
    if any(verb in lower for verb in ("led", "managed", "owned", "architect", "launched")):
        return "ownership"
    if any(verb in lower for verb in ("built", "implemented", "designed", "developed")):
        return "delivery"
    return "experience"


def _align_claim_to_job(claim_text: str, jd_keywords: list[str]) -> tuple[str, list[str]]:
    if not jd_keywords:
        return "not_applicable", []

    compared = compare_keywords(jd_keywords, claim_text)
    matched = compared.get("present", []) + compared.get("partial", [])
    score = float(compared.get("match_percentage", 0.0) or 0.0)

    if score >= 60:
        alignment = "aligned"
    elif score > 0:
        alignment = "partial"
    else:
        alignment = "weak"
    return alignment, matched


def _related_weaknesses(claim_text: str, ats_missing_keywords: list[str]) -> list[str]:
    if not ats_missing_keywords:
        return []

    lower = claim_text.lower()
    related: list[str] = []
    for keyword in ats_missing_keywords:
        key = (keyword or "").strip().lower()
        if not key:
            continue
        tokens = [token for token in re.split(r"\W+", key) if len(token) >= 4]
        if tokens and any(token in lower for token in tokens):
            related.append(keyword)
    return related


def _priority_for_claim(claim_type: str, alignment: str, related_ats: list[str]) -> int:
    priority = 2
    if claim_type == "impact":
        priority += 2
    elif claim_type in {"ownership", "delivery"}:
        priority += 1

    if alignment == "weak":
        priority += 1
    if related_ats:
        priority += 1

    return max(1, min(5, priority))


def _build_claims(
    resume_text: str,
    analysis_output: str,
    jd_keywords: list[str],
    ats_missing_keywords: list[str],
) -> list[ResumeDefenseClaim]:
    analysis_candidates = _extract_from_analysis_output(analysis_output)
    resume_candidates = _extract_from_resume_text(resume_text)
    ordered = _dedupe_preserve_order([*analysis_candidates, *resume_candidates])

    claims: list[ResumeDefenseClaim] = []
    for index, line in enumerate(ordered, start=1):
        claim_type = _classify_claim_type(line)
        alignment, matched = _align_claim_to_job(line, jd_keywords)
        related_ats = _related_weaknesses(line, ats_missing_keywords)
        priority = _priority_for_claim(claim_type, alignment, related_ats)

        claims.append(
            ResumeDefenseClaim(
                claim_id=f"clm_{index:02d}",
                claim_text=line,
                claim_type=claim_type,
                source="analysis_output" if line in analysis_candidates else "resume_text",
                priority=priority,
                job_alignment=alignment,
                matched_job_keywords=matched[:6],
                related_ats_weaknesses=related_ats[:4],
            )
        )

    claims.sort(key=lambda item: (item.priority, item.claim_type == "impact"), reverse=True)

    if not claims:
        fallback = _clean_line((resume_text or "").splitlines()[0] if resume_text else "")
        if fallback:
            claims.append(
                ResumeDefenseClaim(
                    claim_id="clm_01",
                    claim_text=fallback,
                    claim_type="experience",
                    source="resume_text",
                    priority=2,
                )
            )

    return claims[:MAX_CLAIMS]


def _make_question(claim: ResumeDefenseClaim, has_jd: bool) -> ResumeDefenseQuestion:
    base_prompt_map = {
        "impact": "You state this measurable impact on your resume: \"{claim}\". Walk me through the exact context, your direct contribution, and how the result was measured.",
        "ownership": "You claim ownership in this statement: \"{claim}\". What decisions were yours, what constraints existed, and what changed because of your actions?",
        "delivery": "You mention execution depth here: \"{claim}\". Describe the implementation details, key trade-offs, and what evidence proves successful delivery.",
        "experience": "Your resume states: \"{claim}\". Give a concrete interview-ready example that proves this claim with specific actions and outcomes.",
    }
    prompt = base_prompt_map.get(claim.claim_type, base_prompt_map["experience"]).format(claim=claim.claim_text)

    signals = ["resume_claim"]
    reasoning_parts = ["Tests whether the candidate can defend the resume claim with concrete evidence."]

    if has_jd:
        signals.append("job_requirement")
        if claim.job_alignment == "weak":
            prompt += " Also connect this example to the role's stated requirements."
            reasoning_parts.append("Claim has weak alignment with job requirements and needs direct role-mapping evidence.")
        elif claim.job_alignment == "partial":
            prompt += " Highlight how this example maps to the most relevant role requirement."
            reasoning_parts.append("Claim is partially aligned; question verifies depth of relevance.")

    if claim.related_ats_weaknesses:
        signals.append("ats_weakness")
        prompt += " Address the missing evidence area(s) explicitly in your response."
        reasoning_parts.append("Targets ATS weakness signals to close evidence gaps.")

    if claim.priority >= 4:
        signals.append("missing_evidence")
        reasoning_parts.append("High-priority claim needs stronger defensibility before interviews.")

    return ResumeDefenseQuestion(
        question_id=f"q_{claim.claim_id}",
        claim_id=claim.claim_id,
        question=prompt,
        reasoning=" ".join(reasoning_parts),
        source_signals=signals,
    )


def _build_questions(claims: list[ResumeDefenseClaim], has_jd: bool) -> list[ResumeDefenseQuestion]:
    return [_make_question(claim, has_jd=has_jd) for claim in claims]


def _excerpt(text: str, limit: int = 1200) -> str:
    value = " ".join((text or "").split())
    return value[:limit]


def _keywords(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9+#]{3,}", (text or "").lower())
    return {token for token in tokens if token not in _STOPWORDS}


def _is_generic_answer(answer_text: str) -> bool:
    answer = " ".join((answer_text or "").lower().split())
    if len(answer.split()) < 8:
        return True
    return any(phrase in answer for phrase in _GENERIC_ANSWER_PHRASES)


def _overlap_ratio(claim_text: str, answer_text: str) -> tuple[float, list[str]]:
    claim_tokens = _keywords(claim_text)
    if not claim_tokens:
        return 0.0, []

    answer_tokens = _keywords(answer_text)

    overlap: set[str] = set()
    for claim_token in claim_tokens:
        if claim_token in answer_tokens:
            overlap.add(claim_token)
            continue

        for answer_token in answer_tokens:
            if len(claim_token) < 4 or len(answer_token) < 4:
                continue
            if claim_token.startswith(answer_token) or answer_token.startswith(claim_token):
                overlap.add(claim_token)
                break

    overlap_list = sorted(overlap)
    ratio = len(overlap_list) / max(1, len(claim_tokens))
    return ratio, overlap_list[:6]


def _job_keyword_hits(answer_text: str, job_keywords: list[str]) -> list[str]:
    if not job_keywords:
        return []
    answer_lower = (answer_text or "").lower()
    hits: list[str] = []
    for keyword in job_keywords:
        value = (keyword or "").strip().lower()
        if not value:
            continue
        if value in answer_lower:
            hits.append(keyword)
            continue
        tokens = [token for token in re.split(r"\W+", value) if len(token) >= 4]
        if tokens and any(token in answer_lower for token in tokens):
            hits.append(keyword)
    return hits[:6]


def _ownership_signal_count(answer_text: str) -> int:
    markers = {
        " i ",
        " my ",
        " i led ",
        " i built ",
        " i designed ",
        " i implemented ",
        " i owned ",
        " i managed ",
        " i delivered ",
    }
    normalized = f" {(answer_text or '').lower()} "
    return sum(1 for marker in markers if marker in normalized)


def _pick_strength(
    overlap_ratio: float,
    metric_needed: bool,
    metric_present: bool,
    job_keywords: list[str],
    job_hits: list[str],
    ownership_signals: int,
    answer_text: str,
) -> tuple[str, float]:
    if not answer_text.strip() or _is_generic_answer(answer_text):
        return "Unsupported", 0.9

    job_required = bool(job_keywords)

    if overlap_ratio >= 0.45 and (not metric_needed or metric_present) and (not job_required or bool(job_hits)):
        return "Strong", 0.86

    if overlap_ratio >= 0.25 and (metric_present or ownership_signals > 0 or bool(job_hits)):
        return "Moderate", 0.74

    if overlap_ratio > 0.08 or bool(job_hits):
        return "Weak", 0.68

    return "Unsupported", 0.85


def _missing_evidence(
    claim: ResumeDefenseClaim,
    metric_needed: bool,
    metric_present: bool,
    overlap_ratio: float,
    job_keywords: list[str],
    job_hits: list[str],
    ownership_signals: int,
    answer_text: str,
) -> list[str]:
    missing: list[str] = []
    if len((answer_text or "").split()) < 25:
        missing.append("More specific execution detail (scope, tools, timeline, constraints).")
    if overlap_ratio < 0.25:
        missing.append("Concrete context that directly maps to the original resume claim.")
    if metric_needed and not metric_present:
        missing.append("Quantified outcome evidence (baseline, metric, and measured result).")
    if ownership_signals == 0:
        missing.append("Clear first-person ownership of decisions and actions.")
    if job_keywords and not job_hits:
        preview = ", ".join(job_keywords[:3])
        missing.append(f"Direct mapping to job requirements (e.g., {preview}).")
    if claim.related_ats_weaknesses:
        preview = ", ".join(claim.related_ats_weaknesses[:2])
        missing.append(f"Evidence for known ATS gap areas ({preview}).")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in missing:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped[:5]


def _follow_up_question(claim: ResumeDefenseClaim, missing_evidence: list[str], job_keywords: list[str]) -> str:
    if not missing_evidence:
        return f"Can you share one deeper example that further validates this claim: \"{claim.claim_text}\"?"

    first = missing_evidence[0].lower()
    if "quantified" in first:
        return "What exact metric changed for this claim, what was the baseline, and what final result did you personally deliver?"
    if "ownership" in first:
        return "Which specific decisions were yours for this claim, and how did those decisions change the outcome?"
    if "job requirements" in first and job_keywords:
        keyword = job_keywords[0]
        return f"Can you give one concrete example showing how this claim demonstrates {keyword} in practice?"
    if "ats gap" in first and claim.related_ats_weaknesses:
        keyword = claim.related_ats_weaknesses[0]
        return f"Can you provide a specific example that proves your strength in {keyword}?"
    return f"Can you provide one concrete, interview-ready example that directly supports this claim: \"{claim.claim_text}\"?"


def _explanation(
    strength: str,
    claim: ResumeDefenseClaim,
    overlap_ratio: float,
    overlap_tokens: list[str],
    metric_needed: bool,
    metric_present: bool,
    job_hits: list[str],
) -> str:
    overlap_pct = int(round(overlap_ratio * 100))
    overlap_text = ", ".join(overlap_tokens) if overlap_tokens else "no direct claim language"

    metric_sentence = ""
    if metric_needed:
        metric_sentence = (
            "The answer includes measurable outcome detail. "
            if metric_present
            else "The answer does not include measurable outcome detail for a quantified claim. "
        )

    job_sentence = ""
    if job_hits:
        job_sentence = f"It also references job-relevant requirements ({', '.join(job_hits[:3])}). "
    elif claim.job_alignment in {"weak", "partial", "aligned"}:
        job_sentence = "It does not clearly connect the example to the selected job requirements. "

    if strength == "Strong":
        prefix = "This claim is well defended. "
    elif strength == "Moderate":
        prefix = "This claim is partially defended but still needs stronger proof. "
    elif strength == "Weak":
        prefix = "This claim is weakly defended. "
    else:
        prefix = "This claim is currently unsupported by the answer. "

    return (
        f"{prefix}The response overlaps with key claim concepts at about {overlap_pct}% ({overlap_text}). "
        f"{metric_sentence}{job_sentence}".strip()
    )


def _build_evaluation(
    session_id: str,
    claim: ResumeDefenseClaim,
    question: ResumeDefenseQuestion,
    answer_text: str,
    signal_summary: ResumeDefenseSignalSummary,
) -> ResumeDefenseEvaluationResult:
    trimmed_answer = (answer_text or "").strip()
    overlap_ratio, overlap_tokens = _overlap_ratio(claim.claim_text, trimmed_answer)

    metric_needed = claim.claim_type == "impact" or _IMPACT_RE.search(claim.claim_text) is not None
    metric_present = _IMPACT_RE.search(trimmed_answer) is not None

    job_keywords = claim.matched_job_keywords or signal_summary.jd_keywords[:6]
    job_hits = _job_keyword_hits(trimmed_answer, job_keywords)
    ownership_signals = _ownership_signal_count(trimmed_answer)

    strength, confidence = _pick_strength(
        overlap_ratio=overlap_ratio,
        metric_needed=metric_needed,
        metric_present=metric_present,
        job_keywords=job_keywords,
        job_hits=job_hits,
        ownership_signals=ownership_signals,
        answer_text=trimmed_answer,
    )

    if strength not in EVIDENCE_CATEGORIES:
        strength = "Unsupported"

    missing = _missing_evidence(
        claim=claim,
        metric_needed=metric_needed,
        metric_present=metric_present,
        overlap_ratio=overlap_ratio,
        job_keywords=job_keywords,
        job_hits=job_hits,
        ownership_signals=ownership_signals,
        answer_text=trimmed_answer,
    )
    follow_up = _follow_up_question(claim, missing, job_keywords)
    explanation = _explanation(
        strength,
        claim,
        overlap_ratio,
        overlap_tokens,
        metric_needed,
        metric_present,
        job_hits,
    )
    now = _now_iso()

    return ResumeDefenseEvaluationResult(
        evaluation_id=f"ev_{session_id}_{question.question_id}",
        session_id=session_id,
        claim_id=claim.claim_id,
        question_id=question.question_id,
        resume_claim=claim.claim_text,
        interview_question=question.question,
        evidence_strength=strength,
        confidence=confidence,
        explanation=explanation,
        missing_evidence=missing,
        suggested_follow_up_question=follow_up,
        answer_excerpt=_excerpt(trimmed_answer, limit=500),
        evaluated_at=now,
    )


def _session_row(conn: sqlite3.Connection, user_id: str, session_id: str):
    return conn.execute(
        "SELECT * FROM resume_defense_sessions WHERE session_id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()


def _load_evaluations(conn: sqlite3.Connection, session_id: str) -> list[ResumeDefenseEvaluationResult]:
    rows = conn.execute(
        "SELECT * FROM resume_defense_evaluations WHERE session_id = ? ORDER BY updated_at ASC",
        (session_id,),
    ).fetchall()

    evaluations: list[ResumeDefenseEvaluationResult] = []
    for row in rows:
        missing = json.loads(row["missing_evidence_json"] or "[]")
        evaluations.append(
            ResumeDefenseEvaluationResult(
                evaluation_id=f"ev_{session_id}_{row['question_id']}",
                session_id=session_id,
                claim_id=row["claim_id"],
                question_id=row["question_id"],
                resume_claim="",
                interview_question="",
                evidence_strength=row["evidence_strength"],
                confidence=float(row["confidence"]),
                explanation=row["explanation"],
                missing_evidence=[str(item) for item in missing],
                suggested_follow_up_question=row["suggested_follow_up_question"],
                answer_excerpt=_excerpt(row["answer_text"], 500),
                evaluated_at=row["updated_at"],
            )
        )
    return evaluations


def _load_evaluation_rows(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM resume_defense_evaluations WHERE session_id = ? ORDER BY updated_at ASC",
        (session_id,),
    ).fetchall()


def _normalize_strength(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned == "strong":
        return "Strong"
    if cleaned == "moderate":
        return "Moderate"
    if cleaned == "weak":
        return "Weak"
    return "Unsupported"


def _related_job_requirement_text(claim: ResumeDefenseClaim, signal_summary: ResumeDefenseSignalSummary) -> str | None:
    if claim.matched_job_keywords:
        return ", ".join(claim.matched_job_keywords[:3])
    if signal_summary.jd_keywords:
        return signal_summary.jd_keywords[0]
    return None


def _recommendation_for_matrix_entry(strength: str, missing_evidence: list[str]) -> str:
    if strength == "Strong":
        return "Claim is interview-ready; keep this wording and prepare one deeper backup example."
    if strength == "Moderate":
        if missing_evidence:
            return f"Strengthen this claim with: {missing_evidence[0]}"
        return "Add more concrete context, ownership, and outcome proof before interviews."
    if strength == "Weak":
        if missing_evidence:
            return f"Before interviews, gather specific evidence for: {missing_evidence[0]}"
        return "This claim needs clearer proof before relying on it in interviews."
    return "Do not rely on this claim yet; collect verifiable evidence or soften/remove the wording."


def _build_matrix_narrative(
    strong_entries: list[ResumeDefenseMatrixEntry],
    moderate_entries: list[ResumeDefenseMatrixEntry],
    weak_entries: list[ResumeDefenseMatrixEntry],
    unsupported_entries: list[ResumeDefenseMatrixEntry],
) -> str:
    total = len(strong_entries) + len(moderate_entries) + len(weak_entries) + len(unsupported_entries)
    if total == 0:
        return "No claim answers have been evaluated yet. Submit answers to generate a Resume Defense Matrix."

    defended = [*strong_entries, *moderate_entries]
    challenged = [*weak_entries, *unsupported_entries]

    if defended:
        defended_examples = "; ".join(_excerpt(item.resume_claim, 100) for item in defended[:2])
        defended_sentence = f"Well-defended areas include: {defended_examples}."
    else:
        defended_sentence = "No claims are currently well defended."

    if challenged:
        challenged_examples = "; ".join(_excerpt(item.resume_claim, 100) for item in challenged[:2])
        challenged_sentence = f"Claims likely to be challenged include: {challenged_examples}."
    else:
        challenged_sentence = "No claims are currently in weak or unsupported status."

    prep_items: list[str] = []
    for item in challenged:
        for missing in item.missing_evidence:
            if missing not in prep_items:
                prep_items.append(missing)
            if len(prep_items) >= 3:
                break
        if len(prep_items) >= 3:
            break

    if prep_items:
        prep_sentence = f"Preparation should focus on: {'; '.join(prep_items)}"
    else:
        prep_sentence = "Continue preparing concise, evidence-rich examples for each high-priority claim."

    return f"{defended_sentence} {challenged_sentence} {prep_sentence}"


def _session_response_from_row(conn: sqlite3.Connection, row) -> ResumeDefenseSessionResponse:
    claims = [ResumeDefenseClaim.model_validate(item) for item in json.loads(row["claims_json"] or "[]")]
    questions = [
        ResumeDefenseQuestion.model_validate(item)
        for item in json.loads(row["questions_json"] or "[]")
    ]
    signal_summary = ResumeDefenseSignalSummary.model_validate(
        json.loads(row["signal_summary_json"] or "{}")
    )

    claim_map = {claim.claim_id: claim for claim in claims}
    question_map = {question.question_id: question for question in questions}

    evaluations = _load_evaluations(conn, row["session_id"])
    hydrated: list[ResumeDefenseEvaluationResult] = []
    for evaluation in evaluations:
        claim = claim_map.get(evaluation.claim_id)
        question = question_map.get(evaluation.question_id)
        hydrated.append(
            evaluation.model_copy(
                update={
                    "resume_claim": claim.claim_text if claim else "",
                    "interview_question": question.question if question else "",
                }
            )
        )

    return ResumeDefenseSessionResponse(
        session_id=row["session_id"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        resume_hash=row["resume_hash"],
        job_hash=row["job_hash"],
        claims=claims,
        questions=questions,
        evaluations=hydrated,
        signal_summary=signal_summary,
    )


def start_phase1_session(user_id: str, payload: ResumeDefenseStartRequest) -> ResumeDefenseSessionResponse:
    resume_text = (payload.resume_text or "").strip()
    analysis_output = (payload.analysis_output or "").strip()
    job_description = (payload.job_description or "").strip()
    ats_missing_keywords = [str(item).strip() for item in (payload.ats_missing_keywords or []) if str(item).strip()]

    jd_keywords = extract_keywords_deterministic(job_description) if job_description else []
    claims = _build_claims(
        resume_text=resume_text,
        analysis_output=analysis_output,
        jd_keywords=jd_keywords,
        ats_missing_keywords=ats_missing_keywords,
    )
    questions = _build_questions(claims, has_jd=bool(job_description))

    session_id = f"rd_{uuid.uuid4().hex}"
    now = _now_iso()
    resume_hash = _hash_text(resume_text)
    job_hash = _hash_text(job_description) if job_description else None

    signal_summary = ResumeDefenseSignalSummary(
        jd_keywords=jd_keywords[:25],
        ats_missing_keywords=ats_missing_keywords[:25],
    )

    with _connect() as conn:
        _init_db(conn)
        conn.execute(
            """
            INSERT INTO resume_defense_sessions (
                session_id, user_id, status, created_at, updated_at,
                resume_hash, job_hash, model,
                resume_excerpt, analysis_excerpt, job_excerpt, ats_score,
                signal_summary_json, claims_json, questions_json, evaluations_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                "initiated",
                now,
                now,
                resume_hash,
                job_hash,
                (payload.model or "").strip(),
                _excerpt(resume_text),
                _excerpt(analysis_output),
                _excerpt(job_description),
                payload.ats_score,
                json.dumps(signal_summary.model_dump(), ensure_ascii=False),
                json.dumps([claim.model_dump() for claim in claims], ensure_ascii=False),
                json.dumps([question.model_dump() for question in questions], ensure_ascii=False),
                "[]",
            ),
        )

        for claim in claims:
            conn.execute(
                """
                INSERT INTO resume_defense_claims (
                    session_id, claim_id, claim_text, claim_type, source,
                    priority, job_alignment, matched_job_keywords_json,
                    related_ats_weaknesses_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    claim.claim_id,
                    claim.claim_text,
                    claim.claim_type,
                    claim.source,
                    claim.priority,
                    claim.job_alignment,
                    json.dumps(claim.matched_job_keywords, ensure_ascii=False),
                    json.dumps(claim.related_ats_weaknesses, ensure_ascii=False),
                    now,
                ),
            )

        row = _session_row(conn, user_id, session_id)

    if not row:
        raise ResumeDefenseNotFoundError("Resume Defense session was not created.")

    with _connect() as conn:
        _init_db(conn)
        row = _session_row(conn, user_id, session_id)
        return _session_response_from_row(conn, row)


def get_phase1_session(user_id: str, session_id: str) -> ResumeDefenseSessionResponse | None:
    with _connect() as conn:
        _init_db(conn)
        row = _session_row(conn, user_id, session_id)
        if not row:
            return None
        return _session_response_from_row(conn, row)


def submit_phase2_answer(
    user_id: str,
    session_id: str,
    payload: ResumeDefenseAnswerSubmitRequest,
) -> ResumeDefenseEvaluationResult:
    with _connect() as conn:
        _init_db(conn)
        row = _session_row(conn, user_id, session_id)
        if not row:
            raise ResumeDefenseNotFoundError("Resume Defense session not found.")

        claims = [ResumeDefenseClaim.model_validate(item) for item in json.loads(row["claims_json"] or "[]")]
        questions = [
            ResumeDefenseQuestion.model_validate(item)
            for item in json.loads(row["questions_json"] or "[]")
        ]
        signal_summary = ResumeDefenseSignalSummary.model_validate(
            json.loads(row["signal_summary_json"] or "{}")
        )

        question = next((item for item in questions if item.question_id == payload.question_id.strip()), None)
        if not question:
            raise ResumeDefenseValidationError("Question does not belong to this Resume Defense session.")

        claim = next((item for item in claims if item.claim_id == question.claim_id), None)
        if not claim:
            raise ResumeDefenseValidationError("Claim linked to question was not found in this session.")

        evaluation = _build_evaluation(
            session_id=session_id,
            claim=claim,
            question=question,
            answer_text=payload.answer_text,
            signal_summary=signal_summary,
        )

        now = _now_iso()
        conn.execute(
            """
            INSERT INTO resume_defense_evaluations (
                session_id, claim_id, question_id, answer_text,
                evidence_strength, confidence, explanation,
                missing_evidence_json, suggested_follow_up_question,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, question_id) DO UPDATE SET
                claim_id = excluded.claim_id,
                answer_text = excluded.answer_text,
                evidence_strength = excluded.evidence_strength,
                confidence = excluded.confidence,
                explanation = excluded.explanation,
                missing_evidence_json = excluded.missing_evidence_json,
                suggested_follow_up_question = excluded.suggested_follow_up_question,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                evaluation.claim_id,
                evaluation.question_id,
                payload.answer_text.strip(),
                evaluation.evidence_strength,
                evaluation.confidence,
                evaluation.explanation,
                json.dumps(evaluation.missing_evidence, ensure_ascii=False),
                evaluation.suggested_follow_up_question,
                now,
                now,
            ),
        )

        total_questions = len(questions)
        answered_count = conn.execute(
            "SELECT COUNT(*) AS count FROM resume_defense_evaluations WHERE session_id = ?",
            (session_id,),
        ).fetchone()["count"]

        if answered_count >= total_questions and total_questions > 0:
            next_status = "evaluated"
        else:
            next_status = "in_progress"

        conn.execute(
            "UPDATE resume_defense_sessions SET status = ?, updated_at = ? WHERE session_id = ?",
            (next_status, now, session_id),
        )

        evaluations = _load_evaluations(conn, session_id)
        conn.execute(
            "UPDATE resume_defense_sessions SET evaluations_json = ? WHERE session_id = ?",
            (json.dumps([item.model_dump() for item in evaluations], ensure_ascii=False), session_id),
        )

    return evaluation


def get_phase3_matrix(user_id: str, session_id: str) -> ResumeDefenseMatrixResponse:
    with _connect() as conn:
        _init_db(conn)
        row = _session_row(conn, user_id, session_id)
        if not row:
            raise ResumeDefenseNotFoundError("Resume Defense session not found.")

        claims = [ResumeDefenseClaim.model_validate(item) for item in json.loads(row["claims_json"] or "[]")]
        questions = [
            ResumeDefenseQuestion.model_validate(item)
            for item in json.loads(row["questions_json"] or "[]")
        ]
        signal_summary = ResumeDefenseSignalSummary.model_validate(
            json.loads(row["signal_summary_json"] or "{}")
        )

        claim_map = {claim.claim_id: claim for claim in claims}
        question_map = {question.question_id: question for question in questions}
        claim_priority_map = {claim.claim_id: claim.priority for claim in claims}

        eval_rows = _load_evaluation_rows(conn, row["session_id"])
        entries: list[ResumeDefenseMatrixEntry] = []

        for eval_row in eval_rows:
            claim = claim_map.get(eval_row["claim_id"])
            question = question_map.get(eval_row["question_id"])

            strength = _normalize_strength(str(eval_row["evidence_strength"] or ""))
            missing = [str(item) for item in json.loads(eval_row["missing_evidence_json"] or "[]")]

            if claim:
                related_job_requirement = _related_job_requirement_text(claim, signal_summary)
                resume_claim = claim.claim_text
            else:
                related_job_requirement = signal_summary.jd_keywords[0] if signal_summary.jd_keywords else None
                resume_claim = ""

            interview_question = question.question if question else ""
            user_answer = (eval_row["answer_text"] or "").strip()

            entries.append(
                ResumeDefenseMatrixEntry(
                    claim_id=str(eval_row["claim_id"] or ""),
                    question_id=str(eval_row["question_id"] or ""),
                    resume_claim=resume_claim,
                    related_job_requirement=related_job_requirement,
                    interview_question=interview_question,
                    user_answer=user_answer,
                    evidence_strength=strength,
                    explanation=str(eval_row["explanation"] or ""),
                    missing_evidence=missing,
                    suggested_follow_up_question=str(eval_row["suggested_follow_up_question"] or ""),
                    recommendation=_recommendation_for_matrix_entry(strength, missing),
                )
            )

        entries.sort(
            key=lambda item: (claim_priority_map.get(item.claim_id, 0), item.claim_id, item.question_id),
            reverse=True,
        )

        strong_entries: list[ResumeDefenseMatrixEntry] = []
        moderate_entries: list[ResumeDefenseMatrixEntry] = []
        weak_entries: list[ResumeDefenseMatrixEntry] = []
        unsupported_entries: list[ResumeDefenseMatrixEntry] = []

        for entry in entries:
            if entry.evidence_strength == "Strong":
                strong_entries.append(entry)
            elif entry.evidence_strength == "Moderate":
                moderate_entries.append(entry)
            elif entry.evidence_strength == "Weak":
                weak_entries.append(entry)
            else:
                unsupported_entries.append(entry)

        summary = ResumeDefenseMatrixSummary(
            total_claims=len(entries),
            strong_claims=len(strong_entries),
            moderate_claims=len(moderate_entries),
            weak_claims=len(weak_entries),
            unsupported_claims=len(unsupported_entries),
        )

        grouped_claims = ResumeDefenseMatrixGroupedClaims(
            strong=strong_entries,
            moderate=moderate_entries,
            weak=weak_entries,
            unsupported=unsupported_entries,
        )

        narrative_summary = _build_matrix_narrative(
            strong_entries=strong_entries,
            moderate_entries=moderate_entries,
            weak_entries=weak_entries,
            unsupported_entries=unsupported_entries,
        )

        return ResumeDefenseMatrixResponse(
            session_id=row["session_id"],
            status=row["status"],
            generated_at=_now_iso(),
            summary=summary,
            narrative_summary=narrative_summary,
            grouped_claims=grouped_claims,
            entries=entries,
        )



def _split_answer_sentences(answer_text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", (answer_text or "").strip())
    return [part.strip(" -	") for part in parts if part and part.strip()]


def _resume_bullet_from_answer_sentence(sentence: str) -> str:
    cleaned = re.sub(r"\s+", " ", (sentence or "").strip())
    cleaned = cleaned.strip(" .")
    if not cleaned:
        return ""

    cleaned = re.sub(r"^i\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^my\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bi\s+(?=(?:led|managed|built|designed|implemented|owned|delivered|developed|coordinated|supported)\b)", "", cleaned, flags=re.IGNORECASE)

    if not cleaned:
        return ""

    cleaned = cleaned[0].upper() + cleaned[1:]
    if not cleaned.endswith("."):
        cleaned += "."
    return cleaned


def _select_grounded_rewrite_sentence(
    answer_text: str,
    claim_text: str,
    related_job_requirement: str | None,
) -> str | None:
    sentences = _split_answer_sentences(answer_text)
    if not sentences:
        return None

    related_tokens = _keywords(related_job_requirement or "")
    best_sentence = ""
    best_score = -1.0

    for sentence in sentences:
        overlap_ratio, _ = _overlap_ratio(claim_text, sentence)
        metric_bonus = 0.18 if _IMPACT_RE.search(sentence) else 0.0
        ownership_bonus = 0.1 if re.search(r"\bi\s+(?:" + "|".join(_REWRITE_ACTION_VERBS) + r")\b", sentence.lower()) else 0.0
        job_bonus = 0.0
        if related_tokens:
            sentence_tokens = _keywords(sentence)
            if sentence_tokens.intersection(related_tokens):
                job_bonus = 0.07

        score = overlap_ratio + metric_bonus + ownership_bonus + job_bonus
        if score > best_score:
            best_score = score
            best_sentence = sentence

    if best_score < 0.12:
        return None
    return best_sentence


def _build_reason_for_weakness(explanation: str, missing_evidence: list[str]) -> str:
    base = (explanation or "").strip()
    if missing_evidence:
        key_gap = missing_evidence[0]
        if key_gap and key_gap.lower() not in base.lower():
            if base:
                return f"{base} Key gap: {key_gap}"
            return key_gap
    return base or "Evidence is not yet specific enough to fully defend this claim."


def _build_rewrite_entry(
    claim: ResumeDefenseClaim,
    evaluation_row: sqlite3.Row,
    signal_summary: ResumeDefenseSignalSummary,
) -> ResumeDefenseRewriteEntry:
    strength = _normalize_strength(str(evaluation_row["evidence_strength"] or ""))
    missing = [str(item) for item in json.loads(evaluation_row["missing_evidence_json"] or "[]")]
    answer_text = (evaluation_row["answer_text"] or "").strip()
    related_job_requirement = _related_job_requirement_text(claim, signal_summary)

    reason_for_weakness = _build_reason_for_weakness(
        str(evaluation_row["explanation"] or ""),
        missing,
    )

    overlap_ratio, _ = _overlap_ratio(claim.claim_text, answer_text)
    has_metric = _IMPACT_RE.search(answer_text) is not None
    candidate_sentence = _select_grounded_rewrite_sentence(
        answer_text=answer_text,
        claim_text=claim.claim_text,
        related_job_requirement=related_job_requirement,
    )

    insufficient = False
    if _is_generic_answer(answer_text):
        insufficient = True
    elif len(answer_text.split()) < 12:
        insufficient = True
    elif candidate_sentence is None:
        insufficient = True
    elif overlap_ratio < 0.14 and not has_metric:
        insufficient = True

    improved_claim: str | None = None
    explanation_of_changes: str

    if insufficient:
        explanation_of_changes = (
            "Insufficient grounded evidence in the interview answer to safely strengthen this claim "
            "without risking fabrication. Add specific actions, context, and measurable outcomes first."
        )
    else:
        improved_claim = _resume_bullet_from_answer_sentence(candidate_sentence or "")
        if not improved_claim:
            improved_claim = None

        if not improved_claim:
            explanation_of_changes = (
                "Insufficient grounded evidence in the interview answer to safely rewrite the claim."
            )
            insufficient = True
        else:
            explanation_parts = [
                "Rewrite tightens wording around details explicitly stated in the interview answer.",
            ]
            if has_metric:
                explanation_parts.append("Preserves measurable outcomes that the candidate explicitly provided.")
            else:
                explanation_parts.append("Avoids adding metrics not supported by the candidate's answer.")
            if related_job_requirement:
                explanation_parts.append(
                    "Keeps claim aligned to role requirements only when that linkage appears in the answer."
                )
            explanation_of_changes = " ".join(explanation_parts)

    return ResumeDefenseRewriteEntry(
        claim_id=claim.claim_id,
        question_id=str(evaluation_row["question_id"] or ""),
        evidence_strength=strength,
        original_resume_claim=claim.claim_text,
        related_job_requirement=related_job_requirement,
        reason_for_weakness=reason_for_weakness,
        improved_resume_claim=improved_claim,
        explanation_of_changes=explanation_of_changes,
        insufficient_evidence=insufficient,
    )


def get_phase4_rewrites(user_id: str, session_id: str) -> ResumeDefenseRewriteResponse:
    with _connect() as conn:
        _init_db(conn)
        row = _session_row(conn, user_id, session_id)
        if not row:
            raise ResumeDefenseNotFoundError("Resume Defense session not found.")

        claims = [ResumeDefenseClaim.model_validate(item) for item in json.loads(row["claims_json"] or "[]")]
        signal_summary = ResumeDefenseSignalSummary.model_validate(
            json.loads(row["signal_summary_json"] or "{}")
        )

        claim_map = {claim.claim_id: claim for claim in claims}
        claim_priority_map = {claim.claim_id: claim.priority for claim in claims}

        entries: list[ResumeDefenseRewriteEntry] = []
        moderate_count = 0
        weak_count = 0

        eval_rows = _load_evaluation_rows(conn, row["session_id"])
        for eval_row in eval_rows:
            strength = _normalize_strength(str(eval_row["evidence_strength"] or ""))
            if strength not in REWRITE_TARGET_STRENGTHS:
                continue

            claim = claim_map.get(str(eval_row["claim_id"] or ""))
            if not claim:
                continue

            if strength == "Moderate":
                moderate_count += 1
            elif strength == "Weak":
                weak_count += 1

            entries.append(
                _build_rewrite_entry(
                    claim=claim,
                    evaluation_row=eval_row,
                    signal_summary=signal_summary,
                )
            )

        entries.sort(
            key=lambda item: (claim_priority_map.get(item.claim_id, 0), item.claim_id, item.question_id),
            reverse=True,
        )

        rewritten_claims = sum(1 for entry in entries if entry.improved_resume_claim and not entry.insufficient_evidence)
        insufficient_claims = sum(1 for entry in entries if entry.insufficient_evidence)

        summary = ResumeDefenseRewriteSummary(
            targeted_claims=len(entries),
            rewritten_claims=rewritten_claims,
            insufficient_evidence_claims=insufficient_claims,
            moderate_claims=moderate_count,
            weak_claims=weak_count,
        )

        return ResumeDefenseRewriteResponse(
            session_id=row["session_id"],
            status=row["status"],
            generated_at=_now_iso(),
            summary=summary,
            entries=entries,
        )



def _claim_excerpt(value: str, limit: int = 120) -> str:
    return _excerpt(value or "", limit=limit)


def _build_career_readiness_summary(
    matrix: ResumeDefenseMatrixResponse,
    rewrites: ResumeDefenseRewriteResponse,
) -> ResumeDefenseCareerReadinessSummary:
    total = matrix.summary.total_claims
    strong = matrix.summary.strong_claims
    moderate = matrix.summary.moderate_claims
    weak = matrix.summary.weak_claims
    unsupported = matrix.summary.unsupported_claims

    well_defended = strong + moderate
    challenged = weak + unsupported

    if total == 0:
        readiness_label = "insufficient_data"
    elif unsupported > 0 or weak > max(1, strong + moderate):
        readiness_label = "needs_preparation"
    elif challenged == 0:
        readiness_label = "interview_ready"
    elif (well_defended / max(1, total)) >= 0.65:
        readiness_label = "developing"
    else:
        readiness_label = "needs_preparation"

    strengths: list[str] = []
    for entry in [*matrix.grouped_claims.strong, *matrix.grouped_claims.moderate]:
        strengths.append(f"Can defend: {_claim_excerpt(entry.resume_claim, 95)}")
        if len(strengths) >= 3:
            break

    risks: list[str] = []
    for entry in [*matrix.grouped_claims.unsupported, *matrix.grouped_claims.weak]:
        risks.append(f"Likely challenged: {_claim_excerpt(entry.resume_claim, 95)}")
        if len(risks) >= 3:
            break

    priorities: list[str] = []
    for entry in [*matrix.grouped_claims.unsupported, *matrix.grouped_claims.weak, *matrix.grouped_claims.moderate]:
        for item in entry.missing_evidence:
            text = str(item).strip()
            if text and text not in priorities:
                priorities.append(text)
            if len(priorities) >= 4:
                break
        if len(priorities) >= 4:
            break

    if rewrites.summary.insufficient_evidence_claims > 0:
        note = "Collect stronger interview evidence before rewriting unsupported claims."
        if note not in priorities:
            priorities.append(note)

    rationale = (
        f"{well_defended} of {total} claims are currently well defended; "
        f"{challenged} claims are still vulnerable to interviewer challenge. "
        f"Focus preparation on weak evidence areas before final resume updates."
    ) if total > 0 else "No evaluated claims yet. Complete interview answers to produce readiness insights."

    return ResumeDefenseCareerReadinessSummary(
        total_claims=total,
        strong_claims=strong,
        moderate_claims=moderate,
        weak_claims=weak,
        unsupported_claims=unsupported,
        well_defended_claims=well_defended,
        challenged_claims=challenged,
        readiness_label=readiness_label,
        rationale=rationale,
        strengths=strengths,
        risks=risks,
        preparation_priorities=priorities,
    )


def _build_phase5_report_text(
    matrix: ResumeDefenseMatrixResponse,
    rewrites: ResumeDefenseRewriteResponse,
    readiness: ResumeDefenseCareerReadinessSummary,
) -> str:
    lines: list[str] = []
    lines.append("Resume Defense Integrated Report")
    lines.append("")
    lines.append(f"Readiness Label: {readiness.readiness_label}")
    lines.append(readiness.rationale)
    lines.append("")
    lines.append(f"Narrative Summary: {matrix.narrative_summary}")
    lines.append("")
    lines.append("Evidence Distribution:")
    lines.append(f"- Total Claims: {readiness.total_claims}")
    lines.append(f"- Strong: {readiness.strong_claims}")
    lines.append(f"- Moderate: {readiness.moderate_claims}")
    lines.append(f"- Weak: {readiness.weak_claims}")
    lines.append(f"- Unsupported: {readiness.unsupported_claims}")
    lines.append("")

    if readiness.strengths:
        lines.append("Well Defended Areas:")
        lines.extend([f"- {item}" for item in readiness.strengths])
        lines.append("")

    if readiness.risks:
        lines.append("Likely Interview Challenges:")
        lines.extend([f"- {item}" for item in readiness.risks])
        lines.append("")

    if readiness.preparation_priorities:
        lines.append("Preparation Priorities:")
        lines.extend([f"- {item}" for item in readiness.preparation_priorities])
        lines.append("")

    lines.append("Resume Rewrite Suggestions:")
    if not rewrites.entries:
        lines.append("- No rewrite targets yet.")
    else:
        for entry in rewrites.entries[:6]:
            lines.append(f"- Original: {entry.original_resume_claim}")
            lines.append(f"  Reason: {entry.reason_for_weakness}")
            if entry.improved_resume_claim:
                lines.append(f"  Improved: {entry.improved_resume_claim}")
            else:
                lines.append("  Improved: Insufficient grounded evidence to rewrite safely.")

    return "\n".join(lines).strip()


def _build_phase5_report_html(
    matrix: ResumeDefenseMatrixResponse,
    rewrites: ResumeDefenseRewriteResponse,
    readiness: ResumeDefenseCareerReadinessSummary,
) -> str:
    matrix_rows = "".join(
        [
            "<tr>"
            f"<td>{escape(entry.resume_claim or '')}</td>"
            f"<td>{escape(entry.related_job_requirement or '')}</td>"
            f"<td>{escape(entry.evidence_strength or '')}</td>"
            f"<td>{escape(entry.explanation or '')}</td>"
            f"<td>{escape(entry.recommendation or '')}</td>"
            "</tr>"
            for entry in matrix.entries
        ]
    )

    rewrite_rows = "".join(
        [
            "<tr>"
            f"<td>{escape(entry.original_resume_claim or '')}</td>"
            f"<td>{escape(entry.reason_for_weakness or '')}</td>"
            f"<td>{escape(entry.improved_resume_claim or 'Insufficient grounded evidence.')}</td>"
            f"<td>{escape(entry.explanation_of_changes or '')}</td>"
            "</tr>"
            for entry in rewrites.entries
        ]
    )

    strengths_html = "".join([f"<li>{escape(item)}</li>" for item in readiness.strengths])
    risks_html = "".join([f"<li>{escape(item)}</li>" for item in readiness.risks])
    priorities_html = "".join([f"<li>{escape(item)}</li>" for item in readiness.preparation_priorities])
    empty_matrix_row = '<tr><td colspan="5">No evaluated claims yet.</td></tr>'
    empty_rewrite_row = '<tr><td colspan="4">No rewrite targets yet.</td></tr>'
    empty_strengths_item = '<li>None yet.</li>'
    empty_risks_item = '<li>None identified.</li>'
    empty_priorities_item = '<li>No priorities yet.</li>'

    return (
        "<section style='font-family:Arial,sans-serif;line-height:1.45;color:#1f2937'>"
        "<h1 style='margin:0 0 12px'>Resume Defense Integrated Report</h1>"
        f"<p><strong>Readiness:</strong> {escape(readiness.readiness_label)}<br/>"
        f"{escape(readiness.rationale)}</p>"
        f"<p><strong>Narrative Summary:</strong> {escape(matrix.narrative_summary)}</p>"
        "<h2>Evidence Distribution</h2>"
        "<ul>"
        f"<li>Total Claims: {readiness.total_claims}</li>"
        f"<li>Strong: {readiness.strong_claims}</li>"
        f"<li>Moderate: {readiness.moderate_claims}</li>"
        f"<li>Weak: {readiness.weak_claims}</li>"
        f"<li>Unsupported: {readiness.unsupported_claims}</li>"
        "</ul>"
        "<h2>Well Defended Areas</h2>"
        f"<ul>{strengths_html or empty_strengths_item}</ul>"
        "<h2>Likely Interview Challenges</h2>"
        f"<ul>{risks_html or empty_risks_item}</ul>"
        "<h2>Preparation Priorities</h2>"
        f"<ul>{priorities_html or empty_priorities_item}</ul>"
        "<h2>Resume Defense Matrix</h2>"
        "<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse;width:100%;font-size:12px'>"
        "<thead><tr><th>Resume Claim</th><th>Related Job Requirement</th><th>Evidence Strength</th><th>Explanation</th><th>Recommendation</th></tr></thead>"
        f"<tbody>{matrix_rows or empty_matrix_row}</tbody>"
        "</table>"
        "<h2>Resume Rewrite Suggestions</h2>"
        "<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse;width:100%;font-size:12px'>"
        "<thead><tr><th>Original Claim</th><th>Reason for Weakness</th><th>Improved Claim</th><th>Change Explanation</th></tr></thead>"
        f"<tbody>{rewrite_rows or empty_rewrite_row}</tbody>"
        "</table>"
        "</section>"
    )


def get_phase5_integrated_report(user_id: str, session_id: str) -> ResumeDefenseIntegratedReportResponse:
    matrix = get_phase3_matrix(user_id, session_id)
    rewrites = get_phase4_rewrites(user_id, session_id)

    readiness = _build_career_readiness_summary(matrix, rewrites)
    report_text = _build_phase5_report_text(matrix, rewrites, readiness)
    report_html = _build_phase5_report_html(matrix, rewrites, readiness)

    artifact = ResumeDefenseReportingArtifact(
        detected_intent="Resume_Defense_Report",
        result_text=report_text,
        result_html=report_html,
        narrative_summary=matrix.narrative_summary,
    )

    return ResumeDefenseIntegratedReportResponse(
        session_id=matrix.session_id,
        status=matrix.status,
        generated_at=_now_iso(),
        narrative_summary=matrix.narrative_summary,
        career_readiness=readiness,
        matrix=matrix,
        rewrites=rewrites,
        report=artifact,
    )
