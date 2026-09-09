"""Public media delivery and Super Admin content image upload."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.auth import get_current_user
from app.exceptions import exception_to_http
from app.services.content_media_service import ContentMediaService

content_media_router = APIRouter()
content_media_service = ContentMediaService()


@content_media_router.post("/media", response_model=dict)
async def upload_content_image(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    try:
        return await content_media_service.upload_image(file, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@content_media_router.get("/media/{filename}")
async def get_content_image(filename: str):
    try:
        path, content_type = await content_media_service.get_image_path(filename)
        return FileResponse(path=str(path), media_type=content_type)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)
