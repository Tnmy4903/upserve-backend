"""
Activity Logs API
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import require_roles
from app.db.schemas import ActivityLogOut
from app.exceptions import exception_to_http
from app.services.activitylog_service import ActivityLogService


activity_router = APIRouter()

activity_service = ActivityLogService()


@activity_router.get(
    "/activity-logs",
    response_model=list[ActivityLogOut],
)
async def get_activity_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can view activity logs.")),
):
    """Get activity logs."""

    try:
        return await activity_service.get_all_logs(
            skip=skip,
            limit=limit,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@activity_router.get(
    "/activity-logs/user/{user_id}",
    response_model=list[ActivityLogOut],
)
async def get_user_activity_logs(
    user_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can view user activity.")),
):
    """Get activity logs for a user."""

    try:
        return await activity_service.get_user_activity_logs(
            user_id=user_id,
            skip=skip,
            limit=limit,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@activity_router.get(
    "/activity-logs/entity/{entity_id}",
    response_model=list[ActivityLogOut],
)
async def get_entity_activity(
    entity_id: str,
    entity: str | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can view activity logs.")),
):
    """Get activity history for an entity."""

    try:
        return await activity_service.get_entity_history(
            entity_id=entity_id,
            entity=entity,
            skip=skip,
            limit=limit,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@activity_router.get(
    "/activity-logs/{log_id}",
    response_model=ActivityLogOut,
)
async def get_activity_log(
    log_id: str,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can view activity logs.")),
):
    """Get a single activity log."""

    try:
        return await activity_service.get_activity_log(
            log_id
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


