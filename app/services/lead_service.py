from datetime import datetime, timezone

from app.exceptions import (
    AuthorizationException,
    DuplicateException,
    ResourceNotFoundException,
    ValidationException,
)
from app.logger import logger_lead
from app.repositories.lead_repo import LeadRepository
from app.repositories.user_repo import UserRepository
from app.services.activitylog_service import ActivityLogService
from app.services.email import send_existing_client_access_email
from app.services.auth_service import AuthService
from app.services.notification_service import NotificationService


class LeadService:
    """Service for CRM lead management."""

    def __init__(self):
        self.lead_repo = LeadRepository()
        self.user_repo = UserRepository()
        self.auth_service = AuthService()
        self.activity_service = ActivityLogService()
        self.notification_service = NotificationService()

    @staticmethod
    def _ensure_lead_access(
        lead: dict,
        current_user: dict,
    ) -> None:
        """Allow Super Admins all leads and Sub Admins assigned leads."""

        if current_user.get("role") == "super_admin":
            return

        assigned_ids = {
            str(value)
            for value in lead.get("assignedToIds", [])
            if value
        }
        if lead.get("assignedTo"):
            assigned_ids.add(str(lead["assignedTo"]))

        if (
            current_user.get("role") == "sub_admin"
            and str(current_user.get("id")) in assigned_ids
        ):
            return

        raise AuthorizationException(
            "Sub Admins can only access assigned leads."
        )

    @staticmethod
    def _validate_stage_transition(
        current_stage: str,
        next_stage: str,
    ) -> None:
        """Validate normal CRM stage transitions."""

        allowed_transitions = {
            "New": {"Contacted", "Qualified", "Lost"},
            "Contacted": {"Qualified", "Lost"},
            "Qualified": {"Proposal Sent", "Lost"},
            "Proposal Sent": {"Negotiation", "Won", "Lost"},
            "Negotiation": {"Won", "Lost"},
            "Won": set(),
            "Lost": set(),
        }

        if current_stage == next_stage:
            raise ValidationException(
                f"Lead is already in '{next_stage}' stage."
            )

        if next_stage not in allowed_transitions.get(
            current_stage,
            set(),
        ):
            raise ValidationException(
                f"Cannot change lead stage from '{current_stage}' "
                f"to '{next_stage}'."
            )

    async def create_lead(
        self,
        current_user: dict,
        company_name: str,
        contact_person: str,
        phone: str,
        email: str,
        business: str,
        lead_source: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Create a new lead."""

        email = email.strip().lower()

        if await self.lead_repo.find_by_email(
            email
        ):
            raise DuplicateException(
                "Email already exists as lead."
            )

        company_name = (
            company_name.strip()
            if company_name
            else None
        )
        contact_person = contact_person.strip()
        phone = phone.strip() if phone else None
        business = business.strip()
        lead_source = (
            lead_source.strip()
            if lead_source
            else None
        )
        notes = notes.strip() if notes else None

        lead_data = {
            "companyName": company_name,
            "contactPerson": contact_person,
            "phone": phone,
            "email": email,
            "business": business,
            "leadSource": lead_source or "Contact Form",
            "notes": notes,
            "stage": "New",
            "history": [],
        }

        if current_user.get("role") == "sub_admin":
            lead_data["assignedTo"] = current_user["id"]
            lead_data["assignedToIds"] = [current_user["id"]]

            lead_data["history"].append(
                {
                    "action": "Lead Assigned",
                    "field": "assignedTo",
                    "oldValue": None,
                    "newValue": current_user["id"],
                    "changedBy": current_user["id"],
                    "message": "Lead automatically assigned to its creator.",
                    "timestamp": datetime.now(timezone.utc),
                }
            )

        lead_id = await self.lead_repo.create(
            lead_data
        )

        created_lead = await self.lead_repo.find_by_id(
            lead_id
        )

        created_lead["id"] = str(
            created_lead["_id"]
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Lead Created",
            entity="Lead",
            entity_id=lead_id,
        )
        await self.notification_service.notify_admins(
            notif_type="lead",
            title="New lead",
            message=f"{contact_person} submitted a new lead{f' for {company_name}' if company_name else ''}.",
            entity_id=lead_id,
            entity_type="Lead",
            event_key=f"lead_created:{lead_id}",
            exclude_user_id=current_user["id"],
        )

        logger_lead.info(
            f"Lead created: {lead_id}"
        )

        return created_lead

    async def convert_lead_to_client(
        self,
        lead_id: str,
        current_user: dict,
        password: str | None = None,
    ) -> dict:
        """Create or link a client account for a lead."""

        lead = await self.lead_repo.find_by_id(
            lead_id
        )

        if not lead:
            raise ResourceNotFoundException(
                "Lead"
            )

        self._ensure_lead_access(lead, current_user)

        if lead.get("stage") == "Lost":
            raise ValidationException(
                "A lost lead cannot be converted to a client."
            )

        if lead.get("clientId"):
            account_status = "already_linked"
            email_status = "not_attempted"
            email_message = "The lead is already linked to a client account."
            existing_client = await self.user_repo.find_by_id(str(lead["clientId"]))
            if existing_client and existing_client.get("email"):
                try:
                    send_existing_client_access_email(existing_client.get("name", "there"), existing_client["email"])
                    email_status = "sent"
                    email_message = "Access email sent to the existing client account."
                except Exception as exc:
                    email_status = "failed"
                    email_message = "The client is linked, but the access email could not be sent."
                    logger_lead.error(f"Failed to resend existing client access email: {exc}")
            existing = await self.lead_repo.find_by_id(lead_id)
            existing["id"] = str(existing["_id"])
            existing.update({"accountStatus": account_status, "emailStatus": email_status, "emailMessage": email_message})
            return existing

        email = lead.get("email")
        if not email:
            raise ValidationException(
                "Lead email is required before client conversion."
            )

        email = email.strip().lower()
        client = await self.user_repo.find_by_email(email)

        if client:
            account_status = "existing"
            if client.get("role") != "client":
                raise ValidationException(
                    "Lead email already belongs to a non-client user."
                )
            client_id = str(client["_id"])
            email_status = "sent"
            email_message = "Access email sent to the existing client account."
            try:
                send_existing_client_access_email(client.get("name", "there"), client["email"])
            except Exception as exc:
                email_status = "failed"
                email_message = "The existing client was linked, but the access email could not be sent."
                logger_lead.error(f"Failed to send existing client access email: {exc}")
        else:
            if not password:
                raise ValidationException(
                    "A password is required to create the client account."
                )

            client_data = await self.auth_service.register_client(
                name=(
                    lead.get("contactPerson")
                    or lead.get("companyName")
                    or email
                ),
                email=email,
                phone=lead.get("phone"),
                password=password,
                current_user=current_user,
            )
            client_id = client_data["id"]
            account_status = "created"
            email_status = "sent" if client_data.get("emailSent", False) else "failed"
            email_message = "Welcome email sent to the new client." if email_status == "sent" else "Client account created, but the welcome email could not be sent."

        updated = await self.lead_repo.update_with_history(
            lead_id,
            {
                "clientId": client_id,
            },
            [
                {
                    "action": "Lead Converted to Client",
                    "field": "clientId",
                    "oldValue": None,
                    "newValue": client_id,
                    "changedBy": current_user["id"],
                    "message": "Lead linked to a client account.",
                }
            ],
        )

        if not updated:
            raise ValidationException(
                "Failed to convert lead to client."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Lead Converted to Client",
            entity="Lead",
            entity_id=lead_id,
            details={
                "clientId": client_id,
            },
        )

        converted = await self.lead_repo.find_by_id(lead_id)
        converted["id"] = str(converted["_id"])
        converted.update({"accountStatus": account_status, "emailStatus": email_status, "emailMessage": email_message})
        return converted

    async def update_lead(
        self,
        lead_id: str,
        current_user: dict,
        updated_by: str,
        **updates,
    ) -> dict:
        """Update an existing lead."""

        lead = await self.lead_repo.find_by_id(
            lead_id
        )

        if not lead:
            raise ResourceNotFoundException(
                "Lead"
            )

        self._ensure_lead_access(lead, current_user)

        if "email" in updates:
            updates["email"] = (
                updates["email"]
                .strip()
                .lower()
            )

            existing_lead = await self.lead_repo.find_by_email(
                updates["email"]
            )

            if (
                existing_lead
                and str(existing_lead["_id"]) != lead_id
            ):
                raise DuplicateException(
                    "Email already exists as lead."
                )

        if "stage" in updates:
            self._validate_stage_transition(
                lead.get("stage", "New"),
                updates["stage"],
            )

        history_entries = []
        for field, new_value in updates.items():
            old_value = lead.get(field)

            if old_value != new_value:
                history_entries.append(
                    {
                        "action": "Lead Updated",
                        "field": field,
                        "oldValue": (
                            str(old_value)
                            if old_value is not None
                            else None
                        ),
                        "newValue": (
                            str(new_value)
                            if new_value is not None
                            else None
                        ),
                        "changedBy": current_user["id"],
                    }
                )

        updated = await self.lead_repo.update_with_history(
            lead_id,
            updates,
            history_entries,
        )

        if not updated:
            raise ValidationException(
                "Failed to update lead."
            )

        updated_lead = await self.lead_repo.find_by_id(
            lead_id
        )

        updated_lead["id"] = str(
            updated_lead["_id"]
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Lead Updated",
            entity="Lead",
            entity_id=lead_id,
            details={
                "updates": updates,
            },
        )

        logger_lead.info(
            f"Lead updated: {lead_id}"
        )

        return updated_lead

    async def assign_lead(
        self,
        lead_id: str,
        sub_admin_id: str,
        current_user: dict,
    ) -> dict:
        """Assign a lead to a sub-admin."""

        actor = await self.user_repo.find_by_id(
            str(current_user.get("id")) if current_user else ""
        )
        if (
            not actor
            or not actor.get("isActive", True)
            or actor.get("role") != "super_admin"
        ):
            raise AuthorizationException(
                "Only an active Super Admin can assign leads."
            )

        lead = await self.lead_repo.find_by_id(
            lead_id
        )

        if not lead:
            raise ResourceNotFoundException(
                "Lead"
            )

        user = await self.user_repo.find_by_id(
            sub_admin_id
        )

        if not user:
            raise ResourceNotFoundException(
                "User"
            )

        if not user.get("isActive", True):
            raise ValidationException(
                "Lead cannot be assigned to an inactive Sub Admin."
            )

        if user["role"] != "sub_admin":
            raise ValidationException(
                "Lead can only be assigned to a Sub Admin."
            )

        if lead.get("assignedTo") == sub_admin_id:
            assigned_ids = [str(value) for value in lead.get("assignedToIds", []) if value]
        else:
            assigned_ids = [str(value) for value in lead.get("assignedToIds", []) if value]

        if sub_admin_id in assigned_ids:
            raise ValidationException("Lead is already assigned to this Sub Admin.")

        assigned_ids.append(sub_admin_id)
        primary_assignee = lead.get("assignedTo") or sub_admin_id

        updated = await self.lead_repo.update_with_history(
            lead_id,
            {
                "assignedTo": primary_assignee,
                "assignedToIds": assigned_ids,
            },
            [
                {
                    "action": "Lead Assigned",
                    "field": "assignedTo",
                    "oldValue": lead.get("assignedTo"),
                    "newValue": sub_admin_id,
                    "changedBy": current_user["id"],
                    "message": "Lead assigned to a Sub Admin.",
                }
            ],
        )

        if not updated:
            raise ValidationException(
                "Failed to assign lead."
            )

        updated_lead = await self.lead_repo.find_by_id(
            lead_id
        )

        updated_lead["id"] = str(
            updated_lead["_id"]
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Lead Assigned",
            entity="Lead",
            entity_id=lead_id,
            details={
                "assignedTo": sub_admin_id,
            },
        )

        try:
            await self.notification_service.safe_create_notification(
                user_id=sub_admin_id,
                notif_type="lead_assignment",
                title="Lead Assigned",
                message=(
                    f"Lead '{lead.get('companyName') or lead.get('contactPerson')}' "
                    f"assigned to {user.get('name')}."
                ),
                entity_id=lead_id,
                entity_type="Lead",
                event_key=f"lead_assigned:{lead_id}:{sub_admin_id}",
            )
        except Exception as exc:
            logger_lead.warning(
                f"Failed to notify Sub Admin {sub_admin_id}: {exc}"
            )

        logger_lead.info(
            f"Lead {lead_id} assigned to {sub_admin_id}"
        )

        return updated_lead

    async def mark_lead_as_won(
        self,
        lead_id: str,
        current_user: dict | str,
    ) -> dict:
        """Mark a lead as won."""

        lead = await self.lead_repo.find_by_id(
            lead_id
        )

        if not lead:
            raise ResourceNotFoundException(
                "Lead"
            )

        if isinstance(current_user, dict):
            self._ensure_lead_access(lead, current_user)

        if lead.get("stage") in {"Won", "Lost"}:
            raise ValidationException(
                f"Cannot mark a {lead.get('stage')} lead as won."
            )

        actor_id = current_user["id"] if isinstance(current_user, dict) else current_user
        actor_role = current_user["role"] if isinstance(current_user, dict) else "system"

        updated = await self.lead_repo.update_with_history(
            lead_id,
            {
                "stage": "Won",
            },
            [
                {
                    "action": "Lead Marked Won",
                    "field": "stage",
                    "oldValue": lead.get("stage"),
                    "newValue": "Won",
                    "changedBy": actor_id,
                }
            ],
            expected_stage=lead.get("stage"),
        )

        if not updated:
            raise ValidationException(
                "Failed to mark lead as won."
            )

        updated_lead = await self.lead_repo.find_by_id(
            lead_id
        )

        updated_lead["id"] = str(
            updated_lead["_id"]
        )

        await self.activity_service.log_activity(
            user_id=actor_id,
            user_role=actor_role,
            action="Lead Marked Won",
            entity="Lead",
            entity_id=lead_id,
        )

        logger_lead.info(
            f"Lead marked as won: {lead_id}"
        )

        return updated_lead

    async def mark_lead_as_lost(
        self,
        lead_id: str,
        current_user: dict | str,
    ) -> dict:
        """Mark a lead as lost."""

        lead = await self.lead_repo.find_by_id(
            lead_id
        )

        if not lead:
            raise ResourceNotFoundException(
                "Lead"
            )

        if isinstance(current_user, dict):
            self._ensure_lead_access(lead, current_user)

        if lead.get("stage") in {"Won", "Lost"}:
            raise ValidationException(
                f"Cannot mark a {lead.get('stage')} lead as lost."
            )

        actor_id = current_user["id"] if isinstance(current_user, dict) else current_user
        actor_role = current_user["role"] if isinstance(current_user, dict) else "system"

        updated = await self.lead_repo.update_with_history(
            lead_id,
            {
                "stage": "Lost",
            },
            [
                {
                    "action": "Lead Marked Lost",
                    "field": "stage",
                    "oldValue": lead.get("stage"),
                    "newValue": "Lost",
                    "changedBy": actor_id,
                }
            ],
            expected_stage=lead.get("stage"),
        )

        if not updated:
            raise ValidationException(
                "Failed to mark lead as lost."
            )

        updated_lead = await self.lead_repo.find_by_id(
            lead_id
        )

        updated_lead["id"] = str(
            updated_lead["_id"]
        )

        await self.activity_service.log_activity(
            user_id=actor_id,
            user_role=actor_role,
            action="Lead Marked Lost",
            entity="Lead",
            entity_id=lead_id,
        )

        logger_lead.info(
            f"Lead marked as lost: {lead_id}"
        )

        return updated_lead

    async def get_all_leads(
        self,
        skip: int = 0,
        limit: int = 100,
        stage: str | None = None,
        current_user: dict | None = None,
    ) -> list[dict]:
        """Return all leads."""

        if current_user and current_user.get("role") == "sub_admin":
            leads = await self.lead_repo.find_by_assigned_to(
                current_user["id"],
                skip,
                limit,
                stage,
            )
        elif stage:
            leads = await self.lead_repo.find_by_stage(
                stage,
                skip,
                limit,
            )
        else:
            leads = await self.lead_repo.get_all_sorted(
                skip,
                limit,
            )

        for lead in leads:
            lead["id"] = str(
                lead["_id"]
            )

        return leads

    async def get_lead(
        self,
        lead_id: str,
        current_user: dict | None = None,
    ) -> dict:
        """Return a lead."""

        lead = await self.lead_repo.find_by_id(
            lead_id
        )

        if not lead:
            raise ResourceNotFoundException(
                "Lead"
            )

        if current_user:
            self._ensure_lead_access(lead, current_user)

        lead["id"] = str(
            lead["_id"]
        )

        return lead

    async def get_lead_history(
        self,
        lead_id: str,
        current_user: dict | None = None,
    ) -> list[dict]:
        """Return the history of a lead."""

        lead = await self.lead_repo.find_by_id(
            lead_id
        )

        if not lead:
            raise ResourceNotFoundException(
                "Lead"
            )

        if current_user:
            self._ensure_lead_access(lead, current_user)

        return lead.get(
            "history",
            [],
        )
