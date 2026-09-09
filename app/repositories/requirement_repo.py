"""Requirement Repository."""

from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError

from app.exceptions import DuplicateException, ValidationException
from app.repositories.base_repo import BaseRepository


class RequirementRepository(BaseRepository):
    """Repository for requirement operations."""

    def __init__(self):
        super().__init__("requirements")

    async def ensure_indexes(self) -> None:
        """Ensure one requirement per lead or project association."""

        await self.collection.create_index(
            "leadId",
            unique=True,
            name="requirements_lead_unique",
            partialFilterExpression={
                "leadId": {
                    "$type": "string"
                }
            },
        )
        await self.collection.create_index(
            "projectId",
            unique=True,
            name="requirements_project_unique",
            partialFilterExpression={
                "projectId": {
                    "$type": "string"
                }
            },
        )

    async def create(self, data: dict) -> str:
        """Create a requirement and translate duplicate associations."""

        try:
            return await super().create(data)
        except DuplicateKeyError:
            raise DuplicateException(
                "Requirement already exists for this lead or project."
            )

    async def create_with_history(
        self,
        data: dict,
        history_entry: dict,
    ) -> str:
        """Create a requirement and its initial history in one insert."""

        requirement_id = ObjectId()
        now = datetime.now(timezone.utc)
        payload = {
            **data,
            "_id": requirement_id,
            "history": [{
                **history_entry,
                "requirementId": str(requirement_id),
            }],
            "createdAt": now,
            "updatedAt": now,
        }
        try:
            await self.collection.insert_one(payload)
        except DuplicateKeyError:
            raise DuplicateException(
                "Requirement already exists for this lead or project."
            )
        return str(requirement_id)

    @staticmethod
    def _id_values(value: str) -> list:
        values = [value]
        try:
            values.append(ObjectId(value))
        except (InvalidId, TypeError):
            pass
        return values

    async def update_with_history(
        self,
        requirement_id: str,
        data: dict,
        history_entry: dict,
        expected_status: str | None = None,
    ) -> bool:
        """Update a requirement and append its history entry atomically."""

        try:
            now = datetime.now(timezone.utc)
            data["updatedAt"] = now
            query = {"_id": ObjectId(requirement_id)}
            if expected_status is not None:
                query["status"] = expected_status
            result = await self.collection.update_one(
                query,
                {
                    "$set": data,
                    "$push": {"history": history_entry},
                },
            )
            return result.matched_count > 0
        except InvalidId:
            raise ValidationException("Invalid requirement ID format.")

    async def find_by_lead(
        self,
        lead_id: str,
    ) -> dict | None:
        """Find requirements by lead ID."""

        return await self.find_one({"leadId": {"$in": self._id_values(lead_id)}})

    async def find_by_project(
        self,
        project_id: str,
    ) -> dict | None:
        """Find requirements by project ID."""

        return await self.find_one({"projectId": {"$in": self._id_values(project_id)}})

    async def exists_by_lead(
        self,
        lead_id: str,
    ) -> bool:
        """Check whether a requirement exists for a lead."""

        return (
            await self.collection.count_documents(
                {"leadId": {"$in": self._id_values(lead_id)}}
            )
        ) > 0

    async def exists_by_project(
        self,
        project_id: str,
    ) -> bool:
        """Check whether a requirement exists for a project."""

        return (
            await self.collection.count_documents(
                {"projectId": {"$in": self._id_values(project_id)}}
            )
        ) > 0
