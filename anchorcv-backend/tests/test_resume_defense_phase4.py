from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps.auth import require_active_access
from app.routers import resume_defense
from app.schemas.resume_defense import ResumeDefenseAnswerSubmitRequest, ResumeDefenseStartRequest
from app.services import resume_defense_service


def _sample_resume() -> str:
    return """
Jane Candidate

Experience
- Increased monthly active users by 28% over two quarters through onboarding redesign.
- Led a cross-functional team of 6 engineers to deliver a customer onboarding platform.
- Built Python and SQL data pipelines for weekly executive reporting.
""".strip()


def _sample_analysis() -> str:
    return """
Strengths:
- Increased monthly active users by 28% over two quarters through onboarding redesign.
- Led a cross-functional team of 6 engineers to deliver a customer onboarding platform.
- Built Python and SQL data pipelines for weekly executive reporting.
Gaps:
- Clarify ownership boundaries and metric methodology.
""".strip()


def _new_session(monkeypatch, tmp_path, user_id: str = "phase4-user"):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase4.db"))
    payload = ResumeDefenseStartRequest(
        resume_text=_sample_resume(),
        analysis_output=_sample_analysis(),
        job_description="Senior analytics role requiring experimentation, stakeholder communication, python, and sql.",
        ats_missing_keywords=["stakeholder communication", "experimentation"],
    )
    return resume_defense_service.start_phase1_session(user_id, payload)


def _answer_question(user_id: str, session_id: str, question_id: str, answer_text: str):
    return resume_defense_service.submit_phase2_answer(
        user_id,
        session_id,
        ResumeDefenseAnswerSubmitRequest(
            question_id=question_id,
            answer_text=answer_text,
        ),
    )


def test_phase4_successful_grounded_rewrite(monkeypatch, tmp_path):
    session = _new_session(monkeypatch, tmp_path)
    question = session.questions[0]

    evaluation = _answer_question(
        "phase4-user",
        session.session_id,
        question.question_id,
        (
            "I led the onboarding redesign and partnered with engineering and product. "
            "I improved monthly active users by running weekly experiments and shared findings "
            "with stakeholders in executive reviews."
        ),
    )

    assert evaluation.evidence_strength in {"Moderate", "Weak"}

    rewrites = resume_defense_service.get_phase4_rewrites("phase4-user", session.session_id)

    assert rewrites.summary.targeted_claims >= 1
    assert len(rewrites.entries) >= 1
    first = rewrites.entries[0]
    assert first.original_resume_claim
    assert first.reason_for_weakness
    assert first.explanation_of_changes
    assert first.improved_resume_claim is not None
    assert "fabrication" not in first.explanation_of_changes.lower()



def test_phase4_insufficient_evidence_handling(monkeypatch, tmp_path):
    session = _new_session(monkeypatch, tmp_path, user_id="insufficient-user")
    question = session.questions[0]

    evaluation = _answer_question(
        "insufficient-user",
        session.session_id,
        question.question_id,
        "I supported onboarding tasks with the team and helped where needed across reporting updates.",
    )

    assert evaluation.evidence_strength == "Weak"

    rewrites = resume_defense_service.get_phase4_rewrites("insufficient-user", session.session_id)

    assert rewrites.summary.targeted_claims == 1
    entry = rewrites.entries[0]
    assert entry.insufficient_evidence is True
    assert entry.improved_resume_claim is None
    assert "insufficient grounded evidence" in entry.explanation_of_changes.lower()



def test_phase4_multiple_weak_claims(monkeypatch, tmp_path):
    session = _new_session(monkeypatch, tmp_path, user_id="multiweak-user")

    assert len(session.questions) >= 2

    first = _answer_question(
        "multiweak-user",
        session.session_id,
        session.questions[0].question_id,
        "I supported onboarding tasks and team coordination during project updates without owning decisions.",
    )
    second = _answer_question(
        "multiweak-user",
        session.session_id,
        session.questions[1].question_id,
        "Supported onboarding platform coordination with the engineering team during delivery updates.",
    )

    assert first.evidence_strength == "Weak"
    assert second.evidence_strength == "Weak"

    rewrites = resume_defense_service.get_phase4_rewrites("multiweak-user", session.session_id)

    assert rewrites.summary.targeted_claims >= 2
    assert rewrites.summary.weak_claims >= 2
    assert rewrites.summary.moderate_claims + rewrites.summary.weak_claims == rewrites.summary.targeted_claims



def test_phase4_invalid_session_handling(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase4_invalid.db"))

    app = FastAPI()
    app.include_router(resume_defense.router, prefix="/api")

    def _fake_active_user():
        return {"id": "api-user", "is_premium": True}

    app.dependency_overrides[require_active_access] = _fake_active_user
    client = TestClient(app)

    response = client.get("/api/resume-defense/sessions/rd_missing/rewrites")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()



def test_phase4_authorization_required(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase4_auth.db"))

    app = FastAPI()
    app.include_router(resume_defense.router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/resume-defense/sessions/rd_x/rewrites")

    assert response.status_code == 401
