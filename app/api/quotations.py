"""
Quotation Management API
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from fastapi.responses import FileResponse

from app.api.auth import get_current_user
from app.api.dependencies import require_roles
from app.db.schemas import (
    QuotationCreate,
    QuotationOut,
    QuotationAcceptanceOut,
    QuotationStatus,
    QuotationUpdate,
)
from app.exceptions import (
    AuthorizationException,
    exception_to_http,
)
from app.services.quotation_service import QuotationService


quotation_router = APIRouter()

quotation_service = QuotationService()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def require_admin(
    current_user: dict,
) -> None:
    """Allow only Super Admin for commercial quotation work."""

    if current_user.get("role") != "super_admin":
        raise AuthorizationException(
            "Only Super Admin can manage quotations."
        )


# ------------------------------------------------------------------
# Create Quotation
# ------------------------------------------------------------------

@quotation_router.post(
    "/quotations",
    response_model=QuotationOut,
)
async def create_quotation(
    quotation: QuotationCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a quotation."""

    try:
        require_admin(
            current_user
        )

        return await quotation_service.create_quotation(
            current_user=current_user,
            client_id=quotation.clientId,
            lead_id=quotation.leadId,
            project_id=quotation.projectId,
            services=quotation.services,
            items=[item.dict() for item in quotation.items],
            timeline=quotation.timeline,
            validity=quotation.validity,
            terms=quotation.terms,
            notes=quotation.notes,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Get Quotations
# ------------------------------------------------------------------

@quotation_router.get(
    "/quotations",
    response_model=list[QuotationOut],
)
async def get_quotations(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: QuotationStatus | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Get quotations."""

    try:
        return await quotation_service.get_quotations(
            current_user=current_user,
            skip=skip,
            limit=limit,
            status=status.value if status else None,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Get Quotation
# ------------------------------------------------------------------

@quotation_router.get(
    "/quotations/{quotation_id}",
    response_model=QuotationOut,
)
async def get_quotation(
    quotation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get quotation details."""

    try:
        return await quotation_service.get_quotation(
            quotation_id,
            current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Update Quotation
# ------------------------------------------------------------------

@quotation_router.put(
    "/quotations/{quotation_id}",
    response_model=QuotationOut,
)
async def update_quotation(
    quotation_id: str,
    updates: QuotationUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update a quotation."""

    try:
        require_admin(
            current_user
        )

        update_dict = updates.dict(
            exclude_unset=True
        )

        return await quotation_service.update_quotation(
            quotation_id=quotation_id,
            current_user=current_user,
            **update_dict,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Send Quotation
# ------------------------------------------------------------------

@quotation_router.post(
    "/quotations/{quotation_id}/send",
    response_model=QuotationOut,
)
async def send_quotation(
    quotation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Send a quotation to the client."""

    try:
        require_admin(
            current_user
        )

        return await quotation_service.send_quotation(
            quotation_id,
            current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Accept Quotation
# ------------------------------------------------------------------

@quotation_router.post(
    "/quotations/{quotation_id}/accept",
    response_model=QuotationAcceptanceOut,
)
async def accept_quotation(
    quotation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Accept a quotation."""

    try:
        return await quotation_service.accept_quotation(
            quotation_id,
            current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Reject Quotation
# ------------------------------------------------------------------

@quotation_router.post(
    "/quotations/{quotation_id}/reject",
    response_model=QuotationOut,
)
async def reject_quotation(
    quotation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Reject a quotation."""

    try:
        return await quotation_service.reject_quotation(
            quotation_id,
            current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Request Revision
# ------------------------------------------------------------------

@quotation_router.post(
    "/quotations/{quotation_id}/request-revision",
    response_model=QuotationOut,
)
async def request_revision(
    quotation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Request a quotation revision."""

    try:
        return await quotation_service.request_revision(
            quotation_id,
            current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Delete Quotation
# ------------------------------------------------------------------

@quotation_router.delete(
    "/quotations/{quotation_id}",
    response_model=dict,
)
async def delete_quotation(
    quotation_id: str,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    """Delete a quotation."""

    try:
        return await quotation_service.delete_quotation(
            quotation_id,
            current_user,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@quotation_router.get(
    "/quotations/{quotation_id}/pdf",
)
async def download_quotation_pdf(
    quotation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Generate and download the detailed quotation PDF."""

    try:
        file_path, filename = await quotation_service.generate_quotation_pdf_file(
            quotation_id,
            current_user,
        )
        return FileResponse(
            path=file_path,
            media_type="application/pdf",
            filename=filename,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)
