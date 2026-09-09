"""Notification Repository."""

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.exceptions import DuplicateException
from app.repositories.base_repo import BaseRepository


class NotificationRepository(BaseRepository):
    """Repository for notification operations."""

    def __init__(self):
        super().__init__("notifications")

    async def ensure_indexes(self) -> None:
        """Ensure notification recipient, unread, and event queries are indexed."""

        await self.collection.create_index(
            [("userId", 1), ("createdAt", -1), ("_id", -1)],
            name="notifications_user_recent",
        )
        await self.collection.create_index(
            [("userId", 1), ("read", 1), ("createdAt", -1), ("_id", -1)],
            name="notifications_user_unread",
        )
        await self.collection.create_index(
            "eventKey",
            unique=True,
            sparse=True,
            name="notifications_event_unique",
        )

    async def create(self, data: dict) -> str:
        try:
            return await super().create(data)
        except DuplicateKeyError:
            raise DuplicateException("Notification event")

    async def find_by_event_key(self, event_key: str) -> dict | None:
        return await self.find_one({"eventKey": event_key})

    async def find_by_user(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return notifications for a user."""

        cursor = (
            self.collection.find(
                {"userId": user_id}
            )
            .sort([
                ("createdAt", -1),
                ("_id", -1),
            ])
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def find_unread_by_user(
        self,
        user_id: str,
    ) -> list[dict]:
        """Return unread notifications for a user."""

        cursor = (
            self.collection.find(
                {
                    "userId": user_id,
                    "read": False,
                }
            )
            .sort([
                ("createdAt", -1),
                ("_id", -1),
            ])
        )
        return [doc async for doc in cursor]

    async def mark_as_read(
        self,
        notification_id: str,
    ) -> bool:
        """Mark a notification as read."""

        result = await self.collection.update_one(
            {"_id": ObjectId(notification_id)},
            {
                "$set": {
                    "read": True
                }
            },
        )

        return result.matched_count > 0

    async def mark_all_as_read(
        self,
        user_id: str,
    ) -> int:
        """Mark all unread notifications as read for a user."""

        result = await self.collection.update_many(
            {
                "userId": user_id,
                "read": False,
            },
            {
                "$set": {
                    "read": True
                }
            },
        )

        return result.modified_count

    async def delete_many_by_user(
        self,
        user_id: str,
    ) -> int:
        """Delete all notifications for a user."""

        result = await self.collection.delete_many(
            {
                "userId": user_id
            }
        )

        return result.deleted_count
