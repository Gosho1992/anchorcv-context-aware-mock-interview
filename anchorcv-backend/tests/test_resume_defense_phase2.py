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
Gaps:
- Clarify ownership boundaries and metric methodology.
""".strip()


def _new_session(monkeypatch, tmp_path, user_id: str = "phase2-user"):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase2.db"))
    payload = ResumeDefenseStartRequest(
        resume_text=_sample_resume(),
        analysis_output=_sample_analysis(),
        job_description="Senior product analytics role requiring experimentation, stakeholder communication, and Python.",
        ats_missing_keywords=["stakeholder communication", "experimentation"],
    )
    return resume_defense_service.start_phase1_session(user_id, payload)



def test_phase2_successful_answer_evaluation(monkeypatch, tmp_path):
    session = _new_session(monkeypatch, tmp_path)
    question = session.questions[0]

    answer = ResumeDefenseAnswerSubmitRequest(
        question_id=question.question_id,
        answer_text=(
            "I led the onboarding redesign and worked with engineering and product partners. "
            "Monthly active users increased by 28% over two quarters, measured in our weekly analytics dashboard. "
            "I designed and ran the experiments and presented results to stakeholders."
        ),
    )

    evaluation = resume_defense_service.submit_phase2_answer("phase2-user", session.session_id, answer)

    assert evaluation.evidence_strength in {"Strong", "Moderate"}
    assert 0.0 <= evaluation.confidence <= 1.0
    assert evaluation.explanation
    assert evaluation.resume_claim
    assert evaluation.interview_question
    assert evaluation.suggested_follow_up_question



def test_phase2_weak_evidence(monkeypatch, tmp_path):
    session = _new_session(monkeypatch, tmp_path, user_id="weak-user")
    question = session.questions[0]

    answer = ResumeDefenseAnswerSubmitRequest(
        question_id=question.question_id,
        answer_text="I had some exposure to user growth work but cannot provide much detail right now.",
    )

    evaluation = resume_defense_service.submit_phase2_answer("weak-user", session.session_id, answer)

    assert evaluation.evidence_strength == "Weak"
    assert len(evaluation.missing_evidence) > 0
    assert "unsupported" not in evaluation.explanation.lower()



def test_phase2_unsupported_claim(monkeypatch, tmp_path):
    session = _new_session(monkeypatch, tmp_path, user_id="unsupported-user")
    question = session.questions[0]

    answer = ResumeDefenseAnswerSubmitRequest(
        question_id=question.question_id,
        answer_text="I enjoy photography, travel, and listening to music on weekends.",
    )

    evaluation = resume_defense_service.submit_phase2_answer("unsupported-user", session.session_id, answer)

    assert evaluation.evidence_strength == "Unsupported"
    assert len(evaluation.missing_evidence) > 0
    assert "unsupported" in evaluation.explanation.lower()



def test_phase2_invalid_session_handling(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase2_invalid.db"))

    app = FastAPI()
    app.include_router(resume_defense.router, prefix="/api")

    def _fake_active_user():
        return {"id": "api-user", "is_premium": True}

    app.dependency_overrides[require_active_access] = _fake_active_user
    client = TestClient(app)

    response = client.post(
        "/api/resume-defense/sessions/rd_missing/answers",
        json={"question_id": "q_clm_01", "answer_text": "I delivered measurable outcomes."},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()



def test_phase2_authorization_required(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase2_auth.db"))

    app = FastAPI()
    app.include_router(resume_defense.router, prefix="/api")
    client = TestClient(app)

    response = client.post(
        "/api/resume-defense/sessions/rd_x/answers",
        json={"question_id": "q_clm_01", "answer_text": "I delivered measurable outcomes with clear ownership."},
    )

    assert response.status_code == 401
