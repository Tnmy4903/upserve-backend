"""
Projects API
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.api.dependencies import require_roles
from app.db.schemas import (
    BudgetUpdate,
    InvoiceGenerate,
    InvoiceOut,
    PaymentScheduleUpdate,
    ProjectOut,
    StatusUpdate,
)
from app.exceptions import AuthorizationException, exception_to_http
from app.services.invoice_service import InvoiceService
from app.services.project_service import ProjectService


project_router = APIRouter()

project_service = ProjectService()
invoice_service = InvoiceService()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def require_client(
    current_user: dict,
) -> None:
    """Allow only clients."""

    if current_user.get("role") != "client":
        raise AuthorizationException(
            "Only clients can access this endpoint."
        )


def require_admin(
    current_user: dict,
) -> None:
    """Allow only Super Admin and Sub Admin."""

    if current_user.get("role") not in [
        "super_admin",
        "sub_admin",
    ]:
        raise AuthorizationException(
            "Admin access only."
        )


def require_project_editor(
    current_user: dict,
) -> None:
    """Allow Super Admin and Sub Admin project management actions."""

    if current_user.get("role") not in ["super_admin", "sub_admin"]:
        raise AuthorizationException(
            "Only Super Admin or Sub Admin can perform this action."
        )


# ------------------------------------------------------------------
# Client - My Projects
# ------------------------------------------------------------------

@project_router.get(
    "/",
    response_model=list[ProjectOut],
)
async def get_my_projects(
    current_user: dict = Depends(get_current_user),
):
    """Get projects for the current client."""

    try:
        require_client(current_user)
        return await project_service.get_my_projects(current_user["id"])
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Admin - All Projects
# ------------------------------------------------------------------

@project_router.get(
    "/all",
    response_model=list[ProjectOut],
)
async def get_all_projects(
    current_user: dict = Depends(get_current_user),
):
    """Get all projects."""

    try:
        require_admin(current_user)
        return await project_service.get_all_projects(current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@project_router.get(
    "/{project_id}",
    response_model=ProjectOut,
)
async def get_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get one project using role-aware access rules."""

    try:
        return await project_service.get_project_by_id(
            project_id,
            current_user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Admin - Update Status
# ------------------------------------------------------------------

@project_router.patch(
    "/{project_id}/status",
)
async def update_project_status(
    project_id: str,
    payload: StatusUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update project status."""

    try:
        require_project_editor(current_user)
        await project_service.update_status(
            project_id,
            payload.status,
            current_user,
        )
        return {"message": "Project status updated successfully."}
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Admin - Update Budget
# ------------------------------------------------------------------

@project_router.patch(
    "/{project_id}/budget",
)
async def update_budget(
    project_id: str,
    payload: BudgetUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update project budget."""

    try:
        require_project_editor(current_user)
        await project_service.set_budget(
            project_id,
            payload.budget,
            current_user,
        )
        return {"message": "Project budget updated successfully."}
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@project_router.patch(
    "/{project_id}/payment-schedule",
)
async def update_payment_schedule(
    project_id: str,
    payload: PaymentScheduleUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update the three-stage payment schedule before invoice generation."""

    try:
        await project_service.set_payment_schedule(
            project_id,
            payload.dict(),
            current_user,
        )
        return {"message": "Payment schedule updated successfully."}
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Admin - Generate Invoice
# ------------------------------------------------------------------

@project_router.post(
    "/{project_id}/invoice",
    response_model=InvoiceOut,
)
async def generate_invoice(
    project_id: str,
    payload: InvoiceGenerate | None = None,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    """Generate invoice for a project."""

    try:
        return await invoice_service.generate_invoice(project_id, current_user, payload.dueDate if payload else None, payload.stage.value if payload and payload.stage else None)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)
