from fastapi import APIRouter, Depends, HTTPException, status

from app.deps.auth import require_active_access
from app.schemas.resume_defense import (
    ResumeDefenseAnswerSubmitRequest,
    ResumeDefenseEvaluationResult,
    ResumeDefenseIntegratedReportResponse,
    ResumeDefenseMatrixResponse,
    ResumeDefenseRewriteResponse,
    ResumeDefenseSessionResponse,
    ResumeDefenseStartRequest,
)
from app.services import resume_defense_service

router = APIRouter(prefix="/resume-defense", tags=["resume-defense"])


@router.post("/sessions", response_model=ResumeDefenseSessionResponse)
def start_resume_defense_session(
    payload: ResumeDefenseStartRequest,
    user: dict = Depends(require_active_access),
):
    try:
        return resume_defense_service.start_phase1_session(str(user.get("id") or ""), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not start Resume Defense session.",
        ) from exc


@router.get("/sessions/{session_id}", response_model=ResumeDefenseSessionResponse)
def get_resume_defense_session(
    session_id: str,
    user: dict = Depends(require_active_access),
):
    session = resume_defense_service.get_phase1_session(str(user.get("id") or ""), session_id.strip())
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume Defense session not found.")
    return session




@router.get("/sessions/{session_id}/matrix", response_model=ResumeDefenseMatrixResponse)
def get_resume_defense_matrix(
    session_id: str,
    user: dict = Depends(require_active_access),
):
    try:
        return resume_defense_service.get_phase3_matrix(
            str(user.get("id") or ""),
            session_id.strip(),
        )
    except resume_defense_service.ResumeDefenseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate Resume Defense matrix.",
        ) from exc



@router.get("/sessions/{session_id}/rewrites", response_model=ResumeDefenseRewriteResponse)
def get_resume_defense_rewrites(
    session_id: str,
    user: dict = Depends(require_active_access),
):
    try:
        return resume_defense_service.get_phase4_rewrites(
            str(user.get("id") or ""),
            session_id.strip(),
        )
    except resume_defense_service.ResumeDefenseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate Resume Defense rewrites.",
        ) from exc



@router.get("/sessions/{session_id}/report", response_model=ResumeDefenseIntegratedReportResponse)
def get_resume_defense_integrated_report(
    session_id: str,
    user: dict = Depends(require_active_access),
):
    try:
        return resume_defense_service.get_phase5_integrated_report(
            str(user.get("id") or ""),
            session_id.strip(),
        )
    except resume_defense_service.ResumeDefenseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate Resume Defense integrated report.",
        ) from exc

@router.post("/sessions/{session_id}/answers", response_model=ResumeDefenseEvaluationResult)
def submit_resume_defense_answer(
    session_id: str,
    payload: ResumeDefenseAnswerSubmitRequest,
    user: dict = Depends(require_active_access),
):
    try:
        return resume_defense_service.submit_phase2_answer(
            str(user.get("id") or ""),
            session_id.strip(),
            payload,
        )
    except resume_defense_service.ResumeDefenseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except resume_defense_service.ResumeDefenseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not evaluate Resume Defense answer.",
        ) from exc
