from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import anyio
from fastapi import UploadFile

from app.config import ALLOWED_UPLOAD_EXTENSIONS, MAX_UPLOAD_FILE_SIZE, UPLOAD_STORAGE_ROOT
from app.db.schemas import RequirementStatus
from app.exceptions import (
    AuthorizationException,
    DuplicateException,
    ResourceNotFoundException,
    ValidationException,
)
from app.logger import logger_requirement
from app.repositories.lead_repo import LeadRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.requirement_repo import RequirementRepository
from app.repositories.user_repo import UserRepository
from app.services.activitylog_service import ActivityLogService
from app.services.notification_service import NotificationService


class RequirementService:
    """Service for requirement management."""

    def __init__(self):
        self.req_repo = RequirementRepository()
        self.lead_repo = LeadRepository()
        self.project_repo = ProjectRepository()
        self.user_repo = UserRepository()
        self.activity_service = ActivityLogService()
        self.notification_service = NotificationService()

    @staticmethod
    def _lead_has_assignee(lead: dict, user_id: str | None) -> bool:
        if not user_id:
            return False
        assigned_ids = {str(value) for value in lead.get("assignedToIds", []) if value}
        if lead.get("assignedTo"):
            assigned_ids.add(str(lead["assignedTo"]))
        return str(user_id) in assigned_ids

    @staticmethod
    def _serialize_requirement(requirement: dict) -> dict:
        """Normalize requirement identifiers for API responses, including legacy records."""

        requirement["id"] = str(requirement["_id"])
        for field in ("leadId", "projectId", "approvedBy", "lastUpdatedBy"):
            if requirement.get(field) is not None:
                requirement[field] = str(requirement[field])
        return requirement

    async def _add_history_actor_names(self, requirement: dict) -> None:
        """Attach safe display names to requirement history events."""

        history = requirement.get("history") or []
        actor_ids = {
            str(event.get("actorId"))
            for event in history
            if event.get("actorId")
        }
        if not actor_ids:
            return

        names: dict[str, str] = {}
        for actor_id in actor_ids:
            actor = await self.user_repo.find_by_id(actor_id)
            if actor and actor.get("name"):
                names[actor_id] = actor["name"]

        for event in history:
            actor_id = event.get("actorId")
            if actor_id and str(actor_id) in names:
                event["actorName"] = names[str(actor_id)]

    async def _ensure_project_mutation_allowed(
        self,
        requirement: dict,
    ) -> None:
        """Keep requirements actionable throughout the project lifecycle.

        The requirement itself is the lock boundary: once approved, clients
        cannot edit it, while a Super Admin can still request changes. Project
        status must not prevent review or revision later in delivery.
        """
        return None

    @staticmethod
    def _history_entry(
        requirement: dict,
        action: str,
        current_user: dict,
        changes: dict | None = None,
        requirement_id: str | None = None,
    ) -> dict:
        return {
            "requirementId": requirement_id or str(requirement.get("_id")),
            "projectId": str(requirement["projectId"]) if requirement.get("projectId") is not None else None,
            "leadId": str(requirement["leadId"]) if requirement.get("leadId") is not None else None,
            "action": action,
            "actorId": current_user["id"],
            "actorRole": current_user.get("role"),
            "timestamp": datetime.now(timezone.utc),
            "changes": changes or {},
        }

    async def _load_requirement_relations(
        self,
        requirement: dict,
    ) -> tuple[dict | None, dict | None]:
        """Load the lead and project referenced by a requirement."""

        lead = None
        project = None

        if requirement.get("leadId"):
            lead = await self.lead_repo.find_by_id(
                str(requirement["leadId"])
            )

        if requirement.get("projectId"):
            project = await self.project_repo.find_by_id(
                str(requirement["projectId"])
            )

        if lead and project is None:
            project = await self.project_repo.find_one(
                {
                    "leadId": str(requirement.get("leadId")),
                }
            )

        return lead, project

    async def _require_requirement_access(
        self,
        requirement: dict,
        current_user: dict,
        allow_write: bool = False,
    ) -> None:
        """Enforce Super Admin, Sub Admin, and client ownership rules."""

        role = current_user.get("role")
        if role == "super_admin":
            return

        lead, project = await self._load_requirement_relations(
            requirement
        )

        if role == "client":
            if project and str(project.get("userId")) == current_user.get("id"):
                return

            raise AuthorizationException(
                "Clients can only access requirements for their own projects."
            )

        if role == "sub_admin":
            if lead and self._lead_has_assignee(lead, current_user.get("id")):
                return

            if project:
                if str(project.get("assignedSubAdmin")) == current_user.get("id"):
                    return

                project_lead_id = project.get("leadId")
                if (
                    lead is None
                    and project_lead_id
                ):
                    lead = await self.lead_repo.find_by_id(
                        str(project_lead_id)
                    )

                if (
                    lead
                    and self._lead_has_assignee(lead, current_user.get("id"))
                ):
                    return

            raise AuthorizationException(
                "Sub Admins can only access assigned requirements."
            )

        raise AuthorizationException(
            "You are not authorized to access this requirement."
        )

    async def _validate_creation_relationships(
        self,
        lead_id: str | None,
        project_id: str | None,
    ) -> tuple[dict | None, dict | None]:
        """Validate parent existence and lead/project consistency."""

        if not lead_id and not project_id:
            raise ValidationException(
                "Either lead_id or project_id must be provided."
            )

        lead = None
        project = None

        if lead_id:
            lead = await self.lead_repo.find_by_id(lead_id)
            if not lead:
                raise ResourceNotFoundException("Lead")
            if lead.get("stage") == "Lost":
                raise ValidationException(
                    "Requirements cannot be created for a lost lead."
                )

        if project_id:
            project = await self.project_repo.find_by_id(project_id)
            if not project:
                raise ResourceNotFoundException("Project")
            if project.get("status") in {"delivered", "completed"}:
                raise ValidationException(
                    "Requirements cannot be created after project delivery."
                )

            if project.get("leadId") and lead is None:
                lead = await self.lead_repo.find_by_id(
                    str(project["leadId"])
                )
                if not lead:
                    raise ResourceNotFoundException("Lead")
                if lead.get("stage") == "Lost":
                    raise ValidationException(
                        "Requirements cannot be created for a lost lead."
                    )

        if lead and project:
            resolved_lead_id = lead_id or lead.get("_id")
            if project.get("leadId") and str(project.get("leadId")) != str(resolved_lead_id):
                raise ValidationException(
                    "Lead and project do not belong to the same business flow."
                )

        if lead and project is None:
            project = await self.project_repo.find_one(
                {"leadId": str(lead_id)}
            )
            if project and project.get("status") in {"delivered", "completed"}:
                raise ValidationException(
                    "Requirements cannot be created after project delivery."
                )

        return lead, project

    async def create_requirement(
        self,
        current_user: dict,
        lead_id: str | None = None,
        project_id: str | None = None,
        created_by: str | None = None,
        **req_data,
    ) -> dict:
        """Create requirement documentation."""

        lead, project = await self._validate_creation_relationships(
            lead_id,
            project_id,
        )

        if current_user.get("role") == "client" and not project_id:
            raise ValidationException(
                "Clients must create requirements from one of their projects."
            )

        if project and project.get("leadId"):
            derived_lead_id = str(project["leadId"])
            if lead_id and str(lead_id) != derived_lead_id:
                raise ValidationException(
                    "Lead and project do not belong to the same business flow."
                )
            lead_id = derived_lead_id

        if project and project.get("status") not in {
            "pending",
            "in_progress",
            "testing",
            "deployment",
        }:
            raise ValidationException(
                "Requirements cannot be created for this project status."
            )

        if lead_id and await self.req_repo.exists_by_lead(lead_id):
            raise DuplicateException(
                "Requirement already exists for this lead."
            )

        if project_id and await self.req_repo.exists_by_project(project_id):
            raise DuplicateException(
                "Requirement already exists for this project."
            )

        relationship = {
            "leadId": lead_id,
            "projectId": project_id,
        }
        relationship_requirement = {
            **relationship,
        }

        await self._require_requirement_access(
            relationship_requirement,
            current_user,
            allow_write=True,
        )

        req_data["leadId"] = lead_id
        req_data["projectId"] = project_id
        req_data["status"] = RequirementStatus.PENDING.value
        req_data["approvedBy"] = None
        req_data["approvedAt"] = None
        req_data["remarks"] = None
        req_data["lastUpdatedBy"] = current_user["id"]
        req_data["lastUpdatedAt"] = datetime.now(
            timezone.utc
        )

        req_id = await self.req_repo.create_with_history(
            req_data,
            self._history_entry(
                {
                    "_id": "pending",
                    "projectId": req_data.get("projectId"),
                    "leadId": req_data.get("leadId"),
                },
                "created",
                current_user,
                changes={"snapshot": dict(req_data)},
            ),
        )

        created_requirement = await self.req_repo.find_by_id(req_id)
        if not created_requirement:
            raise ResourceNotFoundException("Requirement")
        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Requirement Created",
            entity="Requirement",
            entity_id=req_id,
        )
        await self.notification_service.notify_admins(
            notif_type="requirement",
            title="New requirement",
            message="A new requirement is ready for review.",
            entity_id=req_id,
            entity_type="Requirement",
            event_key=f"requirement_created:{req_id}",
            exclude_user_id=current_user["id"],
        )

        logger_requirement.info(
            f"Requirement created: {req_id}"
        )

        self._serialize_requirement(created_requirement)

        return created_requirement

    async def update_requirement(
        self,
        requirement_id: str,
        current_user: dict,
        updated_by: str,
        **updates,
    ) -> dict:
        """Update a requirement."""

        requirement = await self.req_repo.find_by_id(
            requirement_id
        )

        if not requirement:
            raise ResourceNotFoundException(
                "Requirement"
            )

        await self._require_requirement_access(
            requirement,
            current_user,
            allow_write=True,
        )

        await self._ensure_project_mutation_allowed(requirement)

        if (
            requirement.get("status")
            == RequirementStatus.APPROVED.value
        ):
            raise ValidationException(
                "Approved requirement cannot be edited. Request changes first."
            )

        if isinstance(updates.get("deadline"), date):
            updates["deadline"] = updates["deadline"].isoformat()

        updates["status"] = RequirementStatus.PENDING.value
        updates["approvedBy"] = None
        updates["approvedAt"] = None
        changes = {
            field: {"previous": requirement.get(field), "new": value}
            for field, value in updates.items()
        }
        updates["lastUpdatedBy"] = current_user["id"]
        updates["lastUpdatedAt"] = datetime.now(
            timezone.utc
        )

        updated = await self.req_repo.update_with_history(
            requirement_id,
            updates,
            self._history_entry(
                requirement,
                "updated",
                current_user,
                changes=changes,
                requirement_id=requirement_id,
            ),
            expected_status=requirement.get("status", RequirementStatus.PENDING.value),
        )

        if not updated:
            raise ValidationException(
                "Failed to update requirement."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Requirement Updated",
            entity="Requirement",
            entity_id=requirement_id,
        )
        await self.notification_service.notify_admins(
            notif_type="requirement",
            title="Requirement updated",
            message="A requirement was updated and is ready for review again.",
            entity_id=requirement_id,
            entity_type="Requirement",
            event_key=f"requirement_updated:{requirement_id}:{datetime.now(timezone.utc).isoformat()}",
            exclude_user_id=current_user["id"],
        )

        logger_requirement.info(
            f"Requirement updated: {requirement_id}"
        )

        updated_requirement = await self.req_repo.find_by_id(
            requirement_id
        )

        self._serialize_requirement(updated_requirement)

        return updated_requirement

    async def upload_attachment(
        self,
        requirement_id: str,
        file: UploadFile,
        current_user: dict,
    ) -> dict:
        """Store one optional PDF reference on a requirement."""

        requirement = await self.req_repo.find_by_id(requirement_id)
        if not requirement:
            raise ResourceNotFoundException("Requirement")
        await self._require_requirement_access(requirement, current_user, allow_write=True)
        await self._ensure_project_mutation_allowed(requirement)
        if requirement.get("status") == RequirementStatus.APPROVED.value:
            raise ValidationException("Approved requirement cannot be changed. Request changes first.")

        original_name = Path(file.filename or "").name.strip()
        extension = Path(original_name).suffix.lower()
        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
            raise ValidationException(f"This file type is not supported. Allowed extensions: {allowed}.")

        content = bytearray()
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_FILE_SIZE:
                raise ValidationException(f"File exceeds the maximum size of {MAX_UPLOAD_FILE_SIZE} bytes.")
        if not content:
            raise ValidationException("Empty file attachments are not allowed.")

        upload_dir = Path(UPLOAD_STORAGE_ROOT) / "requirements"
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid4().hex}{extension}"
        saved_path = upload_dir / stored_name
        try:
            async with await anyio.open_file(str(saved_path), "wb") as output:
                await output.write(bytes(content))
        except OSError as exc:
            raise ValidationException("Unable to store the requirement attachment.") from exc

        old_attachment = requirement.get("attachment") or {}
        attachment = {
            "fileName": original_name or f"requirement{extension}",
            "storedFileName": stored_name,
            "contentType": file.content_type or "application/octet-stream",
            "fileSize": len(content),
            "uploadedAt": datetime.now(timezone.utc),
            "uploadedBy": current_user["id"],
        }
        updated = await self.req_repo.update_with_history(
            requirement_id,
            {"attachment": attachment},
            self._history_entry(
                requirement,
                "attachment_uploaded",
                current_user,
                changes={"fileName": attachment["fileName"]},
                requirement_id=requirement_id,
            ),
            expected_status=requirement.get("status", RequirementStatus.PENDING.value),
        )
        if not updated:
            saved_path.unlink(missing_ok=True)
            raise ValidationException("Requirement changed before the file could be attached.")

        old_stored_name = old_attachment.get("storedFileName")
        if old_stored_name:
            (upload_dir / Path(str(old_stored_name)).name).unlink(missing_ok=True)

        refreshed = await self.req_repo.find_by_id(requirement_id)
        if not refreshed:
            raise ResourceNotFoundException("Requirement")
        self._serialize_requirement(refreshed)
        return refreshed

    async def download_attachment(
        self,
        requirement_id: str,
        current_user: dict,
    ) -> tuple[Path, str, str]:
        """Return an authorized requirement attachment path."""

        requirement = await self.req_repo.find_by_id(requirement_id)
        if not requirement:
            raise ResourceNotFoundException("Requirement")
        await self._require_requirement_access(requirement, current_user)
        attachment = requirement.get("attachment") or {}
        stored_name = Path(str(attachment.get("storedFileName") or "")).name
        if not stored_name:
            raise ResourceNotFoundException("Requirement attachment")
        file_path = (Path(UPLOAD_STORAGE_ROOT) / "requirements" / stored_name).resolve()
        upload_root = (Path(UPLOAD_STORAGE_ROOT) / "requirements").resolve()
        if upload_root not in file_path.parents or not file_path.is_file():
            raise ResourceNotFoundException("Requirement attachment")
        return file_path, attachment.get("fileName") or "requirement-file", attachment.get("contentType") or "application/octet-stream"

    async def approve_requirement(
        self,
        requirement_id: str,
        current_user: dict,
        approved_by: str,
        remarks: str | None = None,
    ) -> dict:
        """Approve a requirement."""

        requirement = await self.req_repo.find_by_id(
            requirement_id
        )

        if not requirement:
            raise ResourceNotFoundException(
                "Requirement"
            )

        if current_user.get("role") != "super_admin":
            raise AuthorizationException(
                "Only Super Admin can approve requirements."
            )

        await self._require_requirement_access(
            requirement,
            current_user,
            allow_write=True,
        )
        await self._ensure_project_mutation_allowed(requirement)

        if (
            requirement.get("status")
            == RequirementStatus.APPROVED.value
        ):
            raise ValidationException(
                "Requirement is already approved."
            )

        updated = await self.req_repo.update_with_history(
            requirement_id,
            {
                "status": RequirementStatus.APPROVED.value,
                "approvedBy": current_user["id"],
                "approvedAt": datetime.now(
                    timezone.utc
                ),
                "remarks": remarks,
                "lastUpdatedBy": current_user["id"],
                "lastUpdatedAt": datetime.now(
                    timezone.utc
                ),
            },
            self._history_entry(
                requirement,
                "approved",
                current_user,
                changes={
                    "status": {
                        "previous": requirement.get("status"),
                        "new": RequirementStatus.APPROVED.value,
                    },
                    "remarks": {
                        "previous": requirement.get("remarks"),
                        "new": remarks,
                    },
                },
                requirement_id=requirement_id,
            ),
            expected_status=requirement.get("status", RequirementStatus.PENDING.value),
        )

        if not updated:
            raise ValidationException(
                "Requirement status changed before approval completed."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Requirement Approved",
            entity="Requirement",
            entity_id=requirement_id,
        )
        await self.notification_service.notify_admins(
            notif_type="requirement",
            title="Requirement approved",
            message="A requirement was approved and is available as optional quotation context.",
            entity_id=requirement_id,
            entity_type="Requirement",
            event_key=f"requirement_approved:{requirement_id}",
            exclude_user_id=current_user["id"],
        )

        logger_requirement.info(
            f"Requirement approved: {requirement_id}"
        )

        approved_requirement = await self.req_repo.find_by_id(
            requirement_id
        )

        self._serialize_requirement(approved_requirement)

        return approved_requirement

    async def request_changes(
        self,
        requirement_id: str,
        current_user: dict,
        remarks: str,
    ) -> dict:
        """Request changes to a requirement."""

        requirement = await self.req_repo.find_by_id(
            requirement_id
        )

        if not requirement:
            raise ResourceNotFoundException(
                "Requirement"
            )

        if current_user.get("role") != "super_admin":
            raise AuthorizationException(
                "Only Super Admin can request requirement changes."
            )

        await self._require_requirement_access(
            requirement,
            current_user,
            allow_write=True,
        )
        await self._ensure_project_mutation_allowed(requirement)

        if (
            requirement.get("status")
            == RequirementStatus.CHANGES_REQUESTED.value
        ):
            raise ValidationException(
                "Changes have already been requested."
            )

        updated = await self.req_repo.update_with_history(
            requirement_id,
            {
                "status": RequirementStatus.CHANGES_REQUESTED.value,
                "remarks": remarks,
                "approvedBy": None,
                "approvedAt": None,
                "lastUpdatedBy": current_user["id"],
                "lastUpdatedAt": datetime.now(
                    timezone.utc
                ),
            },
            self._history_entry(
                requirement,
                "changes_requested",
                current_user,
                changes={
                    "status": {
                        "previous": requirement.get("status"),
                        "new": RequirementStatus.CHANGES_REQUESTED.value,
                    },
                    "remarks": {
                        "previous": requirement.get("remarks"),
                        "new": remarks,
                    },
                },
                requirement_id=requirement_id,
            ),
            expected_status=requirement.get("status", RequirementStatus.PENDING.value),
        )

        if not updated:
            raise ValidationException(
                "Requirement status changed before the change request completed."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Requirement Changes Requested",
            entity="Requirement",
            entity_id=requirement_id,
        )
        await self.notification_service.notify_admins(
            notif_type="requirement",
            title="Requirement changes requested",
            message="Changes were requested on a requirement.",
            entity_id=requirement_id,
            entity_type="Requirement",
            event_key=f"requirement_changes_requested:{requirement_id}",
            exclude_user_id=current_user["id"],
        )

        logger_requirement.info(
            f"Changes requested for requirement: {requirement_id}"
        )

        updated_requirement = await self.req_repo.find_by_id(
            requirement_id
        )

        self._serialize_requirement(updated_requirement)

        return updated_requirement

    async def get_requirement(
        self,
        requirement_id: str,
        current_user: dict,
    ) -> dict:
        """Return a requirement."""

        requirement = await self.req_repo.find_by_id(
            requirement_id
        )

        if not requirement:
            raise ResourceNotFoundException(
                "Requirement"
            )

        await self._require_requirement_access(
            requirement,
            current_user,
        )

        self._serialize_requirement(requirement)
        await self._add_history_actor_names(requirement)

        return requirement

    async def delete_requirement(
        self,
        requirement_id: str,
        current_user: dict,
    ) -> dict:
        """Delete a requirement."""

        requirement = await self.req_repo.find_by_id(
            requirement_id
        )

        if not requirement:
            raise ResourceNotFoundException(
                "Requirement"
            )

        actor = await self.user_repo.find_by_id(
            str(current_user.get("id")) if current_user else ""
        )
        if (
            not actor
            or not actor.get("isActive", True)
            or actor.get("role") != "super_admin"
        ):
            raise AuthorizationException(
                "Only an active Super Admin can delete requirements."
            )

        await self._require_requirement_access(
            requirement,
            current_user,
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Requirement Deletion Attempted",
            entity="Requirement",
            entity_id=requirement_id,
            details={
                "projectId": requirement.get("projectId"),
                "leadId": requirement.get("leadId"),
                "status": requirement.get("status"),
            },
        )

        await self._ensure_project_mutation_allowed(requirement)

        if requirement.get("status") == RequirementStatus.APPROVED.value:
            raise ValidationException(
                "Approved requirement cannot be deleted."
            )

        deleted = await self.req_repo.delete(
            requirement_id
        )

        if not deleted:
            raise ValidationException(
                "Failed to delete requirement."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Requirement Deleted",
            entity="Requirement",
            entity_id=requirement_id,
            details={
                "projectId": requirement.get("projectId"),
                "leadId": requirement.get("leadId"),
                "previousStatus": requirement.get("status"),
            },
        )

        logger_requirement.info(
            f"Requirement deleted: {requirement_id}"
        )

        return {
            "message": "Requirement deleted successfully."
        }

    async def get_lead_requirements(
        self,
        lead_id: str,
        current_user: dict,
    ) -> dict:
        """Return requirements for a lead."""

        lead = await self.lead_repo.find_by_id(lead_id)
        if not lead:
            raise ResourceNotFoundException("Lead")

        requirement = await self.req_repo.find_by_lead(
            lead_id
        )

        if not requirement:
            raise ResourceNotFoundException(
                "Requirement"
            )

        await self._require_requirement_access(
            requirement,
            current_user,
        )

        self._serialize_requirement(requirement)
        await self._add_history_actor_names(requirement)

        return requirement

    async def get_project_requirements(
        self,
        project_id: str,
        current_user: dict,
    ) -> dict:
        """Return requirements for a project."""

        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")

        requirement = await self.req_repo.find_by_project(
            project_id
        )

        if not requirement and project.get("leadId"):
            requirement = await self.req_repo.find_by_lead(
                project["leadId"]
            )

        if not requirement:
            raise ResourceNotFoundException(
                "Requirement"
            )

        access_requirement = requirement
        if not requirement.get("projectId"):
            access_requirement = {
                **requirement,
                "projectId": project_id,
            }

        await self._require_requirement_access(
            access_requirement,
            current_user,
        )

        self._serialize_requirement(requirement)
        await self._add_history_actor_names(requirement)

        return requirement
