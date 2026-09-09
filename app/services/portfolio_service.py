from app.exceptions import DuplicateException, ResourceNotFoundException, ValidationException
from app.logger import logger_portfolio
from app.repositories.portfolio_repo import PortfolioRepository
from app.services.activitylog_service import ActivityLogService


class PortfolioService:
    """Service for portfolio management."""

    def __init__(self):
        self.portfolio_repo = PortfolioRepository()
        self.activity_service = ActivityLogService()

    async def create_portfolio_item(
        self,
        current_user: dict,
        title: str,
        slug: str,
        category: str,
        description: str,
        tech_stack: list,
        website_url: str | None = None,
        github_url: str | None = None,
        images: list | None = None,
        featured: bool = False,
        display_order: int = 0,
        published: bool = True,
    ) -> dict:
        """Create a portfolio item."""

        slug = slug.strip().lower()

        if not slug:
            raise ValidationException(
                "Slug cannot be empty."
            )

        if await self.portfolio_repo.find_by_slug(
            slug
        ):
            raise DuplicateException(
                "Slug"
            )

        item_data = {
            "title": title.strip(),
            "slug": slug,
            "category": category.strip().lower(),
            "description": description.strip(),
            "techStack": tech_stack,
            "websiteUrl": website_url,
            "githubUrl": github_url,
            "images": images or [],
            "featured": featured,
            "displayOrder": display_order,
            "published": published,
        }

        item_id = await self.portfolio_repo.create(
            item_data
        )

        created_item = await self.portfolio_repo.find_by_id(
            item_id
        )

        created_item["id"] = str(
            created_item["_id"]
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Portfolio Item Created",
            entity="Portfolio",
            entity_id=item_id,
        )

        logger_portfolio.info(
            f"Portfolio item '{title}' created."
        )

        return created_item

    async def update_portfolio_item(
        self,
        item_id: str,
        current_user: dict,
        **updates,
    ) -> dict:
        """Update a portfolio item."""

        item = await self.portfolio_repo.find_by_id(
            item_id
        )

        if not item:
            raise ResourceNotFoundException(
                "Portfolio Item"
            )

        if "slug" in updates:
            updates["slug"] = (
                updates["slug"]
                .strip()
                .lower()
            )

            existing = await self.portfolio_repo.find_by_slug(
                updates["slug"]
            )

            if (
                existing
                and str(existing["_id"]) != item_id
            ):
                raise DuplicateException(
                    "Slug"
                )

        updated = await self.portfolio_repo.update(
            item_id,
            updates,
        )

        if not updated:
            raise ValidationException(
                "Failed to update portfolio item."
            )

        updated_item = await self.portfolio_repo.find_by_id(
            item_id
        )

        updated_item["id"] = str(
            updated_item["_id"]
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Portfolio Item Updated",
            entity="Portfolio",
            entity_id=item_id,
        )

        logger_portfolio.info(
            f"Portfolio item {item_id} updated."
        )

        return updated_item

    async def get_published_items(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all published portfolio items."""

        items = await self.portfolio_repo.find_published(
            skip,
            limit,
        )

        for item in items:
            item["id"] = str(
                item["_id"]
            )

        return items

    async def get_featured_items(
        self,
        limit: int = 10,
    ) -> list[dict]:
        """Return featured portfolio items."""

        items = await self.portfolio_repo.get_featured(
            limit
        )

        for item in items:
            item["id"] = str(
                item["_id"]
            )

        return items

    async def get_items_by_category(
        self,
        category: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return portfolio items by category."""

        items = await self.portfolio_repo.find_by_category(
            category,
            skip,
            limit,
        )

        for item in items:
            item["id"] = str(
                item["_id"]
            )

        return items

    async def get_portfolio_item(
        self,
        slug: str,
    ) -> dict:
        """Return a published portfolio item."""

        item = await self.portfolio_repo.find_by_slug(
            slug
        )

        if (
            not item
            or not item.get("published")
        ):
            raise ResourceNotFoundException(
                "Portfolio Item"
            )

        item["id"] = str(
            item["_id"]
        )

        return item

    async def get_all_items(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all portfolio items."""

        items = await self.portfolio_repo.get_all_items(
            skip,
            limit,
        )

        for item in items:
            item["id"] = str(
                item["_id"]
            )

        return items

    async def delete_portfolio_item(
        self,
        item_id: str,
        current_user: dict,
    ) -> dict:
        """Delete a portfolio item."""

        item = await self.portfolio_repo.find_by_id(
            item_id
        )

        if not item:
            raise ResourceNotFoundException(
                "Portfolio Item"
            )

        deleted = await self.portfolio_repo.delete(
            item_id
        )

        if not deleted:
            raise ValidationException(
                "Failed to delete portfolio item."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Portfolio Item Deleted",
            entity="Portfolio",
            entity_id=item_id,
        )

        logger_portfolio.info(
            f"Portfolio item {item_id} deleted."
        )

        return {
            "message": "Portfolio item deleted successfully."
        }