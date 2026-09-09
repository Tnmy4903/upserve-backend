"""
Project Timeline API
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from app.api.auth import get_current_user
from app.api.dependencies import require_roles
from app.db.schemas import (
    TimelineEventCreate,
    TimelineEventOut,
)
from app.exceptions import (
    AuthorizationException,
    exception_to_http,
)
from app.services.timeline_service import TimelineService


timeline_router = APIRouter()

timeline_service = TimelineService()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def require_admin(
    current_user: dict,
) -> None:
    """Allow only Super Admin and Sub Admin."""

    if current_user.get("role") not in (
        "super_admin",
        "sub_admin",
    ):
        raise AuthorizationException(
            "Admin access only."
        )


# ------------------------------------------------------------------
# Add Timeline Event
# ------------------------------------------------------------------

@timeline_router.post(
    "/projects/{project_id}/timeline",
    response_model=TimelineEventOut,
)
async def add_timeline_event(
    project_id: str,
    event: TimelineEventCreate,
    current_user: dict = Depends(get_current_user),
):
    """Add a timeline event."""

    try:
        require_admin(
            current_user
        )

        return await timeline_service.add_timeline_event(
            project_id=project_id,
            title=event.title,
            description=event.description,
            created_by=current_user["id"],
            current_user=current_user,
            client_visible=event.clientVisible,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Get Project Timeline
# ------------------------------------------------------------------

@timeline_router.get(
    "/projects/{project_id}/timeline",
    response_model=list[TimelineEventOut],
)
async def get_project_timeline(
    project_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    """Get project timeline."""

    try:
        return await timeline_service.get_project_timeline(
            project_id=project_id,
            skip=skip,
            limit=limit,
            current_user=current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Delete Timeline Event
# ------------------------------------------------------------------

@timeline_router.delete(
    "/timeline/{event_id}",
    response_model=dict,
)
async def delete_timeline_event(
    event_id: str,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    """Delete a timeline event."""

    try:
        return await timeline_service.delete_timeline_event(
            event_id,
            current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


