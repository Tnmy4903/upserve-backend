"""Upload Repository."""

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from app.exceptions import DuplicateException
from app.repositories.base_repo import BaseRepository


class UploadRepository(BaseRepository):
    """Repository for file upload operations."""

    def __init__(self):
        super().__init__("uploads")

    @staticmethod
    def _project_values(project_id: str) -> list:
        values = [project_id]
        try:
            values.append(ObjectId(project_id))
        except (InvalidId, TypeError):
            pass
        return values

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            "storedFileName",
            unique=True,
            name="uploads_stored_filename_unique",
        )

    async def create(self, data: dict) -> str:
        try:
            return await super().create(data)
        except DuplicateKeyError:
            raise DuplicateException("Stored upload filename already exists.")

    async def find_by_project(
        self,
        project_id: str,
    ) -> list[dict]:
        """Return uploads associated with a project."""

        return await self.find_many(
            {"projectId": {"$in": self._project_values(project_id)}}
        )

    async def find_by_user(
        self,
        user_id: str,
    ) -> list[dict]:
        """Return uploads associated with a user."""

        return await self.find_many(
            {
                "userId": ObjectId(user_id)
            }
        )

    async def get_all_sorted(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all uploads sorted by upload date."""

        cursor = (
            self.collection.find()
            .sort("uploadedAt", -1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def find_by_filename(
        self,
        filename: str,
    ) -> dict | None:
        """Find an upload by its stored filename."""

        return await self.find_one(
            {
                "storedFileName": filename
            }
        )

    async def count_by_project(self, project_id: str) -> int:
        return await self.collection.count_documents(
            {"projectId": {"$in": self._project_values(project_id)}}
        )

    async def count_all(
        self,
    ) -> int:
        """Return the total number of uploads."""

        return await self.count({})
