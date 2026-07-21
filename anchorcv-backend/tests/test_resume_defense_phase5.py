from io import BytesIO

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps.auth import require_active_access
from app.routers import export as export_router
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


def _answer_for_claim(claim_text: str) -> str:
    lower = claim_text.lower()
    if "increased" in lower or "monthly active users" in lower:
        return (
            "I led onboarding redesign experiments and worked with engineering and product partners. "
            "Monthly active users increased by 28% over two quarters, measured weekly in our dashboard."
        )
    if "led" in lower or "cross-functional" in lower:
        return (
            "I coordinated the cross-functional team and drove milestone decisions across planning, "
            "delivery, and stakeholder communication for the onboarding platform."
        )
    if "python" in lower or "pipelines" in lower:
        return "I supported data pipeline work for reporting updates during weekly team delivery cycles."
    return "I contributed to the workstream and collaborated on execution details."



def _build_app(with_export: bool = False) -> FastAPI:
    app = FastAPI()
    app.include_router(resume_defense.router, prefix="/api")
    if with_export:
        app.include_router(export_router.router, prefix="/api")

    def _fake_active_user():
        return {"id": "phase5-user", "is_premium": True}

    app.dependency_overrides[require_active_access] = _fake_active_user
    return app



def test_phase5_end_to_end_workflow_api(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase5_e2e.db"))
    app = _build_app(with_export=False)
    client = TestClient(app)

    start_payload = {
        "resume_text": _sample_resume(),
        "analysis_output": _sample_analysis(),
        "job_description": "Senior analytics role requiring experimentation, stakeholder communication, python, and sql.",
        "ats_missing_keywords": ["stakeholder communication", "experimentation"],
    }

    created = client.post("/api/resume-defense/sessions", json=start_payload)
    assert created.status_code == 200, created.text
    session = created.json()
    assert session["session_id"].startswith("rd_")
    assert len(session["questions"]) == len(session["claims"])

    claim_map = {claim["claim_id"]: claim for claim in session["claims"]}

    for question in session["questions"]:
        claim = claim_map[question["claim_id"]]
        answer_payload = {
            "question_id": question["question_id"],
            "answer_text": _answer_for_claim(claim["claim_text"]),
        }
        evaluated = client.post(
            f"/api/resume-defense/sessions/{session['session_id']}/answers",
            json=answer_payload,
        )
        assert evaluated.status_code == 200, evaluated.text

    matrix_resp = client.get(f"/api/resume-defense/sessions/{session['session_id']}/matrix")
    rewrites_resp = client.get(f"/api/resume-defense/sessions/{session['session_id']}/rewrites")
    report_resp = client.get(f"/api/resume-defense/sessions/{session['session_id']}/report")

    assert matrix_resp.status_code == 200, matrix_resp.text
    assert rewrites_resp.status_code == 200, rewrites_resp.text
    assert report_resp.status_code == 200, report_resp.text

    matrix = matrix_resp.json()
    rewrites = rewrites_resp.json()
    report = report_resp.json()

    assert report["session_id"] == session["session_id"]
    assert report["matrix"]["summary"]["total_claims"] == matrix["summary"]["total_claims"]
    assert report["rewrites"]["summary"]["targeted_claims"] == rewrites["summary"]["targeted_claims"]
    assert report["narrative_summary"] == matrix["narrative_summary"]

    readiness = report["career_readiness"]
    assert readiness["total_claims"] == matrix["summary"]["total_claims"]
    assert readiness["strong_claims"] == matrix["summary"]["strong_claims"]
    assert readiness["moderate_claims"] == matrix["summary"]["moderate_claims"]
    assert readiness["weak_claims"] == matrix["summary"]["weak_claims"]
    assert readiness["unsupported_claims"] == matrix["summary"]["unsupported_claims"]
    assert readiness["well_defended_claims"] + readiness["challenged_claims"] == readiness["total_claims"]

    artifact = report["report"]
    assert artifact["detected_intent"] == "Resume_Defense_Report"
    assert artifact["result_text"]
    assert artifact["result_html"]
    assert artifact["narrative_summary"]



def test_phase5_export_report_compatibility(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase5_export.db"))

    def _fake_export_pdf(_html: str):
        return BytesIO(b"%PDF-1.4 fake resume defense report")

    def _fake_export_docx(html: str = "", cv_data=None):
        _ = html
        _ = cv_data
        return BytesIO(b"PK\x03\x04fake-docx")

    monkeypatch.setattr(export_router, "export_pdf", _fake_export_pdf)
    monkeypatch.setattr(export_router, "export_docx", _fake_export_docx)

    app = _build_app(with_export=True)
    client = TestClient(app)

    created = client.post(
        "/api/resume-defense/sessions",
        json={
            "resume_text": _sample_resume(),
            "analysis_output": _sample_analysis(),
            "job_description": "Analytics role requiring stakeholder communication and python.",
            "ats_missing_keywords": ["stakeholder communication"],
        },
    )
    assert created.status_code == 200, created.text
    session = created.json()

    claim_map = {claim["claim_id"]: claim for claim in session["claims"]}
    for question in session["questions"]:
        claim = claim_map[question["claim_id"]]
        answer_payload = {
            "question_id": question["question_id"],
            "answer_text": _answer_for_claim(claim["claim_text"]),
        }
        evaluated = client.post(
            f"/api/resume-defense/sessions/{session['session_id']}/answers",
            json=answer_payload,
        )
        assert evaluated.status_code == 200, evaluated.text

    report_resp = client.get(f"/api/resume-defense/sessions/{session['session_id']}/report")
    assert report_resp.status_code == 200, report_resp.text
    report_payload = report_resp.json()["report"]

    pdf_resp = client.post(
        "/api/export/pdf",
        json={
            "html": report_payload["result_html"],
            "filename": "resume-defense-report.pdf",
        },
    )
    assert pdf_resp.status_code == 200, pdf_resp.text

    docx_resp = client.post(
        "/api/export/docx",
        json={
            "html": report_payload["result_html"],
            "cv_data": {"resume_defense": report_resp.json()},
            "filename": "resume-defense-report.docx",
        },
    )
    assert docx_resp.status_code == 200, docx_resp.text



def test_phase5_invalid_session_and_authorization(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase5_invalid.db"))

    app = FastAPI()
    app.include_router(resume_defense.router, prefix="/api")

    def _fake_active_user():
        return {"id": "phase5-user", "is_premium": True}

    app.dependency_overrides[require_active_access] = _fake_active_user
    client = TestClient(app)

    missing = client.get("/api/resume-defense/sessions/rd_missing/report")
    assert missing.status_code == 404
    assert "not found" in missing.json()["detail"].lower()

    app2 = FastAPI()
    app2.include_router(resume_defense.router, prefix="/api")
    client2 = TestClient(app2)

    unauthorized = client2.get("/api/resume-defense/sessions/rd_x/report")
    assert unauthorized.status_code == 401



def test_phase5_service_report_consistency(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORCV_RESUME_DEFENSE_DB_PATH", str(tmp_path / "resume_defense_phase5_service.db"))

    payload = {
        "resume_text": _sample_resume(),
        "analysis_output": _sample_analysis(),
        "job_description": "Analytics role requiring experimentation and stakeholder communication.",
        "ats_missing_keywords": ["experimentation"],
    }

    session = resume_defense_service.start_phase1_session(
        "phase5-user",
        ResumeDefenseStartRequest.model_validate(payload),
    )

    claim_map = {claim.claim_id: claim for claim in session.claims}
    for question in session.questions:
        claim = claim_map[question.claim_id]
        resume_defense_service.submit_phase2_answer(
            "phase5-user",
            session.session_id,
            ResumeDefenseAnswerSubmitRequest(
                question_id=question.question_id,
                answer_text=_answer_for_claim(claim.claim_text),
            ),
        )

    matrix = resume_defense_service.get_phase3_matrix("phase5-user", session.session_id)
    rewrites = resume_defense_service.get_phase4_rewrites("phase5-user", session.session_id)
    report = resume_defense_service.get_phase5_integrated_report("phase5-user", session.session_id)

    assert report.matrix.summary.total_claims == matrix.summary.total_claims
    assert report.rewrites.summary.targeted_claims == rewrites.summary.targeted_claims
    assert report.career_readiness.total_claims == matrix.summary.total_claims
    assert report.report.result_text
    assert report.report.result_html
