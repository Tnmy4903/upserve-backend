from datetime import date, datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
import os

from app.config import UPLOAD_STORAGE_ROOT
from app.exceptions import PermissionException, ResourceNotFoundException, ValidationException
from app.logger import logger_invoice
from app.repositories.deliverables_repo import DeliverablesRepository
from app.repositories.invoice_repo import InvoiceRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.quotation_repo import QuotationRepository
from app.repositories.user_repo import UserRepository
from app.services.activitylog_service import ActivityLogService
from app.services.email import format_currency, format_date, format_status, send_invoice_email, send_payment_confirmation_email
from app.services.invoice_generator import generate_invoice_pdf
from app.services.notification_service import NotificationService
from app.services.project_service import ProjectService


class InvoiceService:
    """Service for invoice management."""

    STALE_SEND_AFTER = timedelta(minutes=15)

    def __init__(self):
        self.invoice_repo = InvoiceRepository()
        self.project_repo = ProjectRepository()
        self.quotation_repo = QuotationRepository()
        self.user_repo = UserRepository()
        self.deliverables_repo = DeliverablesRepository()
        self.activity_service = ActivityLogService()
        self.notification_service = NotificationService()
        self.project_service = ProjectService()

    @staticmethod
    def _invoice_storage_path() -> Path:
        return Path(UPLOAD_STORAGE_ROOT, "invoices").resolve()

    def _safe_invoice_path(self, stored_path: str) -> Path:
        """Resolve a legacy/current path only inside invoice storage."""

        root = self._invoice_storage_path()
        path = Path(stored_path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise ValidationException("Invalid invoice file location.")
        return path

    @staticmethod
    def _serialize_invoice(invoice: dict) -> dict:
        invoice["id"] = str(invoice["_id"])
        for field in ("projectId", "clientId", "quotationId", "leadId"):
            if invoice.get(field) is not None:
                invoice[field] = str(invoice[field])
        invoice["fileUrl"] = None
        invoice["downloadUrl"] = (
            f"/api/invoices/{invoice['id']}/download"
        )
        return invoice

    async def generate_invoice(
        self,
        project_id: str,
        current_user: dict,
        due_date: date | None = None,
        stage: str | None = None,
    ) -> dict:
        """Generate the next eligible project invoice stage."""

        await self._require_super_admin_actor(current_user)

        project = await self.project_repo.find_by_id(
            project_id
        )

        if not project:
            raise ResourceNotFoundException(
                "Project"
            )

        deliverables = await self.deliverables_repo.find_by_project(
            project_id
        )

        existing_invoices = await self.invoice_repo.find_all_by_project(project_id)
        legacy_full_invoice = stage is None
        if stage is None:
            # Preserve the old endpoint behavior for older callers: a request
            # without a stage creates the legacy full-value invoice only when
            # no invoice exists yet and the project is delivered.
            if existing_invoices:
                raise ValidationException("Invoice already exists for this project.")
            stage = "final"
            if project["status"] != "delivered":
                raise ValidationException("Invoice can only be generated after project is delivered.")
        if stage not in {"advance", "milestone", "final"}:
            raise ValidationException("Invalid invoice stage.")
        if stage == "final" and not deliverables:
            raise ValidationException("Deliverables must be created before generating the final invoice.")
        if any(item.get("stage") == stage for item in existing_invoices):
            raise ValidationException(f"A {stage} invoice already exists for this project.")

        user = await self.user_repo.find_by_id(
            str(project["userId"])
        )

        if not user or user.get("role") != "client":
            raise ResourceNotFoundException(
                "User"
            )

        quotation_id = project.get("quotationId")
        quotation = (
            await self.quotation_repo.find_by_id(
                str(quotation_id)
            )
            if quotation_id
            else None
        )
        if not quotation or quotation.get("status") != "Accepted":
            raise ValidationException(
                "Project must be linked to an accepted quotation."
            )
        if str(quotation.get("clientId")) != str(project["userId"]):
            raise ValidationException(
                "Quotation client does not match the project client."
            )
        if quotation.get("projectId") and str(quotation["projectId"]) != project_id:
            raise ValidationException(
                "Quotation does not belong to this project."
            )
        if quotation.get("leadId") and str(quotation["leadId"]) != str(project.get("leadId")):
            raise ValidationException(
                "Quotation lead does not match the project lead."
            )
        if not quotation.get("totalAmount") or not isfinite(float(quotation["totalAmount"])):
            raise ValidationException(
                "Accepted quotation total must be greater than zero."
            )

        amount = round(float(quotation["totalAmount"]), 2)
        if amount <= 0:
            raise ValidationException(
                "Accepted quotation total must be greater than zero."
            )

        schedule = self.invoice_repo._payment_schedule_from_project(project)
        advance_amount = round(amount * schedule["advance"] / 100, 2)
        milestone_amount = round(amount * schedule["milestone"] / 100, 2)
        final_amount = round(amount - advance_amount - milestone_amount, 2)
        stage_amounts = {"advance": advance_amount, "milestone": milestone_amount, "final": final_amount}
        stage_percentages = {"advance": schedule["advance"], "milestone": schedule["milestone"], "final": 100 if legacy_full_invoice else schedule["final"]}
        if legacy_full_invoice:
            stage_amounts["final"] = amount
        if stage == "milestone" and schedule["milestone"] > 0:
            advance = next((item for item in existing_invoices if item.get("stage") == "advance"), None)
            if schedule["advance"] > 0 and (not advance or not advance.get("isPaid")):
                raise ValidationException("The advance invoice must be paid before generating the milestone invoice.")
        if stage == "final":
            milestone = next((item for item in existing_invoices if item.get("stage") == "milestone"), None)
            if schedule["milestone"] > 0 and existing_invoices and any(item.get("stage") for item in existing_invoices) and (not milestone or not milestone.get("isPaid")):
                raise ValidationException("The milestone invoice must be paid before generating the final invoice.")
            if project["status"] != "delivered":
                raise ValidationException("The final invoice can only be generated after project delivery.")

        now = datetime.now(
            timezone.utc
        )

        invoice_due_date = due_date or project.get("deadline")
        if isinstance(invoice_due_date, str):
            try:
                invoice_due_date = date.fromisoformat(invoice_due_date[:10])
            except ValueError as exc:
                raise ValidationException("Invalid invoice due date.") from exc
        if isinstance(invoice_due_date, datetime):
            invoice_due_date = invoice_due_date.date()
        invoice_due_date_db = (
            datetime.combine(
                invoice_due_date,
                datetime.min.time(),
                tzinfo=timezone.utc,
            )
            if isinstance(invoice_due_date, date)
            else None
        )
        invoice_data = {
            "client_name": user["name"],
            "client_email": user["email"],
            "title": project["title"],
            "description": project["description"],
            "status": project["status"],
            "amount": stage_amounts[stage],
            "currency": "INR",
            "stage": stage,
            "percentage": stage_percentages[stage],
            "invoice_number": (
                await self.invoice_repo.get_next_invoice_number()
            ),
            "deadline": (
                invoice_due_date.strftime("%Y-%m-%d")
                if invoice_due_date
                else "N/A"
            ),
            "generated_on": now.strftime("%Y-%m-%d"),
        }

        invoice_path = self._invoice_storage_path()
        invoice_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        pdf_path = None
        try:
            pdf_path = generate_invoice_pdf(invoice_data, invoice_path)

            invoice_db_data = {
                "projectId": project["_id"],
                "clientId": project["userId"],
                "quotationId": str(quotation["_id"]),
                "leadId": quotation.get("leadId") or project.get("leadId"),
                "invoiceNumber": invoice_data["invoice_number"],
                "title": project["title"],
                "description": project.get("description"),
                "amount": invoice_data["amount"],
                "currency": invoice_data["currency"],
                "stage": stage,
                "percentage": stage_percentages[stage],
                "status": "generated",
                "isPaid": False,
                "fileUrl": str(pdf_path),
                "generatedOn": now,
                "dueDate": invoice_due_date_db,
                "paidOn": None,
            }

            invoice_id = await self.invoice_repo.create(invoice_db_data)
        except Exception:
            if pdf_path:
                try:
                    Path(pdf_path).unlink(missing_ok=True)
                except OSError:
                    logger_invoice.exception("Failed to clean up invoice PDF.")
            raise

        actor_id = current_user["id"]
        actor_role = current_user["role"]

        await self.activity_service.log_activity(
            user_id=actor_id,
            user_role=actor_role,
            action="Invoice Generated",
            entity="Invoice",
            entity_id=invoice_id,
            details={
                "projectId": project_id,
                "invoiceNumber": invoice_data["invoice_number"],
                "stage": stage,
                "amount": invoice_data["amount"],
            },
        )

        admins = await self.user_repo.get_active_by_role(
            "super_admin"
        )

        for admin in admins:
            await self.notification_service.safe_create_notification(
                user_id=str(admin["_id"]),
                notif_type="invoice",
                title="Invoice Generated",
                message=(
                    f"Invoice generated for project "
                    f"'{project['title']}'."
                ),
                entity_id=invoice_id,
                entity_type="Invoice",
                event_key=f"invoice_generated:{invoice_id}:{admin['_id']}",
            )

        await self.notification_service.safe_create_notification(
            user_id=str(project["userId"]),
            notif_type="invoice",
            title="Invoice available",
            message=f"Invoice {invoice_data['invoice_number']} is now available for your project.",
            entity_id=invoice_id,
            entity_type="Invoice",
            event_key=f"invoice_generated:{invoice_id}:{project['userId']}",
        )

        logger_invoice.info(
            f"Invoice {invoice_id} generated for project {project_id}"
        )

        created_invoice = await self.invoice_repo.find_by_id(invoice_id)
        if not created_invoice:
            raise ResourceNotFoundException("Invoice")
        return self._serialize_invoice(created_invoice)

    async def get_invoice(
        self,
        invoice_id: str,
        current_user: dict | None = None,
    ) -> dict:
        """Return an invoice by its ID."""

        invoice = await self.invoice_repo.find_by_id(
            invoice_id
        )

        if not invoice:
            raise ResourceNotFoundException(
                "Invoice"
            )

        await self._authorize_invoice(invoice, current_user)

        logger_invoice.info(
            f"Fetched invoice {invoice_id}"
        )

        return self._serialize_invoice(invoice)

    async def get_invoice_by_project(
        self,
        project_id: str,
        current_user: dict | None = None,
    ) -> dict:
        """Return the invoice for a project."""

        project = await self.project_repo.find_by_id(
            project_id
        )

        if not project:
            raise ResourceNotFoundException(
                "Project"
            )

        if current_user:
            await self.project_service.ensure_project_access(
                project,
                current_user,
            )

        invoice = await self.invoice_repo.find_by_project(
            project_id
        )

        if not invoice:
            raise ResourceNotFoundException(
                "Invoice"
            )

        logger_invoice.info(
            f"Fetched invoice for project {project_id}"
        )

        if current_user:
            await self._authorize_invoice(invoice, current_user)

        return self._serialize_invoice(invoice)

    async def get_invoices_by_project(
        self,
        project_id: str,
        current_user: dict | None = None,
    ) -> list[dict]:
        """Return every payment-stage invoice for a project."""

        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")
        if current_user:
            await self.project_service.ensure_project_access(project, current_user)
        invoices = await self.invoice_repo.find_all_by_project(project_id)
        if current_user:
            for invoice in invoices:
                await self._authorize_invoice(invoice, current_user)
        return [self._serialize_invoice(invoice) for invoice in invoices]

    async def _authorize_invoice(
        self,
        invoice: dict,
        current_user: dict | None,
    ) -> None:
        if not current_user:
            return
        project = await self.project_repo.find_by_id(str(invoice["projectId"]))
        if not project:
            raise ResourceNotFoundException("Project")
        await self.project_service.ensure_project_access(project, current_user)

    async def _require_super_admin_actor(
        self,
        current_user: dict,
    ) -> None:
        """Require an active, database-backed Super Admin actor."""

        if not current_user or not current_user.get("id"):
            raise PermissionException("Super Admin authentication is required.")

        user = await self.user_repo.find_by_id(str(current_user["id"]))
        if (
            not user
            or not user.get("isActive", True)
            or user.get("role") != "super_admin"
        ):
            raise PermissionException("Only an active Super Admin can perform this action.")

    async def send_invoice_to_client(
        self,
        invoice_id: str,
        current_user: dict,
    ) -> dict:
        """Email an invoice to the client."""

        await self._require_super_admin_actor(current_user)

        invoice = await self.invoice_repo.find_by_id(
            invoice_id
        )

        if not invoice:
            raise ResourceNotFoundException(
                "Invoice"
            )

        await self._authorize_invoice(invoice, current_user)
        if invoice.get("status") != "generated":
            raise ValidationException(
                "Only generated invoices can be sent."
            )

        project = await self.project_repo.find_by_id(
            str(invoice["projectId"])
        )

        if not project:
            raise ResourceNotFoundException(
                "Project"
            )

        user = await self.user_repo.find_by_id(
            str(project["userId"])
        )

        if not user:
            raise ResourceNotFoundException(
                "User"
            )

        file_path = self._safe_invoice_path(invoice["fileUrl"])

        if not os.path.exists(
            file_path
        ):
            raise ResourceNotFoundException(
                "Invoice PDF"
            )

        subject = f"Invoice {invoice['invoiceNumber']} for {project['title']}"

        body = f"""Hello {user['name']},

An invoice has been issued for your project, {project['title']}.

Invoice: {invoice['invoiceNumber']}
Amount due: {format_currency(invoice['amount'])}
Payment status: {format_status('Paid' if invoice['isPaid'] else 'Unpaid')}
Issue date: {format_date(invoice.get('generatedOn'))}
Due date: {format_date(invoice.get('dueDate'))}

The invoice PDF is attached for your records.

Regards,
Upserve
"""

        claimed = await self.invoice_repo.claim_send(invoice_id)
        if not claimed:
            raise ValidationException(
                "Invoice sending is already in progress or the invoice state has changed."
            )

        try:
            response = send_invoice_email(
                user["email"],
                subject,
                body,
                str(file_path),
                invoice_number=invoice["invoiceNumber"],
            )
        except Exception:
            await self.invoice_repo.fail_send(invoice_id)
            raise

        if not 200 <= response.status_code < 300:
            await self.invoice_repo.fail_send(invoice_id)
            raise PermissionException(
                "Failed to send invoice email via Resend."
            )

        sent_invoice = await self.invoice_repo.complete_send(invoice_id)
        if not sent_invoice:
            raise ValidationException(
                "Invoice email was sent, but its status could not be persisted. Retry only after reconciliation."
            )

        await self.activity_service.log_activity(
            user_id=(current_user["id"] if current_user else "system"),
            user_role=(current_user["role"] if current_user else "system"),
            action="Invoice Sent",
            entity="Invoice",
            entity_id=invoice_id,
            details={
                "email": user["email"],
                "projectId": str(project["_id"]),
            },
        )

        await self.notification_service.safe_create_notification(
            user_id=str(user["_id"]),
            notif_type="invoice",
            title="Invoice Sent",
            message="Your invoice has been emailed successfully.",
            entity_id=invoice_id,
            entity_type="Invoice",
            event_key=f"invoice_sent:{invoice_id}:{user['_id']}",
        )

        logger_invoice.info(
            f"Invoice {invoice_id} emailed to {user['email']}"
        )

        return {
            "message": "Invoice sent successfully.",
            "email": user["email"],
        }

    async def update_payment_status(
        self,
        invoice_id: str,
        is_paid: bool,
        current_user: dict,
        payment_amount: float | None = None,
        payment_reference: str | None = None,
        payment_method: str | None = None,
    ) -> bool:
        """Update an invoice payment status."""

        await self._require_super_admin_actor(current_user)

        invoice = await self.invoice_repo.find_by_id(
            invoice_id
        )

        if not invoice:
            raise ResourceNotFoundException(
                "Invoice"
            )

        await self._authorize_invoice(invoice, current_user)
        if not is_paid:
            raise ValidationException(
                "Payment confirmation cannot revert an invoice."
            )
        if invoice.get("status") != "sent" or invoice.get("isPaid"):
            raise ValidationException(
                "Only sent, unpaid invoices can be confirmed as paid."
            )
        if (
            payment_amount is None
            or not isfinite(float(payment_amount))
            or round(float(payment_amount), 2) != round(float(invoice["amount"]), 2)
        ):
            raise ValidationException(
                "Payment amount must match the invoice amount."
            )
        if not payment_reference or not payment_reference.strip():
            raise ValidationException("Payment reference is required.")
        if not payment_method or not payment_method.strip():
            raise ValidationException("Payment method is required.")

        project = await self.project_repo.find_by_id(str(invoice["projectId"]))
        if not project:
            raise ResourceNotFoundException("Project")
        if invoice.get("stage", "final") == "final" and project.get("status") != "delivered":
            raise ValidationException(
                "The final invoice can only be paid after the project is delivered."
            )

        paid_at = datetime.now(timezone.utc)
        updated_invoice = await self.invoice_repo.confirm_paid(
            invoice_id,
            {
                "paymentAmount": round(float(payment_amount), 2),
                "paymentReference": payment_reference.strip(),
                "paymentMethod": payment_method.strip(),
                "paidAt": paid_at,
                "paidOn": paid_at,
                "paidBy": current_user["id"],
            },
        )
        if not updated_invoice:
            raise ValidationException(
                "Invoice was already paid or is no longer eligible for payment confirmation."
            )

        client_user = await self.user_repo.find_by_id(str(project["userId"]))
        updated_pdf_path = self._invoice_storage_path() / f"invoice_{invoice['invoiceNumber']}_paid.pdf"
        try:
            updated_pdf_path.parent.mkdir(parents=True, exist_ok=True)
            generated_pdf = Path(generate_invoice_pdf(
                {
                    "client_name": (client_user or {}).get("name", "Client"),
                    "client_email": (client_user or {}).get("email", ""),
                    "title": project.get("title", "Project"),
                    "description": project.get("description"),
                    "status": project.get("status"),
                    "amount": invoice["amount"],
                    "currency": invoice.get("currency", "INR"),
                    "stage": invoice.get("stage", "final"),
                    "percentage": invoice.get("percentage", 100),
                    "invoice_number": invoice["invoiceNumber"],
                    "deadline": invoice.get("dueDate"),
                    "generated_on": invoice.get("generatedOn"),
                    "is_paid": True,
                    "payment_reference": payment_reference.strip(),
                },
                updated_pdf_path.parent,
            ))
            generated_pdf.replace(updated_pdf_path)
            await self.invoice_repo.update(invoice_id, {"fileUrl": str(updated_pdf_path)})
        except Exception as exc:
            logger_invoice.error(f"Failed to regenerate paid invoice PDF: {exc}")
            updated_pdf_path = self._safe_invoice_path(invoice["fileUrl"])

        try:
            if not client_user or not client_user.get("email"):
                raise ValueError("Project client does not have a valid email address")
            send_payment_confirmation_email(
                client_user["email"],
                client_user.get("name", "there"),
                invoice["invoiceNumber"],
                float(payment_amount),
                payment_reference.strip(),
                payment_method.strip(),
                str(updated_pdf_path),
            )
        except Exception as exc:
            logger_invoice.error(f"Failed to send payment confirmation email: {exc}")

        logger_invoice.info(
            f"Invoice {invoice_id} marked as "
            f"{'paid' if is_paid else 'sent'}"
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Invoice Payment Confirmed",
            entity="Invoice",
            entity_id=invoice_id,
            details={"projectId": str(invoice["projectId"])},
        )

        await self.notification_service.safe_create_notification(
            user_id=str(project["userId"]),
            notif_type="payment",
            title="Payment Received",
            message="Your payment has been successfully received.",
            entity_id=invoice_id,
            entity_type="Invoice",
            event_key=f"invoice_paid:{invoice_id}:{project['userId']}",
        )
        await self.notification_service.notify_admins(
            notif_type="payment",
            title="Invoice payment confirmed",
            message=f"Invoice {invoice['invoiceNumber']} was marked as paid.",
            entity_id=invoice_id,
            entity_type="Invoice",
            event_key=f"invoice_paid_admin:{invoice_id}",
            exclude_user_id=current_user["id"],
        )

        return updated_invoice

    async def cancel_invoice(
        self,
        invoice_id: str,
        current_user: dict,
    ) -> dict:
        await self._require_super_admin_actor(current_user)

        invoice = await self.invoice_repo.find_by_id(invoice_id)
        if not invoice:
            raise ResourceNotFoundException("Invoice")
        await self._authorize_invoice(invoice, current_user)
        if invoice.get("status") not in {"generated", "sent"}:
            raise ValidationException("Only generated or sent invoices can be cancelled.")
        updated_invoice = await self.invoice_repo.cancel_if_current(invoice_id)
        if not updated_invoice:
            raise ValidationException(
                "Invoice state changed before cancellation completed."
            )
        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Invoice Cancelled",
            entity="Invoice",
            entity_id=invoice_id,
        )
        project = await self.project_repo.find_by_id(str(invoice["projectId"]))
        if project:
            await self.notification_service.safe_create_notification(
                user_id=str(project["userId"]),
                notif_type="invoice",
                title="Invoice cancelled",
                message=f"Invoice {invoice['invoiceNumber']} for your project was cancelled.",
                entity_id=invoice_id,
                entity_type="Invoice",
                event_key=f"invoice_cancelled:{invoice_id}:{project['userId']}",
            )
        return self._serialize_invoice(updated_invoice)

    async def reconcile_stale_send(
        self,
        invoice_id: str,
        current_user: dict,
    ) -> dict:
        """Manually release an old uncertain email-send claim."""

        await self._require_super_admin_actor(current_user)

        invoice = await self.invoice_repo.find_by_id(invoice_id)
        if not invoice:
            raise ResourceNotFoundException("Invoice")
        if invoice.get("status") != "generated" or invoice.get("isPaid"):
            raise ValidationException(
                "Only unpaid generated invoices can be reconciled."
            )
        if invoice.get("emailSendState") != "sending":
            raise ValidationException(
                "Invoice is not awaiting send reconciliation."
            )

        updated_at = invoice.get("updatedAt")
        if not isinstance(updated_at, datetime):
            raise ValidationException(
                "Invoice does not have enough metadata for safe reconciliation."
            )
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        stale_before = datetime.now(timezone.utc) - self.STALE_SEND_AFTER
        if updated_at > stale_before:
            raise ValidationException(
                "Invoice send attempt is not stale enough to reconcile."
            )

        reconciled = await self.invoice_repo.reconcile_stale_send(
            invoice_id,
            stale_before,
            current_user["id"],
        )
        if not reconciled:
            raise ValidationException(
                "Invoice send state changed before reconciliation completed."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Invoice Send Reconciled",
            entity="Invoice",
            entity_id=invoice_id,
            details={"previousState": "sending", "newState": "failed"},
        )
        return self._serialize_invoice(reconciled)

    async def download_invoice(
        self,
        invoice_id: str,
        current_user: dict,
    ) -> tuple[Path, str]:
        invoice = await self.invoice_repo.find_by_id(invoice_id)
        if not invoice:
            raise ResourceNotFoundException("Invoice")
        await self._authorize_invoice(invoice, current_user)
        file_path = self._safe_invoice_path(invoice.get("fileUrl", ""))
        if not file_path.is_file():
            raise ResourceNotFoundException("Invoice PDF")
        return file_path, f"invoice_{invoice['invoiceNumber']}.pdf"
