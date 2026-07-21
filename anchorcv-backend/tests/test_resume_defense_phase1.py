from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps.auth import require_active_access
from app.routers import resume_defense
from app.schemas.resume_defense import ResumeDefenseStartRequest
from app.services import resume_defense_service


def _sample_resume() -> str:
    return """
John Doe

Experience
- Led a cross-functional team of 6 engineers to deliver a customer onboarding platform.
- Increased monthly active users by 28% over two quarters.
- Built Python and SQL data pipelines for weekly executive reporting.

Education
BSc Computer Science
""".strip()


def _sample_analysis_output() -> str:
    return """
Key evidence-based strengths:
- Increased monthly active users by 28% over two quarters through onboarding redesign.
- Built Python and SQL data pipelines supporting business decisions.
Potential defense gap:
- Clarify exact ownership boundaries and decision-making role.
""".strip()


def test_phase1_session_reuses_analysis_output_for_claims(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase1.db"))

    payload = ResumeDefenseStartRequest(
        resume_text=_sample_resume(),
        analysis_output=_sample_analysis_output(),
        job_description="Senior Data Analyst role requiring Python, SQL, stakeholder communication, and experimentation.",
        ats_missing_keywords=["stakeholder communication", "experimentation"],
        ats_score=62.0,
        model="gpt-4o-mini",
    )

    session = resume_defense_service.start_phase1_session("user-1", payload)

    assert session.session_id.startswith("rd_")
    assert session.status == "initiated"
    assert len(session.claims) > 0
    assert len(session.questions) == len(session.claims)
    assert any(claim.source == "analysis_output" for claim in session.claims)
    assert len(session.signal_summary.jd_keywords) > 0



def test_phase1_session_lookup_enforces_user_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_scope.db"))

    payload = ResumeDefenseStartRequest(
        resume_text=_sample_resume(),
        analysis_output=_sample_analysis_output(),
    )

    created = resume_defense_service.start_phase1_session("owner-user", payload)

    as_owner = resume_defense_service.get_phase1_session("owner-user", created.session_id)
    as_other = resume_defense_service.get_phase1_session("other-user", created.session_id)

    assert as_owner is not None
    assert as_owner.session_id == created.session_id
    assert as_other is None



def test_resume_defense_router_session_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_api.db"))

    app = FastAPI()
    app.include_router(resume_defense.router, prefix="/api")

    def _fake_active_user():
        return {"id": "api-user", "is_premium": True}

    app.dependency_overrides[require_active_access] = _fake_active_user

    client = TestClient(app)

    payload = {
        "resume_text": _sample_resume(),
        "analysis_output": _sample_analysis_output(),
        "job_description": "Data engineer role requiring Python, SQL, data modeling, and stakeholder communication.",
        "ats_missing_keywords": ["stakeholder communication"],
    }

    created = client.post("/api/resume-defense/sessions", json=payload)
    assert created.status_code == 200, created.text

    created_body = created.json()
    assert created_body["session_id"].startswith("rd_")
    assert len(created_body["claims"]) > 0
    assert len(created_body["questions"]) == len(created_body["claims"])
    assert any("job_requirement" in q["source_signals"] for q in created_body["questions"])

    fetched = client.get(f"/api/resume-defense/sessions/{created_body['session_id']}")
    assert fetched.status_code == 200, fetched.text
    fetched_body = fetched.json()
    assert fetched_body["session_id"] == created_body["session_id"]
