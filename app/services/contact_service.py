"""Contact Service."""

from app.logger import logger_contact
from app.repositories.contact_repo import ContactRepository
from app.repositories.lead_repo import LeadRepository
from app.repositories.user_repo import UserRepository
from app.services.activitylog_service import ActivityLogService
from app.services.email import send_contact_alert
from app.services.notification_service import NotificationService


class ContactService:
    """Service for contact form operations."""

    def __init__(self):
        self.contact_repo = ContactRepository()
        self.lead_repo = LeadRepository()
        self.user_repo = UserRepository()
        self.activity_service = ActivityLogService()
        self.notification_service = NotificationService()

    async def submit_contact_form(
        self,
        name: str,
        email: str,
        phone: str | None,
        company_name: str | None,
        business: str | None,
        message: str,
    ) -> dict:
        """Submit a contact form and create a CRM lead if required."""

        name = name.strip()
        email = email.strip().lower()
        phone = phone.strip() if phone else None
        company_name = company_name.strip() if company_name else None
        business = business.strip() if business else None
        message = message.strip()

        contact_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "companyName": company_name,
            "business": business,
            "message": message,
        }

        contact_id = await self.contact_repo.create(
            contact_data
        )

        created_contact = await self.contact_repo.find_by_id(
            contact_id
        )

        created_contact["id"] = str(
            created_contact["_id"]
        )

        existing_lead = await self.lead_repo.find_by_email(
            email
        )

        if existing_lead:
            await self.lead_repo.update_contact_details(
                str(existing_lead["_id"]),
                {
                    key: value
                    for key, value in {
                        "phone": phone,
                        "companyName": company_name,
                        "business": business,
                    }.items()
                    if value is not None
                },
            )
            await self.lead_repo.add_history_entry(
                str(existing_lead["_id"]),
                {
                    "action": "Website Contact Form Submitted Again",
                    "message": message,
                    "changedBy": "system",
                },
            )

            await self.activity_service.log_activity(
                user_id="system",
                user_role="system",
                action="Existing Lead Contacted Again",
                entity="Lead",
                entity_id=str(existing_lead["_id"]),
                details={
                    "source": "Website Contact Form",
                },
            )

        else:
            lead_data = {
                "companyName": company_name,
                "contactPerson": name,
                "phone": phone,
                "email": email,
                "business": business or "Website Enquiry",
                "leadSource": "Website Contact Form",
                "notes": message,
                "stage": "New",
                "assignedTo": None,
                "history": [],
            }

            lead_id = await self.lead_repo.create(
                lead_data
            )

            await self.activity_service.log_activity(
                user_id="system",
                user_role="system",
                action="Lead Auto Created",
                entity="Lead",
                entity_id=lead_id,
                details={
                    "source": "Website Contact Form",
                },
            )

            admins = await self.user_repo.get_active_by_role(
                "super_admin"
            )

            for admin in admins:
                await self.notification_service.safe_create_notification(
                    user_id=str(admin["_id"]),
                    notif_type="lead",
                    title="New Website Lead",
                    message=(
                        f"{name} ({email}) "
                        "submitted a new website enquiry."
                    ),
                    entity_id=lead_id,
                    entity_type="Lead",
                    event_key=f"lead_created:{lead_id}:{admin['_id']}",
                )

        try:
            send_contact_alert(
                name,
                email,
                message,
            )
        except Exception as exc:
            logger_contact.error(
                f"Failed to send contact alert: {exc}"
            )

        logger_contact.info(
            f"New contact form submitted by {email}"
        )

        return created_contact
