"""Blog Service."""

from app.exceptions import DuplicateException, ResourceNotFoundException, ValidationException
from app.logger import logger_blog
from app.repositories.blog_repo import BlogRepository
from app.services.activitylog_service import ActivityLogService


class BlogService:
    """Service for blog management."""

    def __init__(self):
        self.blog_repo = BlogRepository()
        self.activity_service = ActivityLogService()

    async def create_blog(
        self,
        current_user: dict,
        title: str,
        slug: str,
        content: str,
        thumbnail: str | None,
    ) -> dict:
        """Create a new blog."""

        title = title.strip()
        slug = slug.strip().lower()
        content = content.strip()
        thumbnail = str(thumbnail) if thumbnail else None

        if await self.blog_repo.slug_exists(
            slug
        ):
            raise DuplicateException(
                "Slug"
            )

        blog_data = {
            "title": title,
            "slug": slug,
            "content": content,
            "thumbnail": thumbnail,
            "author": current_user["name"],
            "views": 0,
        }

        blog_id = await self.blog_repo.create(
            blog_data
        )

        created_blog = await self.blog_repo.find_by_id(
            blog_id
        )

        created_blog["id"] = str(
            created_blog["_id"]
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Blog Created",
            entity="Blog",
            entity_id=blog_id,
        )

        logger_blog.info(
            f"Blog created: {slug}"
        )

        return created_blog

    async def get_all_blogs(
        self,
    ) -> list[dict]:
        """Return all blogs."""

        blogs = await self.blog_repo.get_all_sorted()

        for blog in blogs:
            blog["id"] = str(
                blog["_id"]
            )

        return blogs

    async def get_blog_by_slug(
        self,
        slug: str,
    ) -> dict:
        """Return a blog by its slug."""

        blog = await self.blog_repo.find_by_slug(
            slug
        )

        if not blog:
            raise ResourceNotFoundException(
                "Blog"
            )

        await self.blog_repo.increment_views(
            str(blog["_id"])
        )

        blog["views"] += 1
        blog["id"] = str(
            blog["_id"]
        )

        return blog

    async def delete_blog(
        self,
        blog_id: str,
        current_user: dict,
    ) -> dict:
        """Delete a blog."""

        blog = await self.blog_repo.find_by_id(
            blog_id
        )

        if not blog:
            raise ResourceNotFoundException(
                "Blog"
            )

        deleted = await self.blog_repo.delete(
            blog_id
        )

        if not deleted:
            raise ValidationException(
                "Failed to delete blog."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Blog Deleted",
            entity="Blog",
            entity_id=blog_id,
        )

        logger_blog.info(
            f"Blog deleted: {blog_id}"
        )

        return {
            "message": "Blog deleted successfully."
        }
