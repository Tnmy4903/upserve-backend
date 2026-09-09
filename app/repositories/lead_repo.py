"""Lead Repository."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from app.exceptions import DuplicateException, ValidationException
from app.repositories.base_repo import BaseRepository


class LeadRepository(BaseRepository):
    """Repository for CRM lead operations."""

    def __init__(self):
        super().__init__("leads")

    async def ensure_indexes(self) -> None:
        """Ensure lead email is searchable; client uniqueness belongs to users."""

        try:
            await self.collection.drop_index("leads_email_unique")
        except Exception:
            pass
        await self.collection.create_index("email", sparse=True, name="leads_email_lookup")

    async def create(self, data: dict) -> str:
        """Create a lead and translate duplicate email errors."""

        try:
            return await super().create(data)
        except DuplicateKeyError:
            raise DuplicateException("Lead")

    async def update_with_history(
        self,
        id: str,
        data: dict,
        history: list[dict],
        expected_stage: str | None = None,
    ) -> bool:
        """Atomically update a lead and append its history entries."""

        try:
            now = datetime.now(timezone.utc)
            for entry in history:
                entry["timestamp"] = now

            update_data = {
                **data,
                "updatedAt": now,
            }
            update_operation = {
                "$set": update_data,
            }

            if history:
                update_operation["$push"] = {
                    "history": {
                        "$each": history,
                    }
                }

            query = {"_id": ObjectId(id)}
            if expected_stage is not None:
                query["stage"] = expected_stage

            result = await self.collection.update_one(
                query,
                update_operation,
            )

            return result.modified_count > 0

        except DuplicateKeyError:
            raise DuplicateException("Lead")
        except InvalidId:
            raise ValidationException("Invalid ID format.")

    async def find_by_stage(
        self,
        stage: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return leads filtered by stage."""

        cursor = (
            self.collection.find({"stage": stage})
            .sort("createdAt", -1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def find_by_assigned_to(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 100,
        stage: str | None = None,
    ) -> list[dict]:
        """Return leads assigned to a specific user."""

        query = {
            "$or": [
                {"assignedTo": user_id},
                {"assignedToIds": user_id},
            ]
        }
        if stage:
            query["stage"] = stage

        cursor = (
            self.collection.find(query)
            .sort("createdAt", -1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def find_by_email(
        self,
        email: str,
    ) -> dict | None:
        """Find a lead by email address."""

        return await self.find_one(
            {"email": email}
        )

    async def get_all_sorted(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all leads sorted by creation date."""

        cursor = (
            self.collection.find()
            .sort("createdAt", -1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def add_history_entry(
        self,
        lead_id: str,
        entry: dict,
    ) -> bool:
        """Add a history entry to a lead."""

        now = datetime.now(timezone.utc)

        entry["timestamp"] = now

        result = await self.collection.update_one(
            {"_id": ObjectId(lead_id)},
            {
                "$push": {
                    "history": entry
                },
                "$set": {
                    "updatedAt": now
                },
            },
        )

        return result.modified_count > 0

    async def update_contact_details(
        self,
        lead_id: str,
        data: dict,
    ) -> bool:
        """Update contact-supplied lead details without changing ownership or stage."""

        if not data:
            return False

        try:
            result = await self.collection.update_one(
                {"_id": ObjectId(lead_id)},
                {
                    "$set": {
                        **data,
                        "updatedAt": datetime.now(timezone.utc),
                    }
                },
            )
            return result.modified_count > 0
        except InvalidId:
            raise ValidationException("Invalid ID format.")

    async def update_client_phone(
        self,
        client_id: str,
        phone: str | None,
    ) -> bool:
        """Keep a converted lead's phone aligned with its client profile."""

        result = await self.collection.update_many(
            {"clientId": client_id},
            {
                "$set": {
                    "phone": phone,
                    "updatedAt": datetime.now(timezone.utc),
                }
            },
        )
        return result.modified_count > 0

    async def count_all(
        self,
    ) -> int:
        """Return the total number of leads."""

        return await self.count({})

    async def get_recent(
        self,
        limit: int = 10,
    ) -> list[dict]:
        """Return the most recently created leads."""

        cursor = (
            self.collection.find()
            .sort("createdAt", -1)
            .limit(limit)
        )

        return [doc async for doc in cursor]
