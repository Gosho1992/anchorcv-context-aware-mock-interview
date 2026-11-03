from fastapi import APIRouter, Depends

from app.deps.auth import get_current_user
from app.services.llm import default_model, list_available_models

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
@router.get("/")
def get_models(user: dict = Depends(get_current_user)):
    """Models available with the API keys configured on this server."""
    return {"models": list_available_models(), "default": default_model()}
