"""Contact Repository."""

from app.repositories.base_repo import BaseRepository


class ContactRepository(BaseRepository):
    """Repository for contact form operations."""

    def __init__(self):
        super().__init__("contact_forms")

    async def find_by_email(
        self,
        email: str,
    ) -> dict | None:
        """Find the latest contact submission by email."""

        return await self.find_one(
            {"email": email}
        )

    async def count_all(
        self,
    ) -> int:
        """Return the total number of contact form submissions."""

        return await self.count({})

    async def get_recent_contacts(
        self,
        limit: int = 5,
    ) -> list[dict]:
        """Return the most recent contact form submissions."""

        cursor = (
            self.collection.find()
            .sort("createdAt", -1)
            .limit(limit)
        )

        return [doc async for doc in cursor]