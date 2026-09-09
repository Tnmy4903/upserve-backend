"""Activity Log Repository."""

from bson import ObjectId
from bson.errors import InvalidId
from app.exceptions import ValidationException
from app.repositories.base_repo import BaseRepository


class ActivityLogRepository(BaseRepository):
    """Repository for activity log operations."""

    def __init__(self):
        super().__init__("activity_logs")

    async def ensure_indexes(self) -> None:
        """Ensure indexes for supported audit-log queries and ordering."""

        await self.collection.create_index(
            [("timestamp", -1), ("_id", -1)],
            name="activity_timestamp_id_desc",
        )
        await self.collection.create_index(
            [("userId", 1), ("timestamp", -1), ("_id", -1)],
            name="activity_user_timestamp_id",
        )
        await self.collection.create_index(
            [("entityId", 1), ("timestamp", -1), ("_id", -1)],
            name="activity_entity_timestamp_id",
        )

    async def update(self, id: str, data: dict) -> bool:
        """Activity logs are append-only."""

        raise ValidationException("Activity logs cannot be modified.")

    async def delete(self, id: str) -> bool:
        """Activity logs are append-only."""

        raise ValidationException("Activity logs cannot be deleted.")

    async def find_by_user(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Find activity logs by user."""

        cursor = (
            self.collection.find({"userId": {"$in": self._id_values(user_id)}})
            .sort([("timestamp", -1), ("_id", -1)])
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def find_by_entity(
        self,
        entity_id: str,
        entity: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Find activity logs by entity."""

        query = {"entityId": {"$in": self._id_values(entity_id)}}
        if entity:
            query["entity"] = entity

        cursor = (
            self.collection.find(query)
            .sort([("timestamp", -1), ("_id", -1)])
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def get_all_sorted(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all activity logs sorted by timestamp."""

        cursor = (
            self.collection.find()
            .sort([("timestamp", -1), ("_id", -1)])
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def get_recent(
        self,
        limit: int = 10,
    ) -> list[dict]:
        """Return the most recent activity logs."""

        cursor = (
            self.collection.find()
            .sort([("timestamp", -1), ("_id", -1)])
            .limit(limit)
        )

        return [doc async for doc in cursor]

    @staticmethod
    def _id_values(value: str) -> list:
        values = [value]
        try:
            values.append(ObjectId(value))
        except (InvalidId, TypeError):
            pass
        return values
