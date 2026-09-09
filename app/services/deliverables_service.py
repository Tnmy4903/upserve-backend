from datetime import date, datetime, timezone

from app.db.schemas import DeliverableStatus
from app.exceptions import (
    PermissionException,
    ResourceNotFoundException,
    ValidationException,
)
from app.logger import logger_deliverables
from app.repositories.deliverables_repo import DeliverablesRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.timeline_repo import TimelineRepository
from app.repositories.user_repo import UserRepository
from app.services.activitylog_service import ActivityLogService
from app.services.notification_service import NotificationService
from app.services.project_service import ProjectService


class DeliverablesService:
    """Business logic for independent project deliverables."""

    _allowed_transitions = {
        "pending": {"in_progress", "blocked", "cancelled"},
        "in_progress": {"completed", "blocked", "cancelled"},
        "blocked": {"in_progress", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    }

    def __init__(self):
        self.deliverables_repo = DeliverablesRepository()
        self.project_repo = ProjectRepository()
        self.user_repo = UserRepository()
        self.activity_service = ActivityLogService()
        self.notification_service = NotificationService()
        self.project_service = ProjectService()
        self.timeline_repo = TimelineRepository()

    @staticmethod
    def _require_admin(current_user: dict) -> None:
        if current_user.get("role") not in {"super_admin", "sub_admin"}:
            raise PermissionException("Only administrators can manage deliverables.")

    async def _get_deliverable(self, deliverable_id: str) -> dict:
        deliverable = await self.deliverables_repo.find_by_id(deliverable_id)
        if not deliverable:
            raise ResourceNotFoundException("Deliverable")
        return deliverable

    async def _get_authorized_deliverable(
        self,
        deliverable_id: str,
        current_user: dict,
    ) -> tuple[dict, dict]:
        deliverable = await self._get_deliverable(deliverable_id)
        project = await self.project_repo.find_by_id(
            str(deliverable.get("projectId"))
        )
        if not project:
            raise ResourceNotFoundException("Project")
        await self.project_service.ensure_project_access(project, current_user)
        return deliverable, project

    @staticmethod
    def _output(deliverable: dict, current_user: dict) -> dict:
        result = dict(deliverable)
        result["id"] = str(result.pop("_id"))
        for field in ("projectId", "createdBy", "updatedBy", "completedBy"):
            if result.get(field) is not None:
                result[field] = str(result[field])
        if current_user.get("role") == "client":
            if not result.get("clientVisible", True):
                raise PermissionException("Deliverable is not visible to the client.")
            result.pop("credentials", None)
        return result

    async def create_deliverable(
        self,
        project_id: str,
        current_user: dict,
        **deliverable_data,
    ) -> dict:
        self._require_admin(current_user)
        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")
        await self.project_service.ensure_project_access(project, current_user)
        if project.get("status") not in {"pending", "in_progress", "testing", "deployment"}:
            raise ValidationException("Deliverables cannot be created for this project status.")

        title = deliverable_data.get("title", "").strip()
        if not title:
            raise ValidationException("Deliverable title is required.")
        if isinstance(deliverable_data.get("dueDate"), date) and not isinstance(deliverable_data.get("dueDate"), datetime):
            deliverable_data["dueDate"] = deliverable_data["dueDate"].isoformat()
        deliverable_data.update({
            "projectId": project_id,
            "title": title,
            "titleNormalized": title.casefold(),
            "status": DeliverableStatus.PENDING.value,
            "clientVisible": deliverable_data.get("clientVisible", True),
            "createdBy": current_user["id"],
            "updatedBy": current_user["id"],
            "completedAt": None,
            "completedBy": None,
        })
        deliverable_id = await self.deliverables_repo.create(deliverable_data)
        await self.timeline_repo.create_system_event(
            project_id=project_id,
            title="Deliverable Created",
            description=f"Deliverable '{title}' was created.",
            created_by=current_user["id"],
            event_type="deliverable_created",
            event_key=f"deliverable_created:{deliverable_id}",
        )
        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Deliverable Created",
            entity="Deliverable",
            entity_id=deliverable_id,
        )
        await self.notification_service.notify_project_participants(
            project,
            notif_type="deliverable",
            title="Deliverable created",
            message=f"Deliverable '{title}' was added to the project.",
            entity_id=deliverable_id,
            entity_type="Deliverable",
            event_key=f"deliverable_created:{deliverable_id}",
            exclude_user_id=current_user["id"],
            include_client=bool(deliverable_data.get("clientVisible", True)),
        )
        created = await self._get_deliverable(deliverable_id)
        logger_deliverables.info(f"Deliverable created: {deliverable_id}")
        return self._output(created, current_user)

    async def get_deliverables(self, project_id: str, current_user: dict) -> list[dict]:
        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")
        await self.project_service.ensure_project_access(project, current_user)
        deliverables = await self.deliverables_repo.find_by_project(project_id)
        if current_user.get("role") == "client":
            deliverables = [item for item in deliverables if item.get("clientVisible", True)]
        return [self._output(item, current_user) for item in deliverables]

    async def get_deliverable(self, deliverable_id: str, current_user: dict) -> dict:
        deliverable, _ = await self._get_authorized_deliverable(deliverable_id, current_user)
        return self._output(deliverable, current_user)

    async def update_deliverable(self, deliverable_id: str, current_user: dict, **updates) -> dict:
        self._require_admin(current_user)
        deliverable, _ = await self._get_authorized_deliverable(deliverable_id, current_user)
        if deliverable.get("status") in {"completed", "cancelled"}:
            raise ValidationException("Completed or cancelled deliverables cannot be modified.")
        if "title" in updates:
            title = updates["title"].strip()
            if not title:
                raise ValidationException("Deliverable title is required.")
            updates["title"] = title
            updates["titleNormalized"] = title.casefold()
        if isinstance(updates.get("dueDate"), date) and not isinstance(updates.get("dueDate"), datetime):
            updates["dueDate"] = updates["dueDate"].isoformat()
        updates["updatedBy"] = current_user["id"]
        if not await self.deliverables_repo.update(deliverable_id, updates):
            raise ValidationException("Failed to update deliverable.")
        await self.activity_service.log_activity(
            user_id=current_user["id"], user_role=current_user["role"],
            action="Deliverable Updated", entity="Deliverable", entity_id=deliverable_id,
        )
        return await self.get_deliverable(deliverable_id, current_user)

    async def update_status(self, deliverable_id: str, status: str, current_user: dict) -> dict:
        self._require_admin(current_user)
        deliverable, project = await self._get_authorized_deliverable(deliverable_id, current_user)
        current_status = deliverable.get("status", "pending")
        if current_status == status:
            if status == DeliverableStatus.COMPLETED.value:
                event_key = f"deliverable_completed:{deliverable_id}"
                if not await self.timeline_repo.find_system_event(
                    str(deliverable["projectId"]),
                    event_key,
                ):
                    try:
                        await self.timeline_repo.create_system_event(
                            project_id=str(deliverable["projectId"]),
                            title="Deliverable Completed",
                            description="A project deliverable was completed.",
                            created_by=str(deliverable.get("completedBy") or current_user["id"]),
                            event_type="deliverable_completed",
                            event_key=event_key,
                        )
                    except Exception:
                        logger_deliverables.exception(
                            "Failed to recover completion event for deliverable %s",
                            deliverable_id,
                        )
                        raise
                    return await self.get_deliverable(deliverable_id, current_user)
            raise ValidationException(
                f"Deliverable is already in '{status}' status."
            )
        if status not in self._allowed_transitions.get(current_status, set()):
            raise ValidationException(
                f"Cannot change deliverable status from {current_status} to {status}."
            )
        updates = {"status": status, "updatedBy": current_user["id"]}
        if status == "completed":
            updates["completedAt"] = datetime.now(timezone.utc)
            updates["completedBy"] = current_user["id"]
        updated = await self.deliverables_repo.update_status_if_current(
            deliverable_id,
            current_status,
            updates,
        )
        if not updated:
            raise ValidationException(
                "Deliverable status changed before this request completed."
            )
        if status == "completed":
            try:
                await self.timeline_repo.create_system_event(
                    project_id=str(deliverable["projectId"]),
                    title="Deliverable Completed",
                    description="A project deliverable was completed.",
                    created_by=current_user["id"],
                    event_type="deliverable_completed",
                    event_key=f"deliverable_completed:{deliverable_id}",
                )
            except Exception:
                logger_deliverables.exception(
                    "Deliverable status updated but completion event recording failed for %s",
                    deliverable_id,
                )
                raise
        await self.activity_service.log_activity(
            user_id=current_user["id"], user_role=current_user["role"],
            action="Deliverable Completed" if status == "completed" else "Deliverable Status Changed",
            entity="Deliverable", entity_id=deliverable_id,
            details={"previousStatus": current_status, "newStatus": status},
        )
        await self.notification_service.notify_project_participants(
            project,
            notif_type="deliverable",
            title="Deliverable status updated",
            message=f"Deliverable '{deliverable.get('title', 'Deliverable')}' moved to {status.replace('_', ' ')}.",
            entity_id=deliverable_id,
            entity_type="Deliverable",
            event_key=f"deliverable_status:{deliverable_id}:{status}",
            exclude_user_id=current_user["id"],
            include_client=bool(deliverable.get("clientVisible", True)),
        )
        return await self.get_deliverable(deliverable_id, current_user)

    async def delete_deliverable(self, deliverable_id: str, current_user: dict) -> dict:
        if current_user.get("role") != "super_admin":
            raise PermissionException("Only Super Admin can delete deliverables.")
        deliverable, _ = await self._get_authorized_deliverable(deliverable_id, current_user)
        if not await self.deliverables_repo.delete(deliverable_id):
            raise ValidationException("Failed to delete deliverable.")
        await self.activity_service.log_activity(
            user_id=current_user["id"], user_role=current_user["role"],
            action="Deliverable Deleted", entity="Deliverable", entity_id=deliverable_id,
            details={"projectId": str(deliverable.get("projectId"))},
        )
        return {"message": "Deliverable deleted successfully."}
