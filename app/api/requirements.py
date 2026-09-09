"""
Requirements Module API
"""

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)

from app.api.auth import get_current_user
from app.api.dependencies import require_roles
from app.db.schemas import (
    RequirementApprovalRequest,
    RequirementCreate,
    RequirementOut,
    RequirementUpdate,
)
from app.exceptions import (
    AuthorizationException,
    exception_to_http,
)
from app.services.requirement_service import RequirementService


requirement_router = APIRouter()

requirement_service = RequirementService()


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


def require_client_requirement_writer(current_user: dict) -> None:
    """Only clients can submit or revise their project requirement."""

    if current_user.get("role") != "client":
        raise AuthorizationException(
            "Only clients can create or update project requirements."
        )


# ------------------------------------------------------------------
# Create Requirement
# ------------------------------------------------------------------

@requirement_router.post(
    "/requirements",
    response_model=RequirementOut,
)
async def create_requirement(
    req: RequirementCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a requirement."""

    try:
        require_client_requirement_writer(
            current_user
        )

        return await requirement_service.create_requirement(
            current_user=current_user,
            created_by=current_user["id"],
            lead_id=req.leadId,
            project_id=req.projectId,
            **req.dict(
                exclude={"leadId", "projectId"}
            ),
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Get Requirement
# ------------------------------------------------------------------

@requirement_router.get(
    "/requirements/{requirement_id}",
    response_model=RequirementOut,
)
async def get_requirement(
    requirement_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get requirement details."""

    try:
        return await requirement_service.get_requirement(
            requirement_id,
            current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Update Requirement
# ------------------------------------------------------------------

@requirement_router.put(
    "/requirements/{requirement_id}",
    response_model=RequirementOut,
)
async def update_requirement(
    requirement_id: str,
    updates: RequirementUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update a requirement."""

    try:
        require_client_requirement_writer(
            current_user
        )

        return await requirement_service.update_requirement(
            requirement_id=requirement_id,
            current_user=current_user,
            updated_by=current_user["id"],
            **updates.dict(exclude_unset=True),
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Approve Requirement
# ------------------------------------------------------------------

@requirement_router.patch(
    "/requirements/{requirement_id}/approve",
    response_model=RequirementOut,
)
async def approve_requirement(
    requirement_id: str,
    payload: RequirementApprovalRequest,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    """Approve a requirement."""

    try:
        return await requirement_service.approve_requirement(
            requirement_id=requirement_id,
            current_user=current_user,
            approved_by=current_user["id"],
            remarks=payload.remarks,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Request Changes
# ------------------------------------------------------------------

@requirement_router.patch(
    "/requirements/{requirement_id}/request-changes",
    response_model=RequirementOut,
)
async def request_requirement_changes(
    requirement_id: str,
    payload: RequirementApprovalRequest,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    """Request changes to a requirement."""

    try:
        return await requirement_service.request_changes(
            requirement_id=requirement_id,
            current_user=current_user,
            remarks=payload.remarks,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Delete Requirement
# ------------------------------------------------------------------

@requirement_router.delete(
    "/requirements/{requirement_id}",
    response_model=dict,
)
async def delete_requirement(
    requirement_id: str,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    """Delete a requirement."""

    try:
        return await requirement_service.delete_requirement(
            requirement_id=requirement_id,
            current_user=current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Get Lead Requirements
# ------------------------------------------------------------------

@requirement_router.get(
    "/leads/{lead_id}/requirements",
    response_model=RequirementOut,
)
async def get_lead_requirements(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get requirements for a lead."""

    try:
        return await requirement_service.get_lead_requirements(
            lead_id,
            current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Get Project Requirements
# ------------------------------------------------------------------

@requirement_router.get(
    "/projects/{project_id}/requirements",
    response_model=RequirementOut,
)
async def get_project_requirements(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get requirements for a project."""

    try:
        return await requirement_service.get_project_requirements(
            project_id,
            current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@requirement_router.post(
    "/requirements/{requirement_id}/attachment",
    response_model=RequirementOut,
)
async def upload_requirement_attachment(
    requirement_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Attach an optional reference file to a client requirement."""

    try:
        require_client_requirement_writer(current_user)
        return await requirement_service.upload_attachment(
            requirement_id,
            file,
            current_user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@requirement_router.get(
    "/requirements/{requirement_id}/attachment",
)
async def download_requirement_attachment(
    requirement_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Download an authorized requirement attachment."""

    try:
        file_path, file_name, content_type = await requirement_service.download_attachment(
            requirement_id,
            current_user,
        )
        from fastapi.responses import FileResponse

        return FileResponse(
            path=file_path,
            media_type=content_type,
            filename=file_name,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)
