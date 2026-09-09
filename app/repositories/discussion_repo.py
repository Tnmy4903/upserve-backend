"""Discussion Repository."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from app.exceptions import DuplicateException
from app.repositories.base_repo import BaseRepository


class DiscussionRepository(BaseRepository):
    """Repository for project discussion operations."""

    def __init__(self):
        super().__init__("discussions")

    @staticmethod
    def _project_values(project_id: str) -> list:
        values = [project_id]
        try:
            values.append(ObjectId(project_id))
        except (InvalidId, TypeError):
            pass
        return values

    async def ensure_indexes(self) -> None:
        """Ensure one system initialization message exists per project."""

        await self.collection.create_index(
            [("projectId", 1), ("isSystemMessage", 1)],
            unique=True,
            name="discussion_system_message_unique",
            partialFilterExpression={"isSystemMessage": True},
        )

    async def create(self, data: dict) -> str:
        try:
            return await super().create(data)
        except DuplicateKeyError:
            raise DuplicateException(
                "A system discussion message already exists for this project."
            )

    async def find_by_project(
        self,
        project_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return discussion messages for a project."""

        cursor = (
            self.collection.find(
                {"projectId": {"$in": self._project_values(project_id)}}
            )
            .sort(
                [
                    ("createdAt", -1),
                    ("_id", -1),
                ]
            )
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def find_system_message(self, project_id: str) -> dict | None:
        """Find the system initialization message across legacy ID types."""

        return await self.find_one(
            {
                "projectId": {"$in": self._project_values(project_id)},
                "isSystemMessage": True,
            }
        )

    async def find_legacy_initialization_message(
        self,
        project_id: str,
    ) -> dict | None:
        """Find an unmarked legacy initialization message."""

        return await self.find_one(
            {
                "projectId": {"$in": self._project_values(project_id)},
                "message": {
                    "$regex": r"^Project discussion has been initialized\."
                },
            }
        )

    async def add_reply(
        self,
        message_id: str,
        reply: dict,
    ) -> bool:
        """Add a reply to a discussion message."""

        now = datetime.now(timezone.utc)

        reply["createdAt"] = now
        reply["updatedAt"] = now

        result = await self.collection.update_one(
            {"_id": ObjectId(message_id)},
            {
                "$push": {
                    "replies": reply
                }
            },
        )

        return result.modified_count > 0

    async def mark_seen(
        self,
        message_id: str,
    ) -> bool:
        """Mark a discussion message as seen."""

        result = await self.collection.update_one(
            {"_id": ObjectId(message_id)},
            {
                "$set": {
                    "seen": True
                }
            },
        )

        return result.modified_count > 0

    async def count_by_project(
        self,
        project_id: str,
    ) -> int:
        """Return the total number of discussion messages for a project."""

        return await self.collection.count_documents(
            {"projectId": {"$in": self._project_values(project_id)}}
        )
