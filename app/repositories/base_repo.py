"""Base Repository."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from app.db.database import db
from app.exceptions import ValidationException


class BaseRepository:
    """Base repository with common CRUD operations."""

    def __init__(self, collection_name: str):
        self.collection = db[collection_name]
        self.collection_name = collection_name

    async def find_by_id(
        self,
        id: str,
    ) -> dict | None:
        """Find a document by its ID."""

        try:
            return await self.collection.find_one(
                {"_id": ObjectId(id)}
            )
        except (InvalidId, TypeError):
            raise ValidationException(
                "Invalid ID format."
            )

    async def find_one(
        self,
        query: dict,
    ) -> dict | None:
        """Find a single document."""

        return await self.collection.find_one(query)

    async def find_many(
        self,
        query: dict | None = None,
        skip: int = 0,
        limit: int = 100,
        projection: dict | None = None,
    ) -> list[dict]:
        """Find multiple documents with pagination."""

        query = query or {}

        cursor = (
            self.collection.find(query, projection)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def create(
        self,
        data: dict,
    ) -> str:
        """Create a new document."""

        now = datetime.now(timezone.utc)

        data["createdAt"] = now
        data["updatedAt"] = now

        result = await self.collection.insert_one(data)

        return str(result.inserted_id)

    async def update(
        self,
        id: str,
        data: dict,
    ) -> bool:
        """Update a document by its ID."""

        try:
            data["updatedAt"] = datetime.now(
                timezone.utc
            )

            result = await self.collection.update_one(
                {"_id": ObjectId(id)},
                {"$set": data},
            )

            return result.modified_count > 0

        except (InvalidId, TypeError):
            raise ValidationException(
                "Invalid ID format."
            )

    async def delete(
        self,
        id: str,
    ) -> bool:
        """Delete a document by its ID."""

        try:
            result = await self.collection.delete_one(
                {"_id": ObjectId(id)}
            )

            return result.deleted_count > 0

        except (InvalidId, TypeError):
            raise ValidationException(
                "Invalid ID format."
            )

    async def count(
        self,
        query: dict | None = None,
    ) -> int:
        """Count documents matching a query."""

        query = query or {}

        return await self.collection.count_documents(
            query
        )

    async def get_next_sequence(
        self,
        sequence_name: str,
    ) -> int:
        """Return the next sequence number."""

        result = await db["counters"].find_one_and_update(
            {"_id": sequence_name},
            {
                "$inc": {
                    "sequence": 1
                },
                "$setOnInsert": {
                    "createdAt": datetime.now(
                        timezone.utc
                    )
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        return result["sequence"]
