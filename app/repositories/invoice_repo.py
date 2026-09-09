"""Invoice Repository."""

from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime, timezone
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, OperationFailure

from app.exceptions import DuplicateException, ValidationException
from app.repositories.base_repo import BaseRepository


class InvoiceRepository(BaseRepository):
    """Repository for invoice operations."""

    def __init__(self):
        super().__init__("invoices")

    async def ensure_indexes(self) -> None:
        """Ensure invoice identity and one-invoice-per-stage rules."""

        try:
            await self.collection.drop_index("invoices_project_unique")
        except OperationFailure:
            pass
        await self.collection.create_index(
            [("projectId", 1), ("stage", 1)],
            unique=True,
            name="invoices_project_stage_unique",
            partialFilterExpression={
                "projectId": {"$exists": True},
                "stage": {"$type": "string"},
            },
        )
        await self.collection.create_index(
            "invoiceNumber",
            unique=True,
            name="invoices_number_unique",
            partialFilterExpression={
                "invoiceNumber": {"$type": "string"}
            },
        )

    async def create(self, data: dict) -> str:
        """Create an invoice and translate duplicate-key failures."""

        try:
            return await super().create(data)
        except DuplicateKeyError as exc:
            if "project" in str(exc):
                raise DuplicateException(
                    "Invoice already exists for this project."
                )
            raise DuplicateException("Invoice number")

    async def find_by_project(
        self,
        project_id: str,
    ) -> dict | None:
        """Find an invoice by project ID."""

        values = [project_id]
        try:
            values.append(ObjectId(project_id))
        except (InvalidId, TypeError):
            pass
        return await self.find_one({"projectId": {"$in": values}})

    async def find_all_by_project(self, project_id: str) -> list[dict]:
        """Find all invoices for a project in payment-stage order."""

        values = [project_id]
        try:
            values.append(ObjectId(project_id))
        except (InvalidId, TypeError):
            pass
        stage_order = {"advance": 1, "milestone": 2, "final": 3}
        invoices = [doc async for doc in self.collection.find({"projectId": {"$in": values}})]
        if len(invoices) == 1 and not invoices[0].get("stage"):
            # Existing one-invoice records represented the full project value.
            # Keep them readable as legacy final invoices without rewriting data.
            invoices[0] = {**invoices[0], "stage": "final", "percentage": 100}
        invoices.sort(key=lambda item: (stage_order.get(item.get("stage"), 0), item.get("generatedOn") or item.get("createdAt")))
        return invoices

    async def get_financial_summary(self, project_id: str, project_value: float | None = None, project: dict | None = None) -> dict:
        """Return backend-derived project payment schedule and totals."""

        invoices = await self.find_all_by_project(project_id)
        # The accepted quotation/project commercial value is the source of truth.
        # Do not let a partially generated invoice redefine the full project value.
        if project_value is not None:
            total_value = round(float(project_value), 2)
        else:
            total_value = round(sum(float(item.get("amount", 0)) for item in invoices), 2)
        paid = round(sum(float(item.get("amount", 0)) for item in invoices if item.get("isPaid")), 2)
        schedule = self._payment_schedule_from_project(project)
        stages = []
        for stage, percentage in schedule.items():
            invoice = next((item for item in invoices if item.get("stage") == stage), None)
            if invoice:
                amount = round(float(invoice.get("amount", 0)), 2)
            elif stage == "advance":
                amount = round(total_value * percentage / 100, 2)
            elif stage == "milestone":
                amount = round(total_value * percentage / 100, 2)
            else:
                amount = round(total_value - round(total_value * schedule["advance"] / 100, 2) - round(total_value * schedule["milestone"] / 100, 2), 2)
            stages.append({"stage": stage, "percentage": percentage, "amount": amount, "invoiceId": str(invoice["_id"]) if invoice else None, "status": invoice.get("status") if invoice else "not_generated", "isPaid": bool(invoice and invoice.get("isPaid"))})
        return {
            "totalProjectValue": total_value,
            "totalPaid": paid,
            "outstandingAmount": max(0, round(total_value - paid, 2)),
            "stages": stages,
            "paymentSchedule": {
                "advancePercentage": schedule["advance"],
                "milestonePercentage": schedule["milestone"],
                "finalPercentage": schedule["final"],
            },
        }

    @staticmethod
    def _payment_schedule_from_project(project: dict | None) -> dict[str, float]:
        """Return the configured schedule, with legacy 40/30/30 fallback."""

        configured = (project or {}).get("paymentSchedule") or {}
        values = {
            "advance": configured.get("advancePercentage", 40),
            "milestone": configured.get("milestonePercentage", 30),
            "final": configured.get("finalPercentage", 30),
        }
        try:
            values = {stage: float(value) for stage, value in values.items()}
        except (TypeError, ValueError):
            values = {"advance": 40.0, "milestone": 30.0, "final": 30.0}
        if any(value < 0 for value in values.values()) or abs(sum(values.values()) - 100) > 1e-9:
            return {"advance": 40.0, "milestone": 30.0, "final": 30.0}
        return values

    async def exists_by_project(self, project_id: str) -> bool:
        return await self.find_by_project(project_id) is not None

    async def confirm_paid(
        self,
        invoice_id: str,
        payment_data: dict,
    ) -> dict | None:
        """Atomically confirm an invoice that is currently sent and unpaid."""

        try:
            return await self.collection.find_one_and_update(
                {
                    "_id": ObjectId(invoice_id),
                    "status": "sent",
                    "isPaid": False,
                },
                {
                    "$set": {
                        **payment_data,
                        "status": "paid",
                        "isPaid": True,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
        except (TypeError, ValueError):
            raise ValidationException("Invalid invoice ID format.")

    async def cancel_if_current(self, invoice_id: str) -> dict | None:
        """Atomically cancel an unpaid invoice in an eligible state."""

        try:
            return await self.collection.find_one_and_update(
                {
                    "_id": ObjectId(invoice_id),
                    "status": {"$in": ["generated", "sent"]},
                    "isPaid": False,
                    "emailSendState": {"$ne": "sending"},
                },
                {
                    "$set": {
                        "status": "cancelled",
                        "updatedAt": datetime.now(timezone.utc),
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
        except (TypeError, ValueError):
            raise ValidationException("Invalid invoice ID format.")

    async def claim_send(self, invoice_id: str) -> dict | None:
        """Claim an invoice send attempt without changing its lifecycle status."""

        try:
            return await self.collection.find_one_and_update(
                {
                    "_id": ObjectId(invoice_id),
                    "status": "generated",
                    "isPaid": False,
                    "emailSendState": {"$ne": "sending"},
                },
                {
                    "$set": {
                        "emailSendState": "sending",
                        "updatedAt": datetime.now(timezone.utc),
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
        except (TypeError, ValueError):
            raise ValidationException("Invalid invoice ID format.")

    async def complete_send(self, invoice_id: str) -> dict | None:
        """Persist a successful send only for the claimed invoice."""

        try:
            return await self.collection.find_one_and_update(
                {
                    "_id": ObjectId(invoice_id),
                    "status": "generated",
                    "isPaid": False,
                    "emailSendState": "sending",
                },
                {
                    "$set": {
                        "status": "sent",
                        "emailSendState": "sent",
                        "updatedAt": datetime.now(timezone.utc),
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
        except (TypeError, ValueError):
            raise ValidationException("Invalid invoice ID format.")

    async def fail_send(self, invoice_id: str) -> bool:
        """Release a send claim when delivery definitively failed."""

        try:
            result = await self.collection.update_one(
                {
                    "_id": ObjectId(invoice_id),
                    "status": "generated",
                    "emailSendState": "sending",
                },
                {"$set": {
                    "emailSendState": "failed",
                    "updatedAt": datetime.now(timezone.utc),
                }},
            )
            return result.modified_count > 0
        except (TypeError, ValueError):
            raise ValidationException("Invalid invoice ID format.")

    async def reconcile_stale_send(
        self,
        invoice_id: str,
        stale_before: datetime,
        reconciled_by: str,
    ) -> dict | None:
        """Release only a stale, still-generated send claim."""

        try:
            return await self.collection.find_one_and_update(
                {
                    "_id": ObjectId(invoice_id),
                    "status": "generated",
                    "isPaid": False,
                    "emailSendState": "sending",
                    "updatedAt": {"$lte": stale_before},
                },
                {
                    "$set": {
                        "emailSendState": "failed",
                        "sendReconciledAt": datetime.now(timezone.utc),
                        "sendReconciledBy": reconciled_by,
                        "updatedAt": datetime.now(timezone.utc),
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
        except (InvalidId, TypeError):
            raise ValidationException("Invalid invoice ID format.")

    async def count_paid(
        self,
    ) -> int:
        """Return the total number of paid invoices."""

        return await self.count(
            {
                "isPaid": True
            }
        )

    async def count_unpaid(
        self,
    ) -> int:
        """Return the total number of unpaid invoices."""

        return await self.count(
            {
                "isPaid": False
            }
        )

    async def get_next_invoice_number(
        self,
    ) -> str:
        """Generate the next invoice number."""

        sequence = await self.get_next_sequence(
            "invoice"
        )

        return f"INV-{sequence:05d}"

    async def count_all(
        self,
    ) -> int:
        """Return the total number of invoices."""

        return await self.count({})

    async def get_recent_invoices(
        self,
        limit: int = 5,
    ) -> list[dict]:
        """Return the most recently generated invoices."""

        cursor = (
            self.collection.find()
            .sort("generatedOn", -1)
            .limit(limit)
        )

        return [doc async for doc in cursor]
