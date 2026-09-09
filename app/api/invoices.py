"""
Invoice API
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.auth import get_current_user
from app.api.dependencies import require_roles
from app.db.schemas import ActionMessage, InvoiceOut, InvoiceSendResponse, PaymentUpdate
from app.exceptions import AuthorizationException, exception_to_http
from app.services.invoice_service import InvoiceService


invoice_router = APIRouter()

invoice_service = InvoiceService()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def require_project_invoice_viewer(
    current_user: dict,
) -> None:
    """Allow authenticated roles to view an authorized project invoice."""

    if current_user.get("role") not in {"client", "sub_admin", "super_admin"}:
        raise AuthorizationException(
            "Project invoice access required."
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


# ------------------------------------------------------------------
# Client - View Invoice by Project
# ------------------------------------------------------------------

@invoice_router.get(
    "/project/{project_id}",
    response_model=InvoiceOut,
)
async def get_invoice_by_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get invoice for a project."""
    try:
        require_project_invoice_viewer(current_user)
        return await invoice_service.get_invoice_by_project(
            project_id=project_id,
            current_user=current_user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)

@invoice_router.get(
    "/project/{project_id}/all",
    response_model=list[InvoiceOut],
)
async def get_invoices_by_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get all payment-stage invoices for a project."""
    try:
        require_project_invoice_viewer(current_user)
        return await invoice_service.get_invoices_by_project(project_id, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Admin - Get Invoice by Invoice ID
# ------------------------------------------------------------------

@invoice_router.get(
    "/{invoice_id}",
    response_model=InvoiceOut,
)
async def get_invoice(
    invoice_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get invoice by ID."""

    try:
        require_admin(current_user)
        return await invoice_service.get_invoice(invoice_id, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Admin - Send Invoice
# ------------------------------------------------------------------

@invoice_router.post(
    "/{invoice_id}/send",
    response_model=InvoiceSendResponse,
)
async def send_invoice(
    invoice_id: str,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    """Send invoice to client."""

    try:
        return await invoice_service.send_invoice_to_client(
            invoice_id,
            current_user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Admin - Update Payment Status
# ------------------------------------------------------------------

@invoice_router.patch(
    "/{invoice_id}/payment",
    response_model=ActionMessage,
)
async def update_payment_status(
    invoice_id: str,
    payload: PaymentUpdate,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    """Update invoice payment status."""

    try:
        await invoice_service.update_payment_status(
            invoice_id=invoice_id,
            is_paid=payload.isPaid,
            current_user=current_user,
            payment_amount=payload.paymentAmount,
            payment_reference=payload.paymentReference,
            payment_method=payload.paymentMethod,
        )
        return {"message": "Invoice payment status updated successfully."}
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@invoice_router.post(
    "/{invoice_id}/cancel",
    response_model=InvoiceOut,
)
async def cancel_invoice(
    invoice_id: str,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    """Cancel an unpaid invoice."""

    try:
        return await invoice_service.cancel_invoice(invoice_id, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@invoice_router.post(
    "/{invoice_id}/reconcile-send",
    response_model=InvoiceOut,
)
async def reconcile_invoice_send(
    invoice_id: str,
    current_user: dict = Depends(require_roles("super_admin", message="Only Super Admin can perform this action.")),
):
    """Release a stale uncertain invoice-send claim."""

    try:
        return await invoice_service.reconcile_stale_send(
            invoice_id,
            current_user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@invoice_router.get(
    "/{invoice_id}/download",
)
async def download_invoice(
    invoice_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Download an invoice after project-based authorization."""

    try:
        file_path, filename = await invoice_service.download_invoice(
            invoice_id,
            current_user,
        )
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="application/pdf",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)
