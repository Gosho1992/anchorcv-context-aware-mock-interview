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
- Increased annual revenue by 35% through pricing experiments across SMB customers.
- Led a cross-functional team of 8 engineers to deliver onboarding automation platform.
- Built Python and SQL pipelines for weekly executive reporting dashboards.
- Designed stakeholder communication framework for quarterly roadmap updates.
""".strip()


def _sample_analysis() -> str:
    return """
Strengths:
- Increased annual revenue by 35% through pricing experiments across SMB customers.
- Led a cross-functional team of 8 engineers to deliver onboarding automation platform.
- Built Python and SQL pipelines for weekly executive reporting dashboards.
- Designed stakeholder communication framework for quarterly roadmap updates.
Gaps:
- Clarify ownership boundaries and measurable outcomes.
""".strip()


def _new_session(monkeypatch, tmp_path, user_id: str = "phase3-user"):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase3.db"))
    payload = ResumeDefenseStartRequest(
        resume_text=_sample_resume(),
        analysis_output=_sample_analysis(),
        job_description=(
            "Senior analytics leader role requiring experimentation, stakeholder communication, "
            "python, sql, and cross-functional leadership."
        ),
        ats_missing_keywords=["stakeholder communication", "experimentation"],
    )
    return resume_defense_service.start_phase1_session(user_id, payload)


def _answer_for_claim(claim_text: str) -> str:
    lower = claim_text.lower()
    if "revenue" in lower or "increased" in lower:
        return (
            "I led pricing experiments for SMB customers and increased annual revenue by 35%. "
            "I owned experiment design, set the baseline, and reported weekly measured outcomes "
            "to leadership and stakeholders."
        )
    if "led" in lower or "cross-functional" in lower:
        return (
            "I coordinated the team and made planning decisions during onboarding delivery with "
            "product partners and engineering."
        )
    if "built python" in lower or "pipelines" in lower:
        return "I had some exposure to Python work in that area but cannot explain specifics yet."
    return "I enjoy photography, travel, and listening to music on weekends."


def _complete_session_with_answers(monkeypatch, tmp_path, user_id: str = "phase3-user"):
    session = _new_session(monkeypatch, tmp_path, user_id=user_id)
    claim_map = {claim.claim_id: claim for claim in session.claims}

    for question in session.questions:
        claim = claim_map[question.claim_id]
        resume_defense_service.submit_phase2_answer(
            user_id,
            session.session_id,
            ResumeDefenseAnswerSubmitRequest(
                question_id=question.question_id,
                answer_text=_answer_for_claim(claim.claim_text),
            ),
        )

    return session


def test_phase3_matrix_generation_for_completed_session(monkeypatch, tmp_path):
    session = _complete_session_with_answers(monkeypatch, tmp_path)

    matrix = resume_defense_service.get_phase3_matrix("phase3-user", session.session_id)

    assert matrix.session_id == session.session_id
    assert matrix.status == "evaluated"
    assert matrix.summary.total_claims == len(session.claims)
    assert len(matrix.entries) == len(session.claims)
    assert matrix.narrative_summary
    assert all(item.resume_claim for item in matrix.entries)
    assert all(item.interview_question for item in matrix.entries)
    assert all(item.user_answer for item in matrix.entries)
    assert all(item.recommendation for item in matrix.entries)


def test_phase3_matrix_grouping_and_summary_statistics(monkeypatch, tmp_path):
    session = _complete_session_with_answers(monkeypatch, tmp_path, user_id="group-user")

    matrix = resume_defense_service.get_phase3_matrix("group-user", session.session_id)

    grouped_total = (
        len(matrix.grouped_claims.strong)
        + len(matrix.grouped_claims.moderate)
        + len(matrix.grouped_claims.weak)
        + len(matrix.grouped_claims.unsupported)
    )

    assert grouped_total == len(matrix.entries)
    assert matrix.summary.total_claims == grouped_total
    assert matrix.summary.strong_claims == len(matrix.grouped_claims.strong)
    assert matrix.summary.moderate_claims == len(matrix.grouped_claims.moderate)
    assert matrix.summary.weak_claims == len(matrix.grouped_claims.weak)
    assert matrix.summary.unsupported_claims == len(matrix.grouped_claims.unsupported)

    assert all(item.evidence_strength == "Strong" for item in matrix.grouped_claims.strong)
    assert all(item.evidence_strength == "Moderate" for item in matrix.grouped_claims.moderate)
    assert all(item.evidence_strength == "Weak" for item in matrix.grouped_claims.weak)
    assert all(item.evidence_strength == "Unsupported" for item in matrix.grouped_claims.unsupported)



def test_phase3_empty_session_matrix_handling(monkeypatch, tmp_path):
    session = _new_session(monkeypatch, tmp_path, user_id="empty-user")

    matrix = resume_defense_service.get_phase3_matrix("empty-user", session.session_id)

    assert matrix.session_id == session.session_id
    assert matrix.summary.total_claims == 0
    assert matrix.summary.strong_claims == 0
    assert matrix.summary.moderate_claims == 0
    assert matrix.summary.weak_claims == 0
    assert matrix.summary.unsupported_claims == 0
    assert matrix.entries == []
    assert "no claim answers" in matrix.narrative_summary.lower()



def test_phase3_invalid_session_handling(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase3_invalid.db"))

    app = FastAPI()
    app.include_router(resume_defense.router, prefix="/api")

    def _fake_active_user():
        return {"id": "api-user", "is_premium": True}

    app.dependency_overrides[require_active_access] = _fake_active_user
    client = TestClient(app)

    response = client.get("/api/resume-defense/sessions/rd_missing/matrix")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()



def test_phase3_authorization_required(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase3_auth.db"))

    app = FastAPI()
    app.include_router(resume_defense.router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/resume-defense/sessions/rd_x/matrix")

    assert response.status_code == 401
