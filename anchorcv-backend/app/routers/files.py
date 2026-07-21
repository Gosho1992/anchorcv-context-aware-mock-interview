from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse

from app.deps.auth import get_current_premium_user
from app.services import legacy_bridge

router = APIRouter(prefix="/files", tags=["files"])


@router.get("")
def list_files(user=Depends(get_current_premium_user)):
    return {"files": legacy_bridge.storage_list(user["id"])}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), user=Depends(get_current_premium_user)):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File is required.")
    ok, result = legacy_bridge.storage_upload(
        user["id"],
        file.filename,
        file_bytes,
        file.content_type or "application/octet-stream",
    )
    if not ok:
        raise HTTPException(status_code=400, detail=result)
    return {"path": result}


@router.get("/{file_id}/download")
def download_file(file_id: str, user=Depends(get_current_premium_user)):
    record = legacy_bridge.storage_get_record(user["id"], file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found.")

    signed_url = legacy_bridge.storage_download_url(user["id"], record["filename"])
    if not signed_url:
        raise HTTPException(status_code=404, detail="Download link unavailable.")
    return RedirectResponse(signed_url)


@router.delete("/{file_id}")
def delete_file(file_id: str, user=Depends(get_current_premium_user)):
    if not legacy_bridge.storage_delete_by_id(user["id"], file_id):
        raise HTTPException(status_code=404, detail="File not found.")
    return {"ok": True}
