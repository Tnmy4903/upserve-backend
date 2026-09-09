"""Portfolio Repository."""

from app.repositories.base_repo import BaseRepository


class PortfolioRepository(BaseRepository):
    """Repository for portfolio CMS operations."""

    def __init__(self):
        super().__init__("portfolio")

    async def find_by_slug(
        self,
        slug: str,
    ) -> dict | None:
        """Find a portfolio item by its slug."""

        return await self.find_one(
            {"slug": slug}
        )

    async def find_published(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all published portfolio items."""

        cursor = (
            self.collection.find(
                {"published": True}
            )
            .sort("displayOrder", 1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def find_by_category(
        self,
        category: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return published portfolio items for a category."""

        cursor = (
            self.collection.find(
                {
                    "category": category,
                    "published": True,
                }
            )
            .sort("displayOrder", 1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def get_featured(
        self,
        limit: int = 10,
    ) -> list[dict]:
        """Return featured published portfolio items."""

        cursor = (
            self.collection.find(
                {
                    "featured": True,
                    "published": True,
                }
            )
            .sort("displayOrder", 1)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def get_all_items(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all portfolio items."""

        cursor = (
            self.collection.find()
            .sort("displayOrder", 1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]