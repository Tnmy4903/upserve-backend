"""
Admin API
"""

from fastapi import APIRouter, Depends, Query, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import require_roles
from app.exceptions import AuthorizationException, exception_to_http
from app.services.admin_service import AdminService


admin_router = APIRouter()

admin_service = AdminService()


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def require_admin(
    current_user: dict,
) -> None:
    """Allow only Super Admin and Sub Admin."""

    if current_user.get("role") not in [
        "super_admin",
        "sub_admin",
    ]:
        raise AuthorizationException(
            "Admin access only"
        )


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------

@admin_router.get("/dashboard")
async def admin_dashboard(
    current_user: dict = Depends(get_current_user),
):
    """Get admin dashboard."""

    try:
        require_admin(current_user)
        return await admin_service.get_dashboard(current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------

@admin_router.get("/summary")
async def get_summary(
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can access global dashboard data.")),
):
    """Get dashboard summary."""

    try:
        return await admin_service.get_summary(current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Recent Activities
# ------------------------------------------------------------------

@admin_router.get("/recent-activities")
async def recent_activities(
    limit: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Number of recent activities",
    ),
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can access global dashboard data.")),
):
    """Get recent activity logs."""

    try:
        return await admin_service.get_recent_activities(limit, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# System Statistics
# ------------------------------------------------------------------

@admin_router.get("/system-stats")
async def system_stats(
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can access global dashboard data.")),
):
    """Get system statistics."""

    try:
        return await admin_service.get_system_stats(current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@admin_router.get("/reference-data")
async def reference_data(
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can access global dashboard data.")),
):
    """Return readable IDs and relationships for Super Admin support work."""

    try:
        return await admin_service.get_reference_data(current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)
