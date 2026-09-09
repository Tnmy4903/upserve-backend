"""Blog Repository."""

from bson import ObjectId

from app.repositories.base_repo import BaseRepository


class BlogRepository(BaseRepository):
    """Repository for blog operations."""

    def __init__(self):
        super().__init__("blogs")

    async def find_by_slug(
        self,
        slug: str,
    ) -> dict | None:
        """Find a blog by its slug."""

        return await self.find_one(
            {"slug": slug}
        )

    async def slug_exists(
        self,
        slug: str,
    ) -> bool:
        """Check whether a blog slug already exists."""

        blog = await self.find_by_slug(slug)

        return blog is not None

    async def get_all_sorted(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all blogs sorted by creation date."""

        cursor = (
            self.collection.find()
            .sort("createdAt", -1)
            .skip(skip)
            .limit(limit)
        )

        return [doc async for doc in cursor]

    async def increment_views(
        self,
        blog_id: str,
    ) -> bool:
        """Increment the view count of a blog."""

        result = await self.collection.update_one(
            {"_id": ObjectId(blog_id)},
            {
                "$inc": {
                    "views": 1
                }
            },
        )

        return result.matched_count > 0