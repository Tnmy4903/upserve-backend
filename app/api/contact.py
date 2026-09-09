"""
Contact Form API
"""

from fastapi import APIRouter, HTTPException

from app.db.schemas import ContactFormCreate, ContactFormOut
from app.exceptions import exception_to_http
from app.services.contact_service import ContactService


contact_router = APIRouter()

contact_service = ContactService()


@contact_router.post(
    "/contact",
    response_model=ContactFormOut,
)
async def submit_contact_form(
    form: ContactFormCreate,
):
    """Submit contact form."""

    try:
        return await contact_service.submit_contact_form(
            name=form.name,
            email=form.email,
            phone=form.phone,
            company_name=form.companyName,
            business=form.business,
            message=form.message,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)
