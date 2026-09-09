from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from app.config import UPLOAD_STORAGE_ROOT
from app.db.schemas import QuotationStatus
from app.exceptions import (
    DuplicateException,
    ResourceNotFoundException,
    ValidationException,
    PermissionException,
)
from app.logger import logger_quotation
from app.repositories.lead_repo import LeadRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.quotation_repo import QuotationRepository
from app.repositories.requirement_repo import RequirementRepository
from app.repositories.user_repo import UserRepository
from app.services.activitylog_service import ActivityLogService
from app.services.discussion_service import DiscussionService
from app.services.lead_service import LeadService
from app.services.notification_service import NotificationService
from app.services.project_service import ProjectService
from app.services.timeline_service import TimelineService
from app.services.email import send_quotation_email
from app.services.quotation_generator import generate_quotation_pdf


def _deliver_quotation_email(quotation: dict, client: dict) -> None:
    """Generate and attach the detailed quotation PDF before sending email."""

    pdf_path: str | None = None
    try:
        pdf_path = generate_quotation_pdf(
            {
                "quotation_number": quotation.get("quotationNumber"),
                "issued_on": datetime.now(timezone.utc).strftime("%d %b %Y"),
                "validity": quotation.get("validity"),
                "client_name": client.get("name", "Client"),
                "client_email": client.get("email"),
                "project_title": quotation.get("projectTitle") or f"{client.get('name', 'Client')}'s project",
                "timeline": quotation.get("timeline"),
                "services": quotation.get("services", []),
                "items": quotation.get("items", []),
                "total_amount": quotation.get("totalAmount", 0),
                "terms": quotation.get("terms"),
                "notes": quotation.get("notes"),
            },
            Path(UPLOAD_STORAGE_ROOT) / "quotations",
        )
        send_quotation_email(
            client.get("name", "there"),
            client["email"],
            quotation["quotationNumber"],
            quotation["totalAmount"],
            quotation["timeline"],
            quotation["validity"],
            items=quotation.get("items", []),
            terms=quotation.get("terms"),
            notes=quotation.get("notes"),
            file_path=pdf_path,
            project_name=quotation.get("projectTitle") or f"{client.get('name', 'Client')}'s project",
        )
    finally:
        if pdf_path:
            try:
                Path(pdf_path).unlink(missing_ok=True)
            except OSError:
                logger_quotation.exception("Failed to clean up quotation PDF.")


class QuotationService:
    """Service for quotation management."""

    def __init__(self):
        self.lead_repo = LeadRepository()
        self.project_repo = ProjectRepository()
        self.quotation_repo = QuotationRepository()
        self.user_repo = UserRepository()
        self.req_repo = RequirementRepository()

        self.notification_service = NotificationService()
        self.project_service = ProjectService()
        self.lead_service = LeadService()
        self.timeline_service = TimelineService()
        self.discussion_service = DiscussionService()
        self.activity_service = ActivityLogService()

    @staticmethod
    def _serialize_quotation(quotation: dict) -> dict:
        """Normalize quotation identifiers for API responses, including legacy records."""

        quotation["id"] = str(quotation["_id"])
        for field in ("clientId", "leadId", "projectId", "lastRevisedBy"):
            if quotation.get(field) is not None:
                quotation[field] = str(quotation[field])
        return quotation

    async def _serialize_quotation_for_view(self, quotation: dict) -> dict:
        """Normalize a quotation and include the linked client's display name."""

        self._serialize_quotation(quotation)
        if not quotation.get("projectId") and quotation.get("id"):
            linked_project = await self.project_repo.find_by_quotation(
                str(quotation["id"])
            )
            if linked_project:
                quotation["projectId"] = str(
                    linked_project.get("_id") or linked_project.get("id")
                )
        client = await self.user_repo.find_by_id(str(quotation.get("clientId")))
        quotation["clientName"] = client.get("name") if client else None
        return quotation

    async def _reconcile_accepted_lead(self, quotation: dict) -> None:
        """Bring a valid quotation lead to Won during acceptance recovery."""

        lead_id = quotation.get("leadId")
        if not lead_id:
            return

        lead = await self.lead_repo.find_by_id(str(lead_id))
        if not lead:
            return

        quotation_client = quotation.get("clientId")
        lead_client = lead.get("clientId")
        if quotation_client and lead_client and str(quotation_client) != str(lead_client):
            logger_quotation.warning(
                "Skipping lead reconciliation for quotation %s: client mismatch.",
                quotation.get("_id"),
            )
            return

        if lead.get("stage") in {"Won", "Lost"}:
            return

        # This is a system reconciliation, not a client-authorized lead edit.
        await self.lead_service.mark_lead_as_won(str(lead_id), "system")

    @staticmethod
    def _validate_status_transition(
        current_status: str,
        next_status: str,
    ) -> None:
        """Validate the supported quotation lifecycle."""

        allowed = {
            QuotationStatus.DRAFT.value: {
                QuotationStatus.SENT.value,
            },
            QuotationStatus.SENT.value: {
                QuotationStatus.ACCEPTED.value,
                QuotationStatus.REJECTED.value,
                QuotationStatus.REVISION_REQUESTED.value,
            },
            QuotationStatus.REVISION_REQUESTED.value: {
                QuotationStatus.DRAFT.value,
            },
            QuotationStatus.ACCEPTED.value: set(),
            QuotationStatus.REJECTED.value: set(),
            QuotationStatus.EXPIRED.value: set(),
            QuotationStatus.VIEWED.value: set(),
        }

        if next_status not in allowed.get(current_status, set()):
            raise ValidationException(
                f"Cannot change quotation status from "
                f"'{current_status}' to '{next_status}'."
            )

    @staticmethod
    def _calculate_items(items: list[dict]) -> tuple[list[dict], float]:
        """Calculate item totals from quantity and unit price."""

        calculated_items = []
        total_amount = 0.0

        for item in items:
            quantity = float(item.get("quantity", 0))
            unit_price = float(item.get("unitPrice", 0))

            if not isfinite(quantity) or quantity <= 0:
                raise ValidationException(
                    "Quotation item quantity must be greater than zero."
                )
            if not isfinite(unit_price) or unit_price < 0:
                raise ValidationException(
                    "Quotation item unit price cannot be negative."
                )

            item_copy = dict(item)
            item_total = round(quantity * unit_price, 2)
            item_copy["quantity"] = quantity
            item_copy["unitPrice"] = unit_price
            item_copy["total"] = item_total
            calculated_items.append(item_copy)
            total_amount += item_total

        return calculated_items, round(total_amount, 2)

    async def _require_quotation_access(
        self,
        quotation: dict,
        current_user: dict,
    ) -> None:
        """Enforce quotation ownership and CRM assignment rules."""

        role = current_user.get("role")
        if role == "super_admin":
            return

        if role == "client":
            if str(quotation.get("clientId")) == current_user.get("id"):
                return
            raise PermissionException("Access denied")

        if role == "sub_admin":
            raise PermissionException("Sub Admins do not have access to quotations.")

        raise PermissionException("Access denied")

    async def _get_sub_admin_scope(
        self,
        user_id: str,
    ) -> tuple[list[str], list[str]]:
        """Return lead/project IDs managed by a Sub Admin."""

        leads = await self.lead_repo.find_many(
            {"$or": [{"assignedTo": user_id}, {"assignedToIds": user_id}]},
            limit=1_000_000,
        )
        lead_ids = [str(lead["_id"]) for lead in leads]

        project_query = {
            "$or": [
                {"assignedSubAdmin": user_id},
                {"leadId": {"$in": lead_ids}},
            ]
        }
        projects = await self.project_repo.find_many(
            project_query,
            limit=1_000_000,
        )
        project_ids = [str(project["_id"]) for project in projects]

        return lead_ids, project_ids

    async def create_quotation(
        self,
        current_user: dict,
        client_id: str,
        services: list,
        items: list,
        timeline: str,
        validity: int,
        terms: str,
        lead_id: str | None = None,
        project_id: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Create a new quotation."""

        client = await self.user_repo.find_by_id(
            client_id
        )

        if not client:
            raise ResourceNotFoundException(
                "Client"
            )
        if client.get("role") != "client":
            raise ValidationException(
                "Quotation client must have the client role."
            )

        lead = None
        project = None

        if lead_id:
            lead = await self.lead_repo.find_by_id(
                lead_id
            )

            if not lead:
                raise ResourceNotFoundException(
                    "Lead"
                )

        if project_id:
            project = await self.project_repo.find_by_id(
                project_id
            )

            if not project:
                raise ResourceNotFoundException(
                    "Project"
                )

        if lead_id and project_id:
            if str(project.get("leadId")) != lead_id:
                raise ValidationException(
                    "Lead and project do not belong to the same business flow."
                )

        related_lead = lead
        if related_lead is None and project and project.get("leadId"):
            related_lead = await self.lead_repo.find_by_id(
                project["leadId"]
            )

        if related_lead:
            if not related_lead.get("clientId"):
                raise ValidationException(
                    "Lead must be linked to the client before creating a quotation."
                )
            if str(related_lead["clientId"]) != str(client_id):
                raise ValidationException(
                    "Quotation client does not match the lead's client."
                )

        if project and str(project.get("userId")) != client_id:
            raise ValidationException(
                "Quotation client does not match the project owner."
            )

        await self._require_quotation_access(
            {
                "clientId": client_id,
                "leadId": lead_id or (
                    project.get("leadId") if project else None
                ),
                "projectId": project_id,
            },
            current_user,
        )

        requirement = None

        if lead_id:
            requirement = await self.req_repo.find_by_lead(
                lead_id
            )
        if not requirement and project_id:
            requirement = await self.req_repo.find_by_project(
                project_id
            )

            if not requirement and project.get("leadId"):
                requirement = await self.req_repo.find_by_lead(
                    project["leadId"]
                )

        if requirement:
            if (
                requirement.get("leadId")
                and lead_id
                and str(requirement["leadId"]) != lead_id
            ) or (
                requirement.get("projectId")
                and project_id
                and str(requirement["projectId"]) != project_id
            ):
                raise ValidationException(
                    "Requirement does not belong to the quotation relationship."
                )

        project_title = (
            str((requirement or {}).get("businessName") or "").strip()
            or str((related_lead or {}).get("companyName") or "").strip()
            or f"{str(client.get('name') or 'Client').strip()}'s project"
        )

        # Requirements are optional context for a quotation. If one exists,
        # its relationship is validated above, but it must not block quotation
        # creation when the client has not submitted one.

        if lead_id:
            existing = await self.quotation_repo.find_active_by_lead(
                lead_id
            )

            if existing:
                raise DuplicateException(
                    "Quotation already exists for this lead."
                )

        elif project_id:
            existing = await self.quotation_repo.find_active_by_project(
                project_id
            )

            if existing:
                raise DuplicateException(
                    "Quotation already exists for this project."
                )

        calculated_items, total_amount = self._calculate_items(items)

        quotation_data = {
            "clientId": client_id,
            "leadId": lead_id,
            "projectId": project_id,
            "quotationNumber": (
                await self.quotation_repo.get_next_quotation_number()
            ),
            "services": services,
            "items": calculated_items,
            "timeline": timeline,
            "validity": validity,
            "terms": terms,
            "notes": notes,
            "projectTitle": project_title,
            "status": QuotationStatus.DRAFT,
            "totalAmount": total_amount,
            "revisionCount": 0,
            "lastRevisedBy": None,
            "lastRevisedAt": None,
        }

        quotation_id = await self.quotation_repo.create(
            quotation_data
        )

        created_quotation = (
            await self.quotation_repo.find_by_id(
                quotation_id
            )
        )

        self._serialize_quotation(created_quotation)

        try:
            _deliver_quotation_email(created_quotation, client)
        except Exception as exc:
            logger_quotation.error(f"Failed to send quotation email: {exc}")

        await self.notification_service.notify_admins(
            notif_type="quotation",
            title="New quotation draft",
            message=f"Quotation {created_quotation['quotationNumber']} was created and needs review.",
            entity_id=quotation_id,
            entity_type="Quotation",
            event_key=f"quotation_created:{quotation_id}",
            exclude_user_id=current_user["id"],
        )

        logger_quotation.info(
            f"Quotation created: {quotation_id}"
        )

        return created_quotation

    async def update_quotation_status(
        self,
        quotation_id: str,
        status: str,
        user_id: str | None = None,
        mark_lead: bool = True,
        user_role: str | None = None,
    ) -> dict:
        """Update the status of a quotation."""

        valid_statuses = [
            quotation_status.value
            for quotation_status in QuotationStatus
        ]

        if status not in valid_statuses:
            raise ValidationException(
                f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            )

        quotation = await self.quotation_repo.find_by_id(
            quotation_id
        )

        if not quotation:
            raise ResourceNotFoundException(
                "Quotation"
            )

        self._validate_status_transition(
            quotation.get("status"),
            status,
        )

        updated_quotation = await self.quotation_repo.update_status_if_current(
            quotation_id,
            quotation.get("status"),
            status,
        )

        if not updated_quotation:
            raise ValidationException(
                "Quotation status changed before this request completed."
            )

        if mark_lead and quotation.get("leadId"):
            if status == QuotationStatus.ACCEPTED.value:
                await self.lead_service.mark_lead_as_won(
                    quotation["leadId"],
                    {"id": user_id, "role": user_role}
                    if user_id and user_role
                    else user_id or "system",
                )

            elif status == QuotationStatus.REJECTED.value:
                await self.lead_service.mark_lead_as_lost(
                    quotation["leadId"],
                    {"id": user_id, "role": user_role}
                    if user_id and user_role
                    else user_id or "system",
                )

        self._serialize_quotation(updated_quotation)

        logger_quotation.info(
            f"Quotation {quotation_id} status changed to {status}"
        )

        return updated_quotation

    async def update_quotation(
        self,
        quotation_id: str,
        current_user: dict,
        **updates,
    ) -> dict:
        """Revise an existing quotation."""

        if current_user.get("role") not in {"super_admin", "sub_admin"}:
            raise PermissionException("Only administrators can revise quotations.")

        quotation = await self.quotation_repo.find_by_id(
            quotation_id
        )

        if not quotation:
            raise ResourceNotFoundException(
                "Quotation"
            )

        await self._require_quotation_access(
            quotation,
            current_user,
        )

        if quotation.get("status") not in {
            QuotationStatus.DRAFT.value,
            QuotationStatus.REVISION_REQUESTED.value,
        }:
            raise ValidationException(
                "Only Draft or Revision Requested quotations can be edited."
            )

        if (
            quotation.get("status")
            == QuotationStatus.ACCEPTED.value
        ):
            raise ValidationException(
                "Accepted quotation cannot be revised."
            )

        if (
            quotation.get("status")
            == QuotationStatus.REJECTED.value
        ):
            raise ValidationException(
                "Rejected quotation cannot be revised."
            )

        if "items" in updates:
            calculated_items, total_amount = self._calculate_items(
                updates["items"]
            )
            updates["items"] = calculated_items
            updates["totalAmount"] = total_amount

        updates["status"] = QuotationStatus.DRAFT.value
        updates["revisionCount"] = (
            quotation.get("revisionCount", 0) + 1
        )
        updates["lastRevisedBy"] = current_user["id"]
        updates["lastRevisedAt"] = datetime.now(
            timezone.utc
        )

        updated = await self.quotation_repo.update(
            quotation_id,
            updates,
        )

        if not updated:
            raise ValidationException(
                "Failed to update quotation."
            )

        updated_quotation = (
            await self.quotation_repo.find_by_id(
                quotation_id
            )
        )

        self._serialize_quotation(updated_quotation)

        user = await self.user_repo.find_by_id(
            current_user["id"]
        )

        user_role = (
            user.get("role")
            if user
            else "System"
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=user_role,
            action="Quotation Revised",
            entity="Quotation",
            entity_id=quotation_id,
            details={
                "revisionCount": updated_quotation.get(
                    "revisionCount",
                    0,
                )
            },
        )

        logger_quotation.info(
            f"Quotation updated: {quotation_id}"
        )

        return updated_quotation
    
    async def send_quotation(
        self,
        quotation_id: str,
        current_user: dict,
    ) -> dict:
        """Send a quotation to the client."""

        if current_user.get("role") not in {"super_admin", "sub_admin"}:
            raise PermissionException("Only administrators can send quotations.")

        quotation = await self.quotation_repo.find_by_id(
            quotation_id
        )

        if not quotation:
            raise ResourceNotFoundException(
                "Quotation"
            )

        await self._require_quotation_access(
            quotation,
            current_user,
        )

        if (
            quotation.get("status")
            == QuotationStatus.SENT.value
        ):
            raise ValidationException(
                "Quotation has already been sent."
            )

        client = await self.user_repo.find_by_id(str(quotation["clientId"]))
        if not client or not client.get("email"):
            raise ValidationException("Quotation client does not have a valid email address.")

        if not quotation.get("projectTitle"):
            requirement = await self.req_repo.find_by_lead(str(quotation["leadId"])) if quotation.get("leadId") else None
            lead = await self.lead_repo.find_by_id(str(quotation["leadId"])) if quotation.get("leadId") else None
            quotation["projectTitle"] = (
                str((requirement or {}).get("businessName") or "").strip()
                or str((lead or {}).get("companyName") or "").strip()
                or f"{str(client.get('name') or 'Client').strip()}'s project"
            )

        # Deliver the email before marking the quotation as sent. If Resend rejects
        # it, the API returns an error and the UI must not show a false success.
        _deliver_quotation_email(quotation, client)

        updated_quotation = (
            await self.update_quotation_status(
                quotation_id=quotation_id,
                status=QuotationStatus.SENT.value,
                user_id=current_user["id"],
                user_role=current_user["role"],
            )
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Quotation Sent",
            entity="Quotation",
            entity_id=quotation_id,
            details={
                "quotationNumber": quotation[
                    "quotationNumber"
                ]
            },
        )

        await self.notification_service.safe_create_notification(
            user_id=str(
                quotation["clientId"]
            ),
            notif_type="quotation",
            title="Quotation Sent",
            message=(
                f"Quotation "
                f"{quotation['quotationNumber']} "
                f"has been sent."
            ),
            entity_id=quotation_id,
            entity_type="Quotation",
            event_key=f"quotation_sent:{quotation_id}:{quotation['clientId']}",
        )

        logger_quotation.info(
            f"Quotation {quotation['quotationNumber']} sent successfully."
        )

        return updated_quotation

    async def _recover_accepted_quotation(
        self,
        quotation: dict,
        current_user: dict,
    ) -> dict:
        """Return the single project for an accepted quotation and recover setup."""

        existing_project = await self.project_repo.find_by_quotation(
            str(quotation["_id"] if quotation.get("_id") else quotation["id"])
        )
        if not existing_project:
            raise ValidationException(
                "Accepted quotation has no project. Contact an administrator."
            )

        self.project_service._serialize_project(existing_project)
        self._serialize_quotation(quotation)
        await self._reconcile_accepted_lead(quotation)
        await self.timeline_service.initialize_project_timeline(
            project_id=existing_project["id"],
            created_by=current_user["id"],
        )
        await self.discussion_service.initialize_project_discussion(
            project_id=existing_project["id"],
            created_by=current_user["id"],
        )
        return {
            "quotation": quotation,
            "project": existing_project,
        }

    async def accept_quotation(
        self,
        quotation_id: str,
        current_user: dict,
    ) -> dict:
        """Accept a quotation and start the project workflow."""

        quotation = await self.quotation_repo.find_by_id(
            quotation_id
        )

        if not quotation:
            raise ResourceNotFoundException(
                "Quotation"
            )

        if current_user.get("role") != "client" or str(
            quotation.get("clientId")
        ) != current_user.get("id"):
            raise PermissionException("Only the quotation client can accept it.")

        if quotation.get("status") == QuotationStatus.ACCEPTED.value:
            return await self._recover_accepted_quotation(
                quotation,
                current_user,
            )

        requirement = None
        if quotation.get("leadId"):
            requirement = await self.req_repo.find_by_lead(
                quotation["leadId"]
            )

        if not requirement and quotation.get("projectId"):
            requirement = await self.req_repo.find_by_project(
                quotation["projectId"]
            )
            if not requirement:
                project = await self.project_repo.find_by_id(
                    quotation["projectId"]
                )
                if project and project.get("leadId"):
                    requirement = await self.req_repo.find_by_lead(
                        project["leadId"]
                    )

        # A quotation can be accepted whether or not the client submitted an
        # optional requirement.

        try:
            quotation = await self.update_quotation_status(
                quotation_id=quotation_id,
                status=QuotationStatus.ACCEPTED.value,
                user_id=current_user["id"],
                user_role=current_user["role"],
                mark_lead=False,
            )
        except ValidationException:
            # Another acceptance may have won the conditional status update.
            # Recover its project instead of returning a misleading conflict.
            latest = await self.quotation_repo.find_by_id(quotation_id)
            if latest and latest.get("status") == QuotationStatus.ACCEPTED.value:
                existing_project = await self.project_repo.find_by_quotation(
                    quotation_id
                )
                if existing_project:
                    return await self._recover_accepted_quotation(
                        latest,
                        current_user,
                    )
            raise

        try:
            project = await self.project_service.create_project_from_quotation(
                quotation,
                current_user=current_user,
            )
        except Exception:
            existing_project = await self.project_repo.find_by_quotation(
                quotation_id
            )
            if not existing_project:
                await self.quotation_repo.update(
                    quotation_id,
                    {"status": QuotationStatus.SENT.value},
                )
            raise

        project_id = str(project["id"])
        await self.quotation_repo.update(
            quotation_id,
            {"projectId": project_id},
        )
        quotation["projectId"] = project_id

        await self._reconcile_accepted_lead(quotation)

        await self.timeline_service.initialize_project_timeline(
            project_id=project["id"],
            created_by=current_user["id"],
        )

        await self.discussion_service.initialize_project_discussion(
            project_id=project["id"],
            created_by=current_user["id"],
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Quotation Accepted",
            entity="Quotation",
            entity_id=quotation_id,
            details={
                "projectId": project["id"]
            },
        )

        admins = await self.user_repo.get_active_by_role(
            "super_admin"
        )

        for admin in admins:
            await self.notification_service.safe_create_notification(
                user_id=str(
                    admin["_id"]
                ),
                notif_type="quotation",
                title="Quotation Accepted",
                message=(
                    f"Quotation "
                    f"{quotation['quotationNumber']} "
                    f"has been accepted."
                ),
                entity_id=quotation_id,
                entity_type="Quotation",
                event_key=f"quotation_accepted:{quotation_id}:{admin['_id']}",
            )

        logger_quotation.info(
            f"Quotation accepted: {quotation_id}"
        )

        return {
            "quotation": quotation,
            "project": project,
        }

    async def get_quotations(
        self,
        current_user: dict,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[dict]:
        """Return quotations for the current user."""

        if current_user["role"] == "client":
            quotations = await self.quotation_repo.find_by_client(
                current_user["id"],
                skip,
                limit,
            )

        elif current_user["role"] == "super_admin":
            if status and status not in {
                quotation_status.value
                for quotation_status in QuotationStatus
            }:
                raise ValidationException("Invalid quotation status.")

            if status:
                quotations = await self.quotation_repo.find_by_status(
                    status,
                    skip,
                    limit,
                )
            else:
                quotations = await self.quotation_repo.get_all_sorted(
                    skip,
                    limit,
                )

        else:
            raise PermissionException(
                "Access denied"
            )

        for quotation in quotations:
            await self._serialize_quotation_for_view(quotation)

        logger_quotation.info(
            f"Fetched {len(quotations)} quotations"
        )

        return quotations

    async def get_quotation(
        self,
        quotation_id: str,
        current_user: dict,
    ) -> dict:
        """Return a quotation by ID."""

        quotation = await self.quotation_repo.find_by_id(
            quotation_id
        )

        if not quotation:
            raise ResourceNotFoundException(
                "Quotation"
            )

        await self._require_quotation_access(
            quotation,
            current_user,
        )

        await self._serialize_quotation_for_view(quotation)

        return quotation

    async def generate_quotation_pdf_file(
        self,
        quotation_id: str,
        current_user: dict,
    ) -> tuple[Path, str]:
        """Generate a downloadable quotation PDF for an authorized viewer."""

        quotation = await self.get_quotation(quotation_id, current_user)
        client = await self.user_repo.find_by_id(str(quotation["clientId"]))
        if not client:
            raise ResourceNotFoundException("Client")
        requirement = await self.req_repo.find_by_lead(str(quotation["leadId"])) if quotation.get("leadId") else None
        if not requirement and quotation.get("projectId"):
            requirement = await self.req_repo.find_by_project(str(quotation["projectId"]))
        lead = await self.lead_repo.find_by_id(str(quotation["leadId"])) if quotation.get("leadId") else None
        project_title = (
            str(quotation.get("projectTitle") or "").strip()
            or str((requirement or {}).get("businessName") or "").strip()
            or str((lead or {}).get("companyName") or "").strip()
            or f"{str(client.get('name') or 'Client').strip()}'s project"
        )
        created_on = quotation.get("createdAt", datetime.now(timezone.utc))
        issued_on = created_on.strftime("%d %b %Y") if hasattr(created_on, "strftime") else str(created_on)

        file_path = Path(generate_quotation_pdf(
            {
                "quotation_number": quotation.get("quotationNumber"),
                "issued_on": issued_on,
                "validity": quotation.get("validity"),
                "client_name": client.get("name", "Client"),
                "client_email": client.get("email"),
                "project_title": project_title,
                "timeline": quotation.get("timeline"),
                "services": quotation.get("services", []),
                "items": quotation.get("items", []),
                "total_amount": quotation.get("totalAmount", 0),
                "terms": quotation.get("terms"),
                "notes": quotation.get("notes"),
            },
            Path(UPLOAD_STORAGE_ROOT) / "quotations",
        ))
        return file_path, f"quotation_{quotation.get('quotationNumber', quotation_id)}.pdf"

    async def reject_quotation(
        self,
        quotation_id: str,
        current_user: dict,
    ) -> dict:
        """Reject a quotation."""

        await self.get_quotation(
            quotation_id,
            current_user,
        )

        if current_user.get("role") != "client":
            raise PermissionException("Only the quotation client can reject it.")

        updated = await self.update_quotation_status(
            quotation_id,
            QuotationStatus.REJECTED.value,
            current_user["id"],
            mark_lead=False,
            user_role=current_user["role"],
        )
        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Quotation Rejected",
            entity="Quotation",
            entity_id=quotation_id,
        )
        return updated

    async def request_revision(
        self,
        quotation_id: str,
        current_user: dict,
    ) -> dict:
        """Request a quotation revision."""

        await self.get_quotation(
            quotation_id,
            current_user,
        )

        if current_user.get("role") != "client":
            raise PermissionException("Only the quotation client can request a revision.")

        updated = await self.update_quotation_status(
            quotation_id,
            QuotationStatus.REVISION_REQUESTED.value,
            current_user["id"],
        )
        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Quotation Revision Requested",
            entity="Quotation",
            entity_id=quotation_id,
        )
        return updated

    async def delete_quotation(
        self,
        quotation_id: str,
        current_user: dict,
    ) -> dict:
        """Delete a quotation."""

        quotation = await self.quotation_repo.find_by_id(
            quotation_id
        )

        if not quotation:
            raise ResourceNotFoundException(
                "Quotation"
            )

        await self._require_quotation_access(
            quotation,
            current_user,
        )

        if quotation.get("status") == QuotationStatus.ACCEPTED.value:
            raise ValidationException(
                "Accepted quotation cannot be deleted."
            )

        deleted = await self.quotation_repo.delete(
            quotation_id
        )

        if not deleted:
            raise ValidationException(
                "Failed to delete quotation."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Quotation Deleted",
            entity="Quotation",
            entity_id=quotation_id,
        )

        logger_quotation.info(
            f"Quotation deleted: {quotation_id}"
        )

        return {
            "message": "Quotation deleted successfully."
        }
