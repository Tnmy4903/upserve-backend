from datetime import datetime, timezone

from app.exceptions import DuplicateException, PermissionException, ResourceNotFoundException, ValidationException
from app.logger import logger_discussion
from app.repositories.discussion_repo import DiscussionRepository
from app.repositories.project_repo import ProjectRepository
from app.services.activitylog_service import ActivityLogService
from app.services.notification_service import NotificationService
from app.services.project_service import ProjectService


class DiscussionService:
    """Service for project discussions and messaging."""

    def __init__(self):
        self.discussion_repo = DiscussionRepository()
        self.project_repo = ProjectRepository()
        self.activity_service = ActivityLogService()
        self.notification_service = NotificationService()
        self.project_service = ProjectService()

    async def _ensure_project_access(
        self,
        project: dict,
        current_user: dict,
    ) -> None:
        await self.project_service.ensure_project_access(
            project,
            current_user,
        )

    @staticmethod
    def _prepare_message(
        message: dict,
        current_user: dict,
    ) -> dict:
        """Normalize legacy records and hide deleted content."""

        result = dict(message)
        result["id"] = str(result.pop("_id"))
        result.setdefault("authorRole", None)
        normalized_replies = []
        for index, reply in enumerate(result.get("replies", [])):
            normalized_reply = dict(reply)
            normalized_reply.setdefault(
                "id",
                f"{result['id']}:reply:{index}",
            )
            normalized_reply.setdefault("messageId", result["id"])
            normalized_reply.setdefault("authorRole", None)
            normalized_reply.setdefault("attachments", [])
            normalized_replies.append(normalized_reply)
        result["replies"] = normalized_replies
        result.setdefault("isDeleted", False)
        result.setdefault("isSystemMessage", False)
        result.setdefault("attachments", [])

        if result.get("deletedAt") is not None:
            result["deletedAt"] = result["deletedAt"]
        if result.get("deletedBy") is not None:
            result["deletedBy"] = str(result["deletedBy"])

        if result.get("isDeleted"):
            result["message"] = "[Message deleted]"
            result["attachments"] = []
            result["replies"] = []
            result["authorId"] = ""
            result["authorName"] = "Deleted user"
            result["authorRole"] = None

        return result

    async def add_message(
        self,
        project_id: str,
        current_user: dict,
        author_id: str,
        author_name: str,
        message: str,
        attachments: list | None = None,
    ) -> dict:
        """Add a new discussion message to a project."""

        project = await self.project_repo.find_by_id(
            project_id
        )

        if not project:
            raise ResourceNotFoundException(
                "Project"
            )

        await self._ensure_project_access(project, current_user)

        message_data = {
            "projectId": project_id,
            "authorId": current_user["id"],
            "authorName": current_user["name"].strip(),
            "authorRole": current_user["role"],
            "message": message.strip(),
            "attachments": attachments or [],
            "edited": False,
            "seen": False,
            "replies": [],
            "isDeleted": False,
            "isSystemMessage": False,
        }

        message_id = await self.discussion_repo.create(
            message_data
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Discussion Message Added",
            entity="Discussion",
            entity_id=message_id,
            details={"projectId": project_id},
        )
        await self.notification_service.notify_project_participants(
            project,
            notif_type="discussion",
            title="New project message",
            message=f"{current_user['name']} added a message to the project discussion.",
            entity_id=message_id,
            entity_type="Discussion",
            event_key=f"discussion_message:{message_id}",
            exclude_user_id=current_user["id"],
        )

        message_doc = await self.discussion_repo.find_by_id(
            message_id
        )

        logger_discussion.info(
            f"New discussion message added to project {project_id}"
        )

        return self._prepare_message(message_doc, current_user)

    async def add_reply(
        self,
        message_id: str,
        current_user: dict,
        author_id: str,
        author_name: str,
        message: str,
        attachments: list | None = None,
    ) -> dict:
        """Add a reply to a discussion message."""

        discussion = await self.discussion_repo.find_by_id(
            message_id
        )

        if not discussion:
            raise ResourceNotFoundException(
                "Discussion Message"
            )

        project = await self.project_repo.find_by_id(
            str(discussion["projectId"])
        )

        if not project:
            raise ResourceNotFoundException(
                "Project"
            )

        await self._ensure_project_access(project, current_user)

        if discussion.get("isDeleted"):
            raise ValidationException("Deleted messages cannot receive replies.")

        reply_data = {
            "messageId": message_id,
            "authorId": current_user["id"],
            "authorName": current_user["name"].strip(),
            "authorRole": current_user["role"],
            "message": message.strip(),
            "attachments": attachments or [],
            "edited": False,
        }

        updated = await self.discussion_repo.add_reply(
            message_id,
            reply_data,
        )

        if not updated:
            raise ValidationException(
                "Failed to add reply."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Discussion Reply Added",
            entity="DiscussionReply",
            entity_id=message_id,
        )
        await self.notification_service.notify_project_participants(
            project,
            notif_type="discussion",
            title="New discussion reply",
            message=f"{current_user['name']} replied to a project discussion message.",
            entity_id=message_id,
            entity_type="Discussion",
            event_key=f"discussion_reply:{message_id}:{current_user['id']}:{datetime.now(timezone.utc).isoformat()}",
            exclude_user_id=current_user["id"],
        )

        logger_discussion.info(
            f"Reply added to message {message_id}"
        )

        return {
            "message": "Reply added successfully."
        }

    async def get_project_discussion(
        self,
        project_id: str,
        current_user: dict,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all discussion messages for a project."""

        project = await self.project_repo.find_by_id(
            project_id
        )

        if not project:
            raise ResourceNotFoundException(
                "Project"
            )

        await self._ensure_project_access(project, current_user)

        messages = await self.discussion_repo.find_by_project(
            project_id,
            skip,
            limit,
        )

        return [self._prepare_message(message, current_user) for message in messages]

    async def initialize_project_discussion(
        self,
        project_id: str,
        created_by: str = "system",
    ) -> None:
        """Initialize the discussion thread for a new project."""

        existing = await self.discussion_repo.find_system_message(project_id)
        if existing:
            return

        # Promote legacy initialization records to the dedicated marker.
        legacy = await self.discussion_repo.find_legacy_initialization_message(
            project_id
        )
        if legacy:
            await self.discussion_repo.update(
                str(legacy["_id"]),
                {"isSystemMessage": True},
            )
            return

        message_data = {
            "projectId": project_id,
            "authorId": created_by,
            "authorName": "System",
            "authorRole": "system",
            "message": (
                "Project discussion has been initialized. "
                "All future communication regarding this project "
                "will happen here."
            ),
            "attachments": [],
            "edited": False,
            "seen": False,
            "replies": [],
            "isDeleted": False,
            "isSystemMessage": True,
        }

        try:
            await self.discussion_repo.create(message_data)
        except DuplicateException:
            # Another retry created the unique system message first.
            return

        logger_discussion.info(
            f"Discussion initialized for project {project_id}"
        )

    async def get_message(
        self,
        message_id: str,
        current_user: dict,
    ) -> dict:
        """Return a discussion message."""

        message = await self.discussion_repo.find_by_id(
            message_id
        )

        if not message:
            raise ResourceNotFoundException(
                "Discussion Message"
            )

        project = await self.project_repo.find_by_id(
            str(message["projectId"])
        )

        if not project:
            raise ResourceNotFoundException("Project")

        await self._ensure_project_access(project, current_user)

        await self.discussion_repo.mark_seen(
            message_id
        )

        message["seen"] = True

        return self._prepare_message(message, current_user)

    async def delete_message(
        self,
        message_id: str,
        current_user: dict,
    ) -> dict:
        """Delete a discussion message."""

        message = await self.discussion_repo.find_by_id(
            message_id
        )

        if not message:
            raise ResourceNotFoundException(
                "Discussion Message"
            )

        project = await self.project_repo.find_by_id(
            str(message["projectId"])
        )
        if not project:
            raise ResourceNotFoundException("Project")
        await self._ensure_project_access(project, current_user)

        if message.get("isSystemMessage"):
            raise PermissionException("System messages cannot be deleted.")

        if current_user["role"] != "super_admin":
            raise PermissionException("Only Super Admin can delete discussion messages.")

        deleted = await self.discussion_repo.delete(message_id)

        if not deleted:
            raise ValidationException(
                "Failed to delete message."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Discussion Message Deleted",
            entity="Discussion",
            entity_id=message_id,
        )

        logger_discussion.info(
            f"Discussion message deleted: {message_id}"
        )

        return {
            "message": "Message deleted successfully."
        }
