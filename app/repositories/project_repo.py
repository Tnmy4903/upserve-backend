"""Project Repository."""

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.exceptions import DuplicateException, ValidationException
from app.repositories.base_repo import BaseRepository


class ProjectRepository(BaseRepository):
    """Repository for project operations."""

    def __init__(self):
        super().__init__("projects")

    async def ensure_indexes(self) -> None:
        """Ensure one project is created per quotation."""

        await self.collection.create_index(
            "quotationId",
            unique=True,
            name="projects_quotation_unique",
            partialFilterExpression={
                "quotationId": {
                    "$type": "string"
                }
            },
        )

    async def create(self, data: dict) -> str:
        """Create a project and translate duplicate quotation errors."""

        try:
            return await super().create(data)
        except DuplicateKeyError:
            raise DuplicateException(
                "Project already exists for this quotation."
            )

    @staticmethod
    def _quotation_values(quotation_id: str) -> list:
        values = [quotation_id]
        try:
            values.append(ObjectId(quotation_id))
        except (InvalidId, TypeError):
            pass
        return values

    async def find_by_quotation(self, quotation_id: str) -> dict | None:
        """Find a project across current and legacy quotation ID types."""

        return await self.find_one(
            {"quotationId": {"$in": self._quotation_values(quotation_id)}}
        )

    async def update_status_if_current(
        self,
        project_id: str,
        expected_status: str,
        next_status: str,
    ) -> dict | None:
        """Atomically advance a project from its expected status."""

        try:
            return await self.collection.find_one_and_update(
                {"_id": ObjectId(project_id), "status": expected_status},
                {"$set": {"status": next_status}},
                return_document=ReturnDocument.AFTER,
            )
        except (InvalidId, TypeError):
            raise ValidationException("Invalid project ID format.")

    async def find_by_user(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return projects belonging to a specific user."""

        try:
            owner_query = {
                "$or": [
                    {"userId": user_id},
                    {"userId": ObjectId(user_id)},
                ]
            }
        except Exception:
            owner_query = {"userId": user_id}

        return await self.find_many(
            owner_query,
            skip=skip,
            limit=limit,
        )

    async def count_by_status(
        self,
        status: str,
    ) -> int:
        """Return the total number of projects for a given status."""

        return await self.count(
            {
                "status": status
            }
        )

    async def get_all_sorted(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all projects sorted by creation date."""

        cursor = (
            self.collection.find()
            .sort("createdAt", -1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def count_all(
        self,
    ) -> int:
        """Return the total number of projects."""

        return await self.count({})

    async def get_recent_projects(
        self,
        limit: int = 5,
    ) -> list[dict]:
        """Return the most recently created projects."""

        cursor = (
            self.collection.find()
            .sort("createdAt", -1)
            .limit(limit)
        )

        return [doc async for doc in cursor]
