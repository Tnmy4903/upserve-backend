"""Image storage for public Blog and Portfolio content."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import anyio
from fastapi import UploadFile

from app.config import ALLOWED_UPLOAD_EXTENSIONS, MAX_UPLOAD_FILE_SIZE, UPLOAD_STORAGE_ROOT
from app.exceptions import PermissionException, ResourceNotFoundException, ValidationException
from app.repositories.content_media_repo import ContentMediaRepository


class ContentMediaService:
    def __init__(self):
        self.repository = ContentMediaRepository()

    async def upload_image(self, file: UploadFile, current_user: dict) -> dict:
        if current_user.get("role") != "super_admin":
            raise PermissionException(message="Only Super Admin can upload content images.")
        original_name = Path(file.filename or "").name
        extension = Path(original_name).suffix.lower()
        allowed_images = ALLOWED_UPLOAD_EXTENSIONS & {".jpg", ".jpeg", ".png", ".webp"}
        if extension not in allowed_images:
            raise ValidationException("Only JPG, JPEG, PNG, and WEBP images are allowed.")
        if file.content_type and file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValidationException("Unsupported image content type.")
        content = bytearray()
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_FILE_SIZE:
                raise ValidationException(f"Image exceeds the maximum size of {MAX_UPLOAD_FILE_SIZE} bytes.")
        if not content:
            raise ValidationException("Empty images are not allowed.")
        upload_dir = Path(UPLOAD_STORAGE_ROOT) / "content"
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid4().hex}{extension}"
        saved_path = upload_dir / stored_name
        try:
            async with await anyio.open_file(str(saved_path), "wb") as buffer:
                await buffer.write(bytes(content))
        except OSError as exc:
            raise ValidationException("Unable to store image.") from exc
        metadata = {"originalFileName": original_name or stored_name, "storedFileName": stored_name, "filePath": str(saved_path), "contentType": file.content_type or "application/octet-stream", "fileSize": len(content), "uploadedBy": current_user["id"], "uploadedAt": datetime.now(timezone.utc)}
        try:
            media_id = await self.repository.create(metadata)
        except Exception as exc:
            try:
                saved_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ValidationException("Image metadata could not be saved.") from exc
        return {"id": media_id, "url": f"/api/content/media/{stored_name}", "fileName": original_name or stored_name, "contentType": metadata["contentType"], "fileSize": metadata["fileSize"]}

    async def get_image_path(self, filename: str) -> tuple[Path, str]:
        media = await self.repository.find_by_stored_filename(filename)
        if not media:
            raise ResourceNotFoundException("Content image")
        storage_root = (Path(UPLOAD_STORAGE_ROOT) / "content").resolve()
        path = Path(media.get("filePath", "")).resolve()
        try:
            path.relative_to(storage_root)
        except ValueError as exc:
            raise ValidationException("Invalid content image location.") from exc
        if not path.is_file():
            raise ResourceNotFoundException("Content image")
        return path, media.get("contentType", "application/octet-stream")
