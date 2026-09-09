"""
Blogs API
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import require_roles
from app.db.schemas import BlogCreate, BlogOut
from app.exceptions import exception_to_http
from app.services.blog_service import BlogService


blog_router = APIRouter()

blog_service = BlogService()


@blog_router.post(
    "/",
    response_model=BlogOut,
)
async def create_blog(
    blog: BlogCreate,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can create blogs")),
):
    """Create blog."""

    try:
        return await blog_service.create_blog(
            current_user=current_user,
            title=blog.title,
            slug=blog.slug,
            content=blog.content,
            thumbnail=blog.thumbnail,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@blog_router.get(
    "/",
    response_model=list[BlogOut],
)
async def get_all_blogs():
    """Get all blogs."""

    try:
        return await blog_service.get_all_blogs()

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@blog_router.get(
    "/{slug}",
    response_model=BlogOut,
)
async def get_blog_by_slug(
    slug: str,
):
    """Get blog by slug."""

    try:
        return await blog_service.get_blog_by_slug(
            slug
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@blog_router.delete(
    "/{blog_id}",
    response_model=dict,
)
async def delete_blog(
    blog_id: str,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can delete blogs")),
):
    """Delete blog."""

    try:
        return await blog_service.delete_blog(
            blog_id=blog_id,
            current_user=current_user,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


