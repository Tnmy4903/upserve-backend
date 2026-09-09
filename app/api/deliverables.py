"""Deliverables Management API."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.db.schemas import (
    DeliverableStatusUpdate,
    DeliverablesCreate,
    DeliverablesOut,
    DeliverablesUpdate,
)
from app.exceptions import AuthorizationException, exception_to_http
from app.services.deliverables_service import DeliverablesService


deliverables_router = APIRouter()
deliverables_service = DeliverablesService()


def require_admin(current_user: dict) -> None:
    if current_user.get("role") not in {"super_admin", "sub_admin"}:
        raise AuthorizationException("Only admins can manage deliverables.")


@deliverables_router.post("/projects/{project_id}/deliverables", response_model=DeliverablesOut)
async def create_deliverable(project_id: str, deliverable: DeliverablesCreate, current_user: dict = Depends(get_current_user)):
    try:
        require_admin(current_user)
        return await deliverables_service.create_deliverable(project_id=project_id, current_user=current_user, **deliverable.dict())
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@deliverables_router.get("/projects/{project_id}/deliverables", response_model=list[DeliverablesOut])
async def get_deliverables(project_id: str, current_user: dict = Depends(get_current_user)):
    try:
        return await deliverables_service.get_deliverables(project_id, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@deliverables_router.get("/deliverables/{deliverable_id}", response_model=DeliverablesOut)
async def get_deliverable(deliverable_id: str, current_user: dict = Depends(get_current_user)):
    try:
        return await deliverables_service.get_deliverable(deliverable_id, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@deliverables_router.patch("/deliverables/{deliverable_id}", response_model=DeliverablesOut)
async def update_deliverable(deliverable_id: str, updates: DeliverablesUpdate, current_user: dict = Depends(get_current_user)):
    try:
        require_admin(current_user)
        return await deliverables_service.update_deliverable(deliverable_id, current_user, **updates.dict(exclude_unset=True))
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@deliverables_router.patch("/deliverables/{deliverable_id}/status", response_model=DeliverablesOut)
async def update_deliverable_status(deliverable_id: str, payload: DeliverableStatusUpdate, current_user: dict = Depends(get_current_user)):
    try:
        require_admin(current_user)
        return await deliverables_service.update_status(deliverable_id, payload.status.value, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@deliverables_router.delete("/deliverables/{deliverable_id}", response_model=dict)
async def delete_deliverable(deliverable_id: str, current_user: dict = Depends(get_current_user)):
    try:
        return await deliverables_service.delete_deliverable(deliverable_id, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)
