"""Deliverables Repository."""

from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime, timezone
from pymongo import ReturnDocument

from app.exceptions import DuplicateException
from app.repositories.base_repo import BaseRepository


class DeliverablesRepository(BaseRepository):
    """Repository for project deliverables."""

    def __init__(self):
        super().__init__("deliverables")

    @staticmethod
    def _project_values(project_id: str) -> list:
        values = [project_id]
        try:
            values.append(ObjectId(project_id))
        except (InvalidId, TypeError):
            pass
        return values

    async def ensure_indexes(self) -> None:
        """Prevent duplicate active deliverable titles per project."""

        await self.collection.create_index(
            [
                ("projectId", 1),
                ("titleNormalized", 1),
            ],
            unique=True,
            name="deliverables_active_title_unique",
            partialFilterExpression={
                "status": {
                    "$in": [
                        "pending",
                        "in_progress",
                        "blocked",
                    ]
                }
            },
        )

    async def create(self, data: dict) -> str:
        try:
            return await super().create(data)
        except DuplicateKeyError:
            raise DuplicateException(
                "An active deliverable with this title already exists for the project."
            )

    async def find_by_project(
        self,
        project_id: str,
    ) -> list[dict]:
        """Find deliverables for a project."""

        cursor = (
            self.collection.find({"projectId": {"$in": self._project_values(project_id)}})
            .sort("createdAt", 1)
        )
        return [doc async for doc in cursor]

    async def exists_by_project(
        self,
        project_id: str,
    ) -> bool:
        """Check whether deliverables exist for a project."""

        return await self.collection.count_documents(
            {
                "projectId": {"$in": self._project_values(project_id)},
                "status": {
                    "$nin": ["cancelled"]
                },
            }
        ) > 0

    async def exists_any_by_project(
        self,
        project_id: str,
    ) -> bool:
        """Return whether any historical deliverable exists for a project."""

        return await self.collection.count_documents(
            {"projectId": {"$in": self._project_values(project_id)}}
        ) > 0

    async def update_status_if_current(
        self,
        deliverable_id: str,
        expected_status: str,
        updates: dict,
    ) -> dict | None:
        """Atomically update a deliverable from the expected status."""

        try:
            updates = {**updates, "updatedAt": datetime.now(timezone.utc)}
            return await self.collection.find_one_and_update(
                {
                    "_id": ObjectId(deliverable_id),
                    "status": expected_status,
                },
                {"$set": updates},
                return_document=ReturnDocument.AFTER,
            )
        except (InvalidId, TypeError):
            from app.exceptions import ValidationException
            raise ValidationException("Invalid deliverable ID format.")

    async def all_non_cancelled_completed(
        self,
        project_id: str,
    ) -> tuple[int, int]:
        """Return total active and completed deliverable counts."""

        query = {
            "projectId": {"$in": self._project_values(project_id)},
            "status": {
                "$nin": ["cancelled"]
            },
        }
        total = await self.collection.count_documents(query)
        completed = await self.collection.count_documents(
            {
                **query,
                "status": "completed",
            }
        )
        return total, completed

    async def get_progress_summary(self, project_id: str) -> dict:
        """Calculate current project progress from deliverable records."""

        total = await self.collection.count_documents(
            {
                "projectId": {"$in": self._project_values(project_id)},
                "status": {"$nin": ["cancelled"]},
            }
        )
        completed = await self.collection.count_documents(
            {
                "projectId": {"$in": self._project_values(project_id)},
                "status": "completed",
            }
        )
        cancelled = await self.collection.count_documents(
            {
                "projectId": {"$in": self._project_values(project_id)},
                "status": "cancelled",
            }
        )

        return {
            "progressPercentage": (
                round((completed / total) * 100, 2)
                if total
                else None
            ),
            "totalDeliverables": total,
            "completedDeliverables": completed,
            "cancelledDeliverables": cancelled,
        }

    async def count_all(
        self,
    ) -> int:
        """Return the total number of deliverables."""

        return await self.count({})
