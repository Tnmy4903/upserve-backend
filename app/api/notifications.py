"""
Notifications API
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import get_current_user
from app.db.schemas import NotificationOut
from app.exceptions import exception_to_http
from app.services.notification_service import NotificationService


notification_router = APIRouter()

notification_service = NotificationService()


@notification_router.get(
    "/notifications",
    response_model=list[NotificationOut],
)
async def get_my_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    """Get notifications for current user."""

    try:
        return await notification_service.get_user_notifications(
            user_id=current_user["id"],
            skip=skip,
            limit=limit,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@notification_router.get(
    "/notifications/unread",
    response_model=list[NotificationOut],
)
async def get_unread_notifications(
    current_user: dict = Depends(get_current_user),
):
    """Get unread notifications."""

    try:
        return await notification_service.get_unread_notifications(
            user_id=current_user["id"],
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@notification_router.post(
    "/notifications/{notification_id}/read",
    response_model=NotificationOut,
)
async def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Mark notification as read."""

    try:
        return await notification_service.mark_as_read(
            notification_id=notification_id,
            current_user=current_user,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@notification_router.post(
    "/notifications/read-all",
    response_model=dict,
)
async def mark_all_read(
    current_user: dict = Depends(get_current_user),
):
    """Mark all notifications as read."""

    try:
        count = await notification_service.mark_all_as_read(
            current_user,
        )

        return {
            "message": f"Marked {count} notifications as read."
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@notification_router.delete(
    "/notifications/{notification_id}",
    response_model=dict,
)
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete notification."""

    try:
        return await notification_service.delete_notification(
            notification_id=notification_id,
            current_user=current_user,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@notification_router.post(
    "/notifications/clear-all",
    response_model=dict,
)
async def clear_all_notifications(
    current_user: dict = Depends(get_current_user),
):
    """Delete all notifications."""

    try:
        return await notification_service.clear_all_notifications(
            current_user,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)
