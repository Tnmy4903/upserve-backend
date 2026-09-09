from datetime import datetime, timezone
from pathlib import Path
import re
from uuid import uuid4

import anyio
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import UploadFile

from app.config import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MAX_UPLOAD_FILE_SIZE,
    UPLOAD_STORAGE_ROOT,
)
from app.exceptions import (
    DuplicateException,
    PermissionException,
    ResourceNotFoundException,
    ValidationException,
)
from app.logger import logger_upload
from app.repositories.project_repo import ProjectRepository
from app.repositories.upload_repo import UploadRepository
from app.services.activitylog_service import ActivityLogService
from app.services.notification_service import NotificationService
from app.services.project_service import ProjectService


class UploadService:
    """Project file upload business logic."""

    def __init__(self):
        self.upload_repo = UploadRepository()
        self.project_repo = ProjectRepository()
        self.activity_service = ActivityLogService()
        self.notification_service = NotificationService()
        self.project_service = ProjectService()

    @staticmethod
    def _sanitize_filename(filename: str | None) -> str:
        name = Path(filename or "").name
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip()
        return name or "upload.bin"

    @staticmethod
    def _serialize(upload: dict) -> dict:
        result = dict(upload)
        result["id"] = str(result.pop("_id"))
        for field in ("userId", "projectId"):
            if result.get(field) is not None:
                result[field] = str(result[field])
        result.pop("filePath", None)
        result.setdefault("clientVisible", True)
        result.setdefault("uploaderRole", None)
        return result

    async def _get_authorized_upload(
        self,
        upload_id: str,
        current_user: dict,
        require_client_visible: bool = True,
    ) -> tuple[dict, dict]:
        upload = await self.upload_repo.find_by_id(upload_id)
        if not upload:
            raise ResourceNotFoundException("Upload")

        project = await self.project_repo.find_by_id(
            str(upload.get("projectId"))
        )
        if not project:
            raise ResourceNotFoundException("Project")

        await self.project_service.ensure_project_access(project, current_user)
        if (
            require_client_visible
            and current_user.get("role") == "client"
            and not upload.get("clientVisible", True)
        ):
            raise PermissionException("Upload is not visible to the client.")
        return upload, project

    async def upload_file(
        self,
        file: UploadFile,
        project_id: str,
        current_user: dict,
        client_visible: bool = True,
    ) -> dict:
        if current_user.get("role") not in {
            "client",
            "sub_admin",
            "super_admin",
        }:
            raise PermissionException("Only project users can upload files.")

        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")
        await self.project_service.ensure_project_access(project, current_user)

        original_name = self._sanitize_filename(file.filename)
        extension = Path(original_name).suffix.lower()
        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            raise ValidationException("Unsupported file type.")

        chunks = []
        total_size = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_UPLOAD_FILE_SIZE:
                raise ValidationException(
                    f"File exceeds the maximum size of {MAX_UPLOAD_FILE_SIZE} bytes."
                )
            chunks.append(chunk)

        if total_size == 0:
            raise ValidationException("Empty files are not allowed.")
        content = b"".join(chunks)

        if current_user.get("role") == "client":
            client_visible = True

        upload_dir = Path(UPLOAD_STORAGE_ROOT)
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid4().hex}{extension}"
        saved_path = upload_dir / stored_name

        try:
            async with await anyio.open_file(str(saved_path), "wb") as buffer:
                await buffer.write(content)
        except OSError as exc:
            raise ValidationException("Unable to store uploaded file.") from exc

        upload_data = {
            "userId": ObjectId(current_user["id"]),
            "projectId": ObjectId(project_id),
            "fileName": original_name,
            "storedFileName": stored_name,
            "filePath": str(saved_path),
            "fileSize": len(content),
            "contentType": file.content_type,
            "extension": extension,
            "uploaderRole": current_user["role"],
            "clientVisible": client_visible,
            "uploadedAt": datetime.now(timezone.utc),
        }

        try:
            upload_id = await self.upload_repo.create(upload_data)
        except Exception as exc:
            try:
                saved_path.unlink(missing_ok=True)
            except OSError:
                logger_upload.exception("Failed to clean up orphaned upload file.")
            if isinstance(exc, DuplicateException):
                raise
            raise ValidationException(
                "Uploaded file metadata could not be saved."
            ) from exc

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="File Uploaded",
            entity="Upload",
            entity_id=upload_id,
            details={"projectId": project_id, "fileName": original_name},
        )
        await self.notification_service.notify_project_participants(
            project,
            notif_type="upload",
            title="New project file",
            message=f"{current_user['name']} uploaded {original_name}.",
            entity_id=upload_id,
            entity_type="Upload",
            event_key=f"upload_created:{upload_id}",
            exclude_user_id=current_user["id"],
            include_client=client_visible,
        )

        upload = await self.upload_repo.find_by_id(upload_id)
        logger_upload.info(f"Upload {upload_id} created for project {project_id}")
        return self._serialize(upload)

    async def get_project_uploads(
        self,
        project_id: str,
        current_user: dict,
    ) -> list[dict]:
        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")
        await self.project_service.ensure_project_access(project, current_user)
        uploads = await self.upload_repo.find_by_project(project_id)
        if current_user.get("role") == "client":
            uploads = [item for item in uploads if item.get("clientVisible", True)]
        return [self._serialize(item) for item in uploads]

    async def download_upload(
        self,
        upload_id: str,
        current_user: dict,
    ) -> Path:
        upload, _ = await self._get_authorized_upload(upload_id, current_user)
        return await self._file_path(upload)

    async def download_file(
        self,
        filename: str,
        current_user: dict,
    ) -> Path:
        """Backward-compatible filename download for authorized callers."""

        upload = await self.upload_repo.find_by_filename(filename)
        if not upload:
            raise ResourceNotFoundException("Upload")
        authorized, _ = await self._get_authorized_upload(
            str(upload["_id"]),
            current_user,
        )
        return await self._file_path(authorized)

    async def _file_path(self, upload: dict) -> Path:
        storage_root = Path(UPLOAD_STORAGE_ROOT).resolve()
        path = Path(upload.get("filePath", "")).resolve()
        try:
            path.relative_to(storage_root)
        except ValueError as exc:
            raise ValidationException("Invalid upload file location.") from exc
        if not path.exists() or not path.is_file():
            raise ResourceNotFoundException("File")
        return path

    async def get_all_uploads(self, current_user: dict) -> list[dict]:
        if current_user.get("role") == "super_admin":
            uploads = await self.upload_repo.get_all_sorted()
        elif current_user.get("role") == "sub_admin":
            projects = await self.project_service.get_all_projects(current_user)
            project_ids = []
            for project in projects:
                project_id = str(project["id"])
                project_ids.append(project_id)
                try:
                    project_ids.append(ObjectId(project_id))
                except (InvalidId, TypeError):
                    pass
            uploads = await self.upload_repo.find_many(
                {"projectId": {"$in": project_ids}}
            )
            uploads.sort(
                key=lambda upload: upload.get("uploadedAt"),
                reverse=True,
            )
        else:
            raise PermissionException("Upload access denied.")
        return [self._serialize(item) for item in uploads]

    async def delete_upload(self, upload_id: str, current_user: dict) -> bool:
        if current_user.get("role") != "super_admin":
            raise PermissionException("Only Super Admin can delete uploads.")
        upload, _ = await self._get_authorized_upload(
            upload_id,
            current_user,
            require_client_visible=False,
        )
        file_path = await self._file_path(upload)
        temporary_path = file_path.with_name(
            f".{file_path.name}.deleting-{uuid4().hex}"
        )
        try:
            file_path.replace(temporary_path)
        except OSError as exc:
            raise ValidationException("Unable to prepare file for deletion.") from exc

        try:
            deleted = await self.upload_repo.delete(upload_id)
        except Exception as exc:
            try:
                temporary_path.replace(file_path)
            except OSError:
                logger_upload.exception("Failed to restore upload after metadata deletion failure.")
            raise ValidationException("Upload metadata could not be deleted.") from exc

        if not deleted:
            try:
                temporary_path.replace(file_path)
            except OSError:
                logger_upload.exception("Failed to restore upload after metadata deletion failure.")
            raise ValidationException("Upload metadata could not be deleted.")

        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            logger_upload.exception("Upload metadata deleted but temporary file cleanup failed.")

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Upload Deleted",
            entity="Upload",
            entity_id=upload_id,
            details={"fileName": upload.get("fileName")},
        )
        logger_upload.info(f"Upload {upload_id} deleted")
        return True
