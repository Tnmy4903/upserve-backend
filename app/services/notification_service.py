from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    DuplicateException,
    ResourceNotFoundException,
    ValidationException,
)
from app.logger import logger_notification
from app.repositories.notification_repo import NotificationRepository
from app.repositories.user_repo import UserRepository


class NotificationService:
    """Service for notification management."""

    def __init__(self):
        self.notification_repo = NotificationRepository()
        self.user_repo = UserRepository()

    async def create_notification(
        self,
        user_id: str,
        notif_type: str,
        title: str,
        message: str,
        entity_id: str | None = None,
        entity_type: str | None = None,
        event_key: str | None = None,
    ) -> dict | None:
        """Create a notification for a user."""

        recipient = await self.user_repo.find_by_id(str(user_id))
        if not recipient:
            raise ResourceNotFoundException("Notification recipient")
        if recipient.get("role") not in {
            "super_admin",
            "sub_admin",
            "client",
        }:
            raise ValidationException("Notification recipient has an invalid role.")
        if not recipient.get("isActive", True):
            logger_notification.info(
                f"Skipped notification for inactive user {user_id}"
            )
            return None

        if event_key:
            existing = await self.notification_repo.find_by_event_key(event_key)
            if existing:
                existing["id"] = str(existing["_id"])
                return existing

        notification_data = {
            "userId": user_id,
            "type": notif_type,
            "title": title.strip(),
            "message": message.strip(),
            "entityId": entity_id,
            "entityType": entity_type,
            "read": False,
        }
        if event_key:
            notification_data["eventKey"] = event_key

        try:
            notification_id = await self.notification_repo.create(
                notification_data
            )
        except DuplicateException:
            if not event_key:
                raise
            existing = await self.notification_repo.find_by_event_key(event_key)
            if not existing:
                raise
            existing["id"] = str(existing["_id"])
            return existing

        notification = await self.notification_repo.find_by_id(
            notification_id
        )

        notification["id"] = str(
            notification["_id"]
        )

        logger_notification.info(
            f"Notification created for user {user_id}"
        )

        return notification

    async def safe_create_notification(self, **kwargs) -> dict | None:
        """Create an optional notification without failing its core operation."""

        try:
            return await self.create_notification(**kwargs)
        except Exception as exc:
            logger_notification.warning(
                f"Notification creation failed: {exc}"
            )
            return None

    async def notify_users(
        self,
        user_ids: list[str],
        *,
        notif_type: str,
        title: str,
        message: str,
        entity_id: str | None = None,
        entity_type: str | None = None,
        event_key: str,
        exclude_user_id: str | None = None,
    ) -> None:
        """Fan out one business notification without duplicate recipients."""

        seen: set[str] = set()
        for user_id in user_ids:
            normalized_id = str(user_id)
            if not normalized_id or normalized_id in seen or normalized_id == str(exclude_user_id):
                continue
            seen.add(normalized_id)
            await self.safe_create_notification(
                user_id=normalized_id,
                notif_type=notif_type,
                title=title,
                message=message,
                entity_id=entity_id,
                entity_type=entity_type,
                event_key=f"{event_key}:{normalized_id}",
            )

    async def notify_admins(
        self,
        *,
        notif_type: str,
        title: str,
        message: str,
        entity_id: str | None = None,
        entity_type: str | None = None,
        event_key: str,
        exclude_user_id: str | None = None,
        include_client: bool = True,
    ) -> None:
        """Notify active admins about an important workflow event."""

        recipients: list[str] = []
        for role in ("super_admin", "sub_admin"):
            recipients.extend(str(user["_id"]) for user in await self.user_repo.get_active_by_role(role))
        await self.notify_users(
            recipients,
            notif_type=notif_type,
            title=title,
            message=message,
            entity_id=entity_id,
            entity_type=entity_type,
            event_key=event_key,
            exclude_user_id=exclude_user_id,
        )

    async def notify_project_participants(
        self,
        project: dict,
        *,
        notif_type: str,
        title: str,
        message: str,
        entity_id: str | None = None,
        entity_type: str | None = None,
        event_key: str,
        exclude_user_id: str | None = None,
        include_client: bool = True,
    ) -> None:
        """Notify the project client, assigned admins, and active Super Admins."""

        recipients = [
            str(project.get("userId")) if include_client and project.get("userId") else "",
            str(project.get("assignedAdmin")) if project.get("assignedAdmin") else "",
            str(project.get("assignedSubAdmin")) if project.get("assignedSubAdmin") else "",
        ]
        recipients.extend(str(user["_id"]) for user in await self.user_repo.get_active_by_role("super_admin"))
        await self.notify_users(
            recipients,
            notif_type=notif_type,
            title=title,
            message=message,
            entity_id=entity_id,
            entity_type=entity_type,
            event_key=event_key,
            exclude_user_id=exclude_user_id,
        )

    async def get_unread_notifications(
        self,
        user_id: str,
    ) -> list[dict]:
        """Return all unread notifications for a user."""

        notifications = (
            await self.notification_repo.find_unread_by_user(
                user_id
            )
        )

        for notification in notifications:
            notification["id"] = str(
                notification["_id"]
            )

        return notifications

    async def get_user_notifications(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all notifications for a user."""

        if not user_id:
            raise ValidationException(
                "User ID is required."
            )

        notifications = await self.notification_repo.find_by_user(
            user_id,
            skip,
            limit,
        )

        for notification in notifications:
            notification["id"] = str(
                notification["_id"]
            )

        return notifications

    async def mark_as_read(
        self,
        notification_id: str,
        current_user: dict,
    ) -> dict:
        """Mark a notification as read."""

        notification = await self.notification_repo.find_by_id(
            notification_id
        )

        if not notification:
            raise ResourceNotFoundException(
                "Notification"
            )

        if (
            str(notification["userId"])
            != current_user["id"]
        ):
            raise AuthorizationException(
                "Access denied."
            )

        updated = await self.notification_repo.mark_as_read(
            notification_id
        )

        if not updated:
            raise ValidationException(
                "Failed to mark notification as read."
            )

        notification["read"] = True
        notification["id"] = str(
            notification["_id"]
        )

        logger_notification.info(
            f"Notification {notification_id} marked as read."
        )

        return notification

    async def mark_all_as_read(
        self,
        current_user: dict,
    ) -> int:
        """Mark all notifications as read for a user."""

        user = await self.user_repo.find_by_id(
            str(current_user.get("id")) if current_user else ""
        )
        if not user or not user.get("isActive", True):
            raise AuthorizationException("Authenticated active user is required.")

        user_id = str(user["_id"])

        count = await self.notification_repo.mark_all_as_read(
            user_id
        )

        logger_notification.info(
            f"{count} notifications marked as read for user {user_id}"
        )

        return count

    async def delete_notification(
        self,
        notification_id: str,
        current_user: dict,
    ) -> dict:
        """Delete a notification."""

        notification = await self.notification_repo.find_by_id(
            notification_id
        )

        if not notification:
            raise ResourceNotFoundException(
                "Notification"
            )

        if (
            str(notification["userId"])
            != current_user["id"]
        ):
            raise AuthenticationException(
                "Access denied."
            )

        deleted = await self.notification_repo.delete(
            notification_id
        )

        if not deleted:
            raise ValidationException(
                "Failed to delete notification."
            )

        logger_notification.info(
            f"Notification {notification_id} deleted."
        )

        return {
            "message": "Notification deleted successfully."
        }

    async def clear_all_notifications(
        self,
        current_user: dict,
    ) -> dict:
        """Delete all notifications for a user."""

        user = await self.user_repo.find_by_id(
            str(current_user.get("id")) if current_user else ""
        )
        if not user or not user.get("isActive", True):
            raise AuthorizationException("Authenticated active user is required.")

        user_id = str(user["_id"])

        deleted_count = (
            await self.notification_repo.delete_many_by_user(
                user_id
            )
        )

        logger_notification.info(
            f"{deleted_count} notifications deleted for user {user_id}"
        )

        return {
            "message": (
                f"Deleted {deleted_count} notifications."
            )
        }
