"""Admin Service."""

import asyncio
from datetime import datetime

from bson import ObjectId

from app.exceptions import AuthorizationException
from app.logger import logger_admin
from app.repositories.activitylog_repo import ActivityLogRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.deliverables_repo import DeliverablesRepository
from app.repositories.invoice_repo import InvoiceRepository
from app.repositories.lead_repo import LeadRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.quotation_repo import QuotationRepository
from app.repositories.requirement_repo import RequirementRepository
from app.repositories.user_repo import UserRepository
from app.services.activitylog_service import ActivityLogService


class AdminService:
    """Service for admin dashboard and system statistics."""

    def __init__(self):
        self.user_repo = UserRepository()
        self.project_repo = ProjectRepository()
        self.invoice_repo = InvoiceRepository()
        self.lead_repo = LeadRepository()
        self.quotation_repo = QuotationRepository()
        self.requirement_repo = RequirementRepository()
        self.deliverables_repo = DeliverablesRepository()
        self.contact_repo = ContactRepository()
        self.activity_repo = ActivityLogRepository()

    @staticmethod
    def _serialize_statistics_value(value):
        """Convert MongoDB-specific values before API serialization."""

        if isinstance(value, ObjectId):
            return str(value)

        if isinstance(value, datetime):
            return value.isoformat()

        if isinstance(value, dict):
            return {
                ("id" if key == "_id" else key):
                AdminService._serialize_statistics_value(item)
                for key, item in value.items()
            }

        if isinstance(value, list):
            return [
                AdminService._serialize_statistics_value(item)
                for item in value
            ]

        return value

    async def get_dashboard(
        self,
        current_user: dict,
    ) -> dict:
        """Return dashboard information for an admin."""

        logger_admin.info(
            f"Dashboard accessed by {current_user.get('email')}"
        )

        role = current_user.get("role")

        if role not in [
            "super_admin",
            "sub_admin",
        ]:
            raise AuthorizationException(
                "Admin access only"
            )

        role_display = (
            "Super Admin"
            if role == "super_admin"
            else "Sub Admin"
        )

        return {
            "message": (
                f"Welcome {role_display} "
                f"{current_user.get('name')}"
            ),
            "role": role,
        }

    async def get_summary(
        self,
        current_user: dict,
    ) -> dict:
        """Return system summary."""

        if current_user.get("role") != "super_admin":
            raise AuthorizationException(
                "Only Super Admin can view global system summaries."
            )

        total_users = await self.user_repo.count({})
        admin_count = await self.user_repo.get_admin_count()
        client_count = await self.user_repo.count_by_role(
            "client"
        )

        total_projects = await self.project_repo.count_all()
        pending = await self.project_repo.count_by_status(
            "pending"
        )
        accepted = await self.project_repo.count_by_status(
            "accepted"
        )
        in_progress = await self.project_repo.count_by_status(
            "in_progress"
        )
        testing = await self.project_repo.count_by_status(
            "testing"
        )
        deployment = await self.project_repo.count_by_status(
            "deployment"
        )
        delivered = await self.project_repo.count_by_status(
            "delivered"
        )
        completed = await self.project_repo.count_by_status(
            "completed"
        )

        total_invoices = await self.invoice_repo.count_all()
        paid = await self.invoice_repo.count_paid()
        unpaid = await self.invoice_repo.count_unpaid()

        contacts = await self.contact_repo.count_all()

        logger_admin.info(
            "Admin summary generated"
        )

        return {
            "users": {
                "total": total_users,
                "admins": admin_count,
                "clients": client_count,
            },
            "projects": {
                "total": total_projects,
                "pending": pending,
                "accepted": accepted,
                "in_progress": in_progress,
                "testing": testing,
                "deployment": deployment,
                "delivered": delivered,
                "completed": completed,
            },
            "contacts": contacts,
            "invoices": {
                "total": total_invoices,
                "paid": paid,
                "unpaid": unpaid,
            },
        }

    async def get_recent_activities(
        self,
        limit: int = 10,
        current_user: dict | None = None,
    ) -> list[dict]:
        """Return recent activity logs."""

        if current_user and current_user.get("role") != "super_admin":
            raise AuthorizationException(
                "Only Super Admin can view global activity history."
            )

        logs = await self.activity_repo.get_recent(
            limit
        )

        logger_admin.info(
            f"Fetched {len(logs)} recent activities"
        )

        return [ActivityLogService.normalize_log(log) for log in logs]

    async def get_system_stats(
        self,
        current_user: dict,
    ) -> dict:
        """Return recent system statistics."""

        if current_user.get("role") != "super_admin":
            raise AuthorizationException(
                "Only Super Admin can view global system statistics."
            )

        recent_projects = (
            await self.project_repo.get_recent_projects(
                5
            )
        )

        recent_contacts = (
            await self.contact_repo.get_recent_contacts(
                5
            )
        )

        recent_invoices = (
            await self.invoice_repo.get_recent_invoices(
                5
            )
        )

        return {
            "recent_projects": self._serialize_statistics_value(
                recent_projects
            ),
            "recent_contacts": self._serialize_statistics_value(
                recent_contacts
            ),
            "recent_invoices": self._serialize_statistics_value(
                recent_invoices
            ),
        }

    async def get_reference_data(self, current_user: dict) -> dict:
        """Return a readable Super Admin directory of business-flow records."""

        if current_user.get("role") != "super_admin":
            raise AuthorizationException(
                "Only Super Admin can view the record directory."
            )

        users, leads, requirements, quotations, projects, deliverables, invoices = await asyncio.gather(
            self.user_repo.find_many({}, limit=10000, projection={"name": 1, "email": 1, "role": 1, "isActive": 1}),
            self.lead_repo.find_many({}, limit=10000, projection={"contactPerson": 1, "email": 1, "companyName": 1, "stage": 1, "clientId": 1, "assignedTo": 1}),
            self.requirement_repo.find_many({}, limit=10000, projection={"businessName": 1, "projectId": 1, "status": 1, "deadline": 1}),
            self.quotation_repo.find_many({}, limit=10000, projection={"quotationNumber": 1, "clientId": 1, "leadId": 1, "projectId": 1, "status": 1, "totalAmount": 1}),
            self.project_repo.find_many({}, limit=10000, projection={"title": 1, "userId": 1, "quotationId": 1, "leadId": 1, "status": 1, "deadline": 1, "assignedAdmin": 1, "assignedSubAdmin": 1}),
            self.deliverables_repo.find_many({}, limit=10000, projection={"title": 1, "projectId": 1, "status": 1, "dueDate": 1}),
            self.invoice_repo.find_many({}, limit=10000, projection={"invoiceNumber": 1, "stage": 1, "projectId": 1, "clientId": 1, "quotationId": 1, "leadId": 1, "status": 1, "amount": 1}),
        )

        def records(items: list[dict], fields: tuple[str, ...]) -> list[dict]:
            result = []
            for item in items:
                row = {"id": item.get("_id")}
                row.update({field: item.get(field) for field in fields})
                result.append(self._serialize_statistics_value(row))
            return result

        return {
            "users": records(users, ("name", "email", "role", "isActive")),
            "leads": records(leads, ("contactPerson", "email", "companyName", "stage", "clientId", "assignedTo")),
            "requirements": records(requirements, ("businessName", "projectId", "status", "deadline")),
            "quotations": records(quotations, ("quotationNumber", "clientId", "leadId", "projectId", "status", "totalAmount")),
            "projects": records(projects, ("title", "userId", "quotationId", "leadId", "status", "deadline", "assignedAdmin", "assignedSubAdmin")),
            "deliverables": records(deliverables, ("title", "projectId", "status", "dueDate")),
            "invoices": records(invoices, ("invoiceNumber", "stage", "projectId", "clientId", "quotationId", "leadId", "status", "amount")),
        }
