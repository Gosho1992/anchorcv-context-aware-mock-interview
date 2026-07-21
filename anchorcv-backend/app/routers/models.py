from fastapi import APIRouter, Depends

from app.deps.auth import get_current_user
from app.services.llm import DEFAULT_MODEL, list_available_models

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
@router.get("/")
def get_models(user: dict = Depends(get_current_user)):
    """Models available with the API keys configured on this server."""
    models = list_available_models()
    default = DEFAULT_MODEL if any(m["id"] == DEFAULT_MODEL for m in models) else (
        models[0]["id"] if models else DEFAULT_MODEL
    )
    return {"models": models, "default": default}
