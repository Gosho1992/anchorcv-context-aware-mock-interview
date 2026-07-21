from anchor_shared import create_session_token, verify_session_token
from app.services.legacy_bridge import build_analysis_requirement, build_builder_requirement


def test_session_token_round_trip():
    token = create_session_token("user-123", "secret")
    payload = verify_session_token(token, "secret")
    assert payload is not None
    assert payload["user_id"] == "user-123"


def test_analysis_requirement_contains_intent_and_requirements():
    requirement = build_analysis_requirement("ATS_Optimization", "Focus on quantifying impact.")
    assert "INTENT: ATS_Optimization" in requirement
    assert "Focus on quantifying impact." in requirement


def test_builder_requirement_omits_disabled_sections():
    requirement = build_builder_requirement(
        target="Data Scientist",
        tone="Professional",
        language="English",
        length="Condensed",
        color_theme="#123456",
        sections={"summary": True, "projects": False},
    )
    assert "TARGET: Data Scientist" in requirement
    assert "COLOR_THEME: Custom|#123456" in requirement
    assert "OMIT SECTIONS: projects" in requirement
