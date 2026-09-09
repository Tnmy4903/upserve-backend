"""Project file upload API."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.auth import get_current_user
from app.api.dependencies import require_roles
from app.db.schemas import FileUploadOut
from app.exceptions import AuthorizationException, exception_to_http
from app.services.upload_service import UploadService


upload_router = APIRouter()
upload_service = UploadService()


def require_project_user(current_user: dict) -> None:
    if current_user.get("role") not in {"client", "sub_admin", "super_admin"}:
        raise AuthorizationException("Project access required.")


def require_admin(current_user: dict) -> None:
    if current_user.get("role") not in {"super_admin", "sub_admin"}:
        raise AuthorizationException("Admin access only.")


@upload_router.post("/", response_model=FileUploadOut)
async def upload_file(
    file: UploadFile = File(...),
    projectId: str = Form(...),
    clientVisible: bool = Form(True),
    current_user: dict = Depends(get_current_user),
):
    try:
        require_project_user(current_user)
        return await upload_service.upload_file(
            file=file,
            project_id=projectId,
            current_user=current_user,
            client_visible=clientVisible,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@upload_router.get("/projects/{project_id}", response_model=list[FileUploadOut])
async def get_project_uploads(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await upload_service.get_project_uploads(project_id, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@upload_router.get("/list", response_model=list[FileUploadOut])
async def get_all_uploads(current_user: dict = Depends(get_current_user)):
    try:
        require_admin(current_user)
        return await upload_service.get_all_uploads(current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@upload_router.get("/{upload_id}/download")
async def download_upload(
    upload_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        require_project_user(current_user)
        file_path = await upload_service.download_upload(upload_id, current_user)
        return FileResponse(path=str(file_path))
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@upload_router.get("/download/{filename}")
async def download_file_legacy(
    filename: str,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    try:
        file_path = await upload_service.download_file(filename, current_user)
        return FileResponse(path=str(file_path), filename=filename)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@upload_router.delete("/{upload_id}")
async def delete_upload(
    upload_id: str,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    try:
        await upload_service.delete_upload(upload_id, current_user)
        return {"message": "Upload deleted successfully."}
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)
