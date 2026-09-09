from datetime import datetime, timezone

from app.exceptions import (
    PermissionException,
    ResourceNotFoundException,
    ValidationException,
)
from app.logger import logger_timeline
from app.repositories.project_repo import ProjectRepository
from app.repositories.timeline_repo import TimelineRepository
from app.repositories.user_repo import UserRepository
from app.services.activitylog_service import ActivityLogService
from app.services.project_service import ProjectService
from app.services.notification_service import NotificationService


class TimelineService:
    """Project timeline service."""

    def __init__(self):
        self.timeline_repo = TimelineRepository()
        self.project_repo = ProjectRepository()
        self.user_repo = UserRepository()

        self.project_service = ProjectService()
        self.activity_service = ActivityLogService()
        self.notification_service = NotificationService()

    async def add_timeline_event(
        self,
        project_id: str,
        title: str,
        created_by: str,
        description: str | None = None,
        current_user: dict | None = None,
        client_visible: bool = False,
    ) -> dict:
        """Add a timeline event."""

        project = await self.project_repo.find_by_id(
            project_id
        )

        if not project:
            raise ResourceNotFoundException(
                "Project"
            )

        if current_user:
            await self.project_service.ensure_project_access(
                project,
                current_user,
            )

        event_data = {
            "projectId": project_id,
            "title": title,
            "description": description,
            "createdBy": created_by,
            "isSystemEvent": False,
            "clientVisible": client_visible,
            "isDeleted": False,
        }

        event_id = await self.timeline_repo.create(
            event_data
        )

        user = await self.user_repo.find_by_id(
            created_by
        )

        user_role = (
            user.get("role")
            if user
            else "system"
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"] if current_user else created_by,
            user_role=current_user["role"] if current_user else user_role,
            action="Timeline Event Added",
            entity="TimelineEvent",
            entity_id=event_id,
            details={
                "projectId": project_id,
                "event": title,
            },
        )

        event = await self.timeline_repo.find_by_id(
            event_id
        )

        event["id"] = str(
            event["_id"]
        )

        logger_timeline.info(
            f"Timeline event '{title}' added for project {project_id}"
        )

        return event

    async def get_project_timeline(
        self,
        project_id: str,
        skip: int = 0,
        limit: int = 100,
        current_user: dict | None = None,
    ) -> list[dict]:
        """Return the timeline for a project."""

        project = await self.project_repo.find_by_id(
            project_id
        )

        if not project:
            raise ResourceNotFoundException(
                "Project"
            )

        if current_user:
            await self.project_service.ensure_project_access(
                project,
                current_user,
            )

        events = await self.timeline_repo.find_by_project(
            project_id,
            skip,
            limit,
        )

        if current_user and current_user.get("role") == "client":
            events = [
                event for event in events
                if event.get("clientVisible", True)
                and not event.get("isDeleted", False)
            ]

        for event in events:
            event["id"] = str(event["_id"])
            if event.get("deletedBy") is not None:
                event["deletedBy"] = str(event["deletedBy"])

        return events

    async def initialize_project_timeline(
        self,
        project_id: str,
        created_by: str,
    ) -> None:
        """Initialize the default timeline for a new project."""

        await self.timeline_repo.create_system_event(
            project_id=project_id,
            title="Project Created",
            description="Project created after quotation acceptance.",
            created_by=created_by,
            event_type="project_created",
            event_key="project_created",
        )

        logger_timeline.info(
            f"Default timeline initialized for project {project_id}"
        )

    async def delete_timeline_event(
        self,
        event_id: str,
        current_user: dict,
    ) -> dict:
        """Delete a timeline event."""

        event = await self.timeline_repo.find_by_id(
            event_id
        )

        if not event:
            raise ResourceNotFoundException(
                "Timeline Event"
            )

        actor = await self.user_repo.find_by_id(
            str(current_user.get("id")) if current_user else ""
        )
        if (
            not actor
            or not actor.get("isActive", True)
            or actor.get("role") != "super_admin"
        ):
            raise PermissionException(
                "Only an active Super Admin can delete timeline events."
            )

        project = await self.project_repo.find_by_id(
            str(event.get("projectId"))
        )
        if not project:
            raise ResourceNotFoundException("Project")
        await self.project_service.ensure_project_access(
            project,
            current_user,
        )

        if event.get("isSystemEvent", False):
            raise PermissionException(
                "System timeline events cannot be deleted."
            )

        deleted = await self.timeline_repo.update(
            event_id,
            {
                "isDeleted": True,
                "deletedAt": datetime.now(timezone.utc),
                "deletedBy": current_user["id"],
            },
        )
        await self.notification_service.notify_project_participants(
            project,
            notif_type="timeline",
            title="Project timeline updated",
            message=f"A new timeline update was added: {title}.",
            entity_id=event_id,
            entity_type="TimelineEvent",
            event_key=f"timeline_created:{event_id}",
            exclude_user_id=current_user["id"] if current_user else None,
            include_client=client_visible and title.casefold() != "project budget updated",
        )

        if not deleted:
            raise ValidationException(
                "Failed to delete timeline event."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Timeline Event Deleted",
            entity="TimelineEvent",
            entity_id=event_id,
            details={"projectId": str(event.get("projectId"))},
        )

        logger_timeline.info(
            f"Timeline event deleted: {event_id}"
        )

        return {
            "message": "Timeline event deleted successfully."
        }
