"""Repository for public Blog and Portfolio media."""
from app.repositories.base_repo import BaseRepository


class ContentMediaRepository(BaseRepository):
    def __init__(self):
        super().__init__("content_media")

    async def ensure_indexes(self):
        await self.collection.create_index("storedFileName", unique=True, name="content_media_stored_filename_unique")

    async def find_by_stored_filename(self, filename: str) -> dict | None:
        return await self.find_one({"storedFileName": filename})
