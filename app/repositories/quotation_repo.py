"""Quotation Repository."""

from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime, timezone
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.exceptions import DuplicateException

from app.repositories.base_repo import BaseRepository


class QuotationRepository(BaseRepository):
    """Repository for quotation operations."""

    def __init__(self):
        super().__init__("quotations")

    async def ensure_indexes(self) -> None:
        """Index quotation relationships while allowing rejected re-quotes."""

        indexes = (
            ("leadId", "quotations_lead_unique"),
            ("projectId", "quotations_project_unique"),
        )
        existing_indexes = await self.collection.index_information()
        for field, index_name in indexes:
            existing = existing_indexes.get(index_name)
            if existing and existing.get("unique"):
                # Older deployments used a unique relationship index. Drop
                # only that index so rejected quotation history can coexist
                # with a new quotation for the same lead/project.
                await self.collection.drop_index(index_name)
            await self.collection.create_index(
                field,
                unique=False,
                name=index_name,
                partialFilterExpression={field: {"$type": "string"}},
            )

    async def create(self, data: dict) -> str:
        try:
            return await super().create(data)
        except DuplicateKeyError as exc:
            if "lead" in str(exc):
                raise DuplicateException("Quotation already exists for this lead.")
            if "project" in str(exc):
                raise DuplicateException("Quotation already exists for this project.")
            raise DuplicateException("Quotation")

    async def update_status_if_current(
        self,
        quotation_id: str,
        expected_status: str,
        next_status: str,
    ) -> dict | None:
        """Atomically change quotation status from the expected state."""

        try:
            return await self.collection.find_one_and_update(
                {
                    "_id": ObjectId(quotation_id),
                    "status": expected_status,
                },
                {
                    "$set": {
                        "status": next_status,
                        "updatedAt": datetime.now(timezone.utc),
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
        except (InvalidId, TypeError):
            from app.exceptions import ValidationException
            raise ValidationException("Invalid quotation ID format.")

    async def find_by_client(
        self,
        client_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return quotations belonging to a client."""

        return await self.find_many(
            {"clientId": client_id},
            skip=skip,
            limit=limit,
        )

    async def find_by_status(
        self,
        status: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return quotations filtered by status."""

        return await self.find_many(
            {"status": status},
            skip=skip,
            limit=limit,
        )

    async def find_by_relationships(
        self,
        lead_ids: list[str],
        project_ids: list[str],
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[dict]:
        """Return quotations linked to assigned leads or projects."""

        relationships = []
        if lead_ids:
            relationships.append({"leadId": {"$in": lead_ids}})
        if project_ids:
            relationships.append({"projectId": {"$in": project_ids}})

        if not relationships:
            return []

        query = {"$or": relationships}
        if status:
            query["status"] = status

        cursor = (
            self.collection.find(query)
            .sort("createdAt", -1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def find_by_project(
        self,
        project_id: str,
    ) -> dict | None:
        """Find a quotation by project ID."""

        return await self.find_one(
            {"projectId": project_id}
        )

    async def find_active_by_project(
        self,
        project_id: str,
    ) -> dict | None:
        """Find a non-rejected quotation by project ID."""

        return await self.find_one(
            {"projectId": project_id, "status": {"$ne": "Rejected"}}
        )

    async def get_next_quotation_number(
        self,
    ) -> str:
        """Generate the next quotation number."""

        sequence = await self.get_next_sequence(
            "quotation"
        )

        return f"QT-{sequence:05d}"

    async def get_all_sorted(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all quotations sorted by creation date."""

        cursor = (
            self.collection.find()
            .sort("createdAt", -1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def find_by_lead(
        self,
        lead_id: str,
    ) -> dict | None:
        """Find a quotation by lead ID."""

        return await self.find_one(
            {"leadId": lead_id}
        )

    async def find_active_by_lead(
        self,
        lead_id: str,
    ) -> dict | None:
        """Find a non-rejected quotation by lead ID."""

        return await self.find_one(
            {"leadId": lead_id, "status": {"$ne": "Rejected"}}
        )

    async def count_all(
        self,
    ) -> int:
        """Return the total number of quotations."""

        return await self.count({})

    async def count_by_status(
        self,
        status: str,
    ) -> int:
        """Return the total number of quotations for a status."""

        return await self.count(
            {
                "status": status
            }
        )

    async def get_recent(
        self,
        limit: int = 5,
    ) -> list[dict]:
        """Return the most recently created quotations."""

        cursor = (
            self.collection.find()
            .sort("createdAt", -1)
            .limit(limit)
        )

        return [doc async for doc in cursor]
