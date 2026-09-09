"""Timeline Repository."""

from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from bson.errors import InvalidId

from app.exceptions import DuplicateException
from app.repositories.base_repo import BaseRepository


class TimelineRepository(BaseRepository):
    """Repository for project timeline operations."""

    def __init__(self):
        super().__init__("timeline_events")

    @staticmethod
    def _project_values(project_id: str) -> list:
        values = [project_id]
        try:
            values.append(ObjectId(project_id))
        except (InvalidId, TypeError):
            pass
        return values

    async def ensure_indexes(self) -> None:
        """Ensure keyed system events cannot be duplicated."""

        await self.collection.create_index(
            [("projectId", 1), ("eventKey", 1)],
            unique=True,
            name="timeline_system_event_unique",
            partialFilterExpression={
                "isSystemEvent": True,
                "eventKey": {
                    "$type": "string"
                },
            },
        )

    async def create_system_event(
        self,
        project_id: str,
        title: str,
        description: str | None,
        created_by: str,
        event_type: str,
        event_key: str,
        client_visible: bool = True,
    ) -> dict:
        """Create or return a keyed system event safely."""

        existing = await self.find_one(
            {
                "projectId": {"$in": self._project_values(project_id)},
                "isSystemEvent": True,
                "eventKey": event_key,
            }
        )
        if existing:
            return existing

        event_data = {
            "projectId": project_id,
            "title": title,
            "description": description,
            "createdBy": created_by,
            "eventType": event_type,
            "eventKey": event_key,
            "isSystemEvent": True,
            "clientVisible": client_visible,
            "isDeleted": False,
        }

        try:
            event_id = await self.create(event_data)
        except DuplicateKeyError:
            existing = await self.find_one(
                {
                    "projectId": {"$in": self._project_values(project_id)},
                    "isSystemEvent": True,
                    "eventKey": event_key,
                }
            )
            if existing:
                return existing
            raise DuplicateException("System timeline event already exists.")

        created = await self.find_by_id(event_id)
        return created

    async def find_system_event(
        self,
        project_id: str,
        event_key: str,
    ) -> dict | None:
        """Find a keyed system event for lifecycle recovery."""

        return await self.find_one({
            "projectId": {"$in": self._project_values(project_id)},
            "isSystemEvent": True,
            "eventKey": event_key,
        })

    async def find_by_project(
        self,
        project_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return timeline events for a project."""

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

    async def count_by_project(
        self,
        project_id: str,
    ) -> int:
        """Return the total number of timeline events for a project."""

        return await self.collection.count_documents(
            {"projectId": {"$in": self._project_values(project_id)}}
        )
