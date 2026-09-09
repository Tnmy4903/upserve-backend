from datetime import datetime, timezone

from app.exceptions import (
    DuplicateException,
    PermissionException,
    ResourceNotFoundException,
    ValidationException,
)
from app.logger import logger_project
from app.repositories.project_repo import ProjectRepository
from app.repositories.lead_repo import LeadRepository
from app.repositories.quotation_repo import QuotationRepository
from app.repositories.deliverables_repo import DeliverablesRepository
from app.repositories.timeline_repo import TimelineRepository
from app.repositories.upload_repo import UploadRepository
from app.repositories.invoice_repo import InvoiceRepository
from app.repositories.discussion_repo import DiscussionRepository
from app.repositories.requirement_repo import RequirementRepository
from app.repositories.user_repo import UserRepository
from app.services.activitylog_service import ActivityLogService
from app.services.notification_service import NotificationService
from app.services.email import send_project_completion_email


class ProjectService:
    """Service for project management."""

    def __init__(self):
        self.project_repo = ProjectRepository()
        self.lead_repo = LeadRepository()
        self.quotation_repo = QuotationRepository()
        self.deliverables_repo = DeliverablesRepository()
        self.timeline_repo = TimelineRepository()
        self.upload_repo = UploadRepository()
        self.invoice_repo = InvoiceRepository()
        self.discussion_repo = DiscussionRepository()
        self.requirement_repo = RequirementRepository()
        self.user_repo = UserRepository()
        self.activity_service = ActivityLogService()
        self.notification_service = NotificationService()

    async def _record_system_timeline_event(
        self,
        project_id: str,
        title: str,
        description: str,
        created_by: str,
        event_type: str,
        event_key: str,
    ) -> None:
        await self.timeline_repo.create_system_event(
            project_id=project_id,
            title=title,
            description=description,
            created_by=created_by,
            event_type=event_type,
            event_key=event_key,
        )

    async def _ensure_status_timeline_event(
        self,
        project_id: str,
        status: str,
        created_by: str,
    ) -> None:
        """Create the lifecycle event once, including retry recovery."""

        status_events = {
            "in_progress": ("Project Started", "project_started"),
            "testing": ("Testing Started", "project_testing"),
            "deployment": ("Deployment Started", "project_deployment"),
            "delivered": ("Project Delivered", "project_delivered"),
            "completed": ("Project Completed", "project_completed"),
        }
        event = status_events.get(status)
        if not event:
            return
        title, event_type = event
        await self._record_system_timeline_event(
            project_id=project_id,
            title=title,
            description=f"Project status changed to {status}.",
            created_by=created_by,
            event_type=event_type,
            event_key=event_type,
        )

    async def _with_progress(self, project: dict) -> dict:
        """Attach a read-only progress projection to a project response."""

        quotation = await self.quotation_repo.find_by_id(str(project.get("quotationId"))) if project.get("quotationId") else None
        if quotation:
            requirement = await self.requirement_repo.find_by_project(str(project.get("id") or project.get("_id")))
            if not requirement and quotation.get("leadId"):
                requirement = await self.requirement_repo.find_by_lead(str(quotation["leadId"]))
            lead = await self.lead_repo.find_by_id(str(quotation["leadId"])) if quotation.get("leadId") else None
            client = await self.user_repo.find_by_id(str(project.get("userId"))) if project.get("userId") else None
            resolved_title = (
                str(quotation.get("projectTitle") or "").strip()
                or str((requirement or {}).get("businessName") or "").strip()
                or str((lead or {}).get("companyName") or "").strip()
                or f"{str((client or {}).get('name') or 'Client').strip()}'s project"
            )
            legacy_service_title = (quotation.get("services") or [None])[0]
            if not project.get("title") or project.get("title") == legacy_service_title:
                project["title"] = resolved_title

        project.update(
            await self.deliverables_repo.get_progress_summary(
                str(project.get("id") or project["_id"])
            )
        )
        financial = await self.invoice_repo.get_financial_summary(
            str(project.get("id") or project["_id"]),
            await self._commercial_value(project),
            project,
        )
        project.update(
            {
                "totalProjectValue": financial["totalProjectValue"],
                "totalPaid": financial["totalPaid"],
                "outstandingAmount": financial["outstandingAmount"],
                "invoiceSchedule": financial["stages"],
                "paymentSchedule": financial["paymentSchedule"],
            }
        )
        return project

    async def _commercial_value(self, project: dict) -> float | None:
        """Resolve the project value from its accepted quotation first."""

        quotation_id = project.get("quotationId")
        if quotation_id:
            quotation = await self.quotation_repo.find_by_id(str(quotation_id))
            if quotation and quotation.get("totalAmount") is not None:
                try:
                    value = float(quotation["totalAmount"])
                    if value > 0:
                        return value
                except (TypeError, ValueError):
                    pass
        return project.get("budget")

    async def ensure_project_access(
        self,
        project: dict,
        current_user: dict,
    ) -> None:
        """Validate common client, Sub Admin, and Super Admin access."""

        role = current_user.get("role")
        user_id = current_user.get("id")

        if role == "super_admin":
            return

        if role == "client" and str(project.get("userId")) == user_id:
            return

        if role == "sub_admin":
            if str(project.get("assignedSubAdmin")) == user_id:
                return
            if project.get("leadId"):
                lead = await self.lead_repo.find_by_id(
                    str(project["leadId"])
                )
                assigned_ids = {
                    str(value)
                    for value in lead.get("assignedToIds", [])
                    if value
                } if lead else set()
                if lead and lead.get("assignedTo"):
                    assigned_ids.add(str(lead["assignedTo"]))
                if lead and user_id in assigned_ids:
                    return

        raise PermissionException("Project not found or access denied.")

    async def _require_project_editor_actor(
        self,
        current_user: dict,
    ) -> None:
        """Require an active, database-backed project editor actor."""

        if not current_user or not current_user.get("id"):
            raise PermissionException("Project editor authentication is required.")

        user = await self.user_repo.find_by_id(str(current_user["id"]))
        if (
            not user
            or not user.get("isActive", True)
            or user.get("role") not in ["super_admin", "sub_admin"]
        ):
            raise PermissionException("Only an active Super Admin or Sub Admin can perform this action.")

    @staticmethod
    def _serialize_project(project: dict) -> dict:
        """Return project identifiers in the API's string format."""

        if project.get("_id") is not None:
            project["id"] = str(project["_id"])
            project.pop("_id", None)
        elif project.get("id") is not None:
            project["id"] = str(project["id"])
        else:
            raise ValidationException("Project is missing an identifier.")
        for field in (
            "userId",
            "quotationId",
            "leadId",
            "assignedAdmin",
            "assignedSubAdmin",
        ):
            if project.get(field) is not None:
                project[field] = str(project[field])
        if project.get("description") is None:
            project["description"] = ""
        return project

    async def create_project_internal(
        self,
        client_id: str,
        quotation_id: str,
        lead_id: str,
        title: str,
        description: str,
        deadline,
        budget: float,
        assigned_admin: str | None = None,
        assigned_sub_admin: str | None = None,
        current_user: dict | None = None,
    ) -> dict:
        """Create a new project."""

        client = await self.user_repo.find_by_id(client_id)
        if not client or client.get("role") != "client":
            raise ValidationException(
                "Project client must be a valid client user."
            )

        quotation = await self.quotation_repo.find_by_id(quotation_id)
        if not quotation:
            raise ResourceNotFoundException("Quotation")
        if quotation.get("status") != "Accepted":
            raise ValidationException(
                "Project can only be created from an accepted quotation."
            )
        if str(quotation.get("clientId")) != client_id:
            raise ValidationException(
                "Quotation does not belong to the project client."
            )
        if quotation.get("leadId") and str(quotation["leadId"]) != lead_id:
            raise ValidationException(
                "Lead does not match the quotation relationship."
            )
        if not await self.lead_repo.find_by_id(lead_id):
            raise ResourceNotFoundException("Lead")

        project_data = {
            "userId": client_id,
            "quotationId": quotation_id,
            "leadId": lead_id,
            "title": title,
            "description": description,
            "deadline": deadline,
            "budget": budget,
            "assignedAdmin": assigned_admin,
            "assignedSubAdmin": assigned_sub_admin,
            "status": "pending",
        }

        project_id = await self.project_repo.create(
            project_data
        )

        await self._record_system_timeline_event(
            project_id=project_id,
            title="Project Created",
            description="Project created from an accepted quotation.",
            created_by="system",
            event_type="project_created",
            event_key="project_created",
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"] if current_user else "system",
            user_role=current_user["role"] if current_user else "system",
            action="Project Created",
            entity="Project",
            entity_id=project_id,
            details={
                "quotationId": quotation_id,
                "leadId": lead_id,
                "clientId": client_id,
            },
        )

        await self.notification_service.notify_project_participants(
            project_data,
            notif_type="project",
            title="Project created",
            message=f"Project '{title}' is now ready to start.",
            entity_id=project_id,
            entity_type="Project",
            event_key=f"project_created:{project_id}",
            exclude_user_id=current_user["id"] if current_user else None,
        )

        logger_project.info(
            f"Project created: {project_id} "
            f"by user {client_id} "
            f"of quotation {quotation_id} "
            f"and lead {lead_id}"
        )

        result = {
            "id": project_id,
            "userId": client_id,
            "quotationId": quotation_id,
            "leadId": lead_id,
            "assignedAdmin": assigned_admin,
            "assignedSubAdmin": assigned_sub_admin,
            "status": "pending",
            "title": title,
            "description": description,
            "deadline": deadline,
            "budget": budget,
        }
        result.update(
            await self.deliverables_repo.get_progress_summary(project_id)
        )
        result["paymentSchedule"] = self.invoice_repo._payment_schedule_from_project(project_data)
        return result

    async def create_project_from_quotation(
        self,
        quotation: dict,
        current_user: dict | None = None,
    ) -> dict:
        """Automatically create a project after quotation acceptance."""

        if not quotation.get(
            "clientId"
        ):
            raise ValidationException(
                "Quotation does not contain a valid client."
            )

        if not quotation.get(
            "totalAmount"
        ):
            raise ValidationException(
                "Quotation total amount is missing."
            )

        client = await self.user_repo.find_by_id(
            str(quotation["clientId"])
        )
        if not client or client.get("role") != "client":
            raise ValidationException(
                "Quotation client is not a valid client user."
            )

        existing = await self.project_repo.find_by_quotation(
            str(quotation["id"])
        )

        if existing:
            self._serialize_project(existing)
            return await self._with_progress(existing)

        requirement = None
        if quotation.get("leadId"):
            requirement = await self.requirement_repo.find_by_lead(
                str(quotation["leadId"])
            )
        if not requirement:
            requirement = await self.requirement_repo.find_by_project(
                str(quotation.get("projectId"))
            ) if quotation.get("projectId") else None

        lead = await self.lead_repo.find_by_id(str(quotation["leadId"])) if quotation.get("leadId") else None
        project_title = (
            str(quotation.get("projectTitle") or "").strip()
            or str((requirement or {}).get("businessName") or "").strip()
            or str((lead or {}).get("companyName") or "").strip()
            or f"{str(client.get('name') or 'Client').strip()}'s project"
        )

        project_data = {
            "quotationId": quotation["id"],
            "leadId": quotation.get(
                "leadId"
            ),
            "userId": quotation["clientId"],
            "title": project_title,
            "description": quotation.get("notes") or "",
            # The quotation amount remains commercial data; delivery budget
            # starts at zero until an admin explicitly sets it.
            "budget": 0,
            "status": "pending",
        }

        try:
            project_id = await self.project_repo.create(
                project_data
            )
        except DuplicateException:
            existing = await self.project_repo.find_by_quotation(
                str(quotation["id"])
            )
            if not existing:
                raise
            self._serialize_project(existing)
            return await self._with_progress(existing)

        project_data["id"] = project_id
        self._serialize_project(project_data)
        project_data.update(
            await self.deliverables_repo.get_progress_summary(project_id)
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"] if current_user else "system",
            user_role=current_user["role"] if current_user else "system",
            action="Project Created",
            entity="Project",
            entity_id=project_id,
            details={
                "quotationId": quotation.get("id"),
                "leadId": quotation.get("leadId"),
                "clientId": quotation.get("clientId"),
            },
        )

        await self.notification_service.notify_project_participants(
            project_data,
            notif_type="project",
            title="Project created",
            message=f"Project '{project_data.get('title', 'Project')}' is now ready to start.",
            entity_id=project_id,
            entity_type="Project",
            event_key=f"project_created:{project_id}",
            exclude_user_id=current_user["id"] if current_user else None,
        )

        return project_data

    async def update_status(
        self,
        project_id: str,
        status: str,
        current_user: dict,
    ) -> bool:
        """Update the status of a project."""

        valid_transitions = {
            "pending": ["in_progress"],
            "in_progress": ["testing"],
            "testing": ["deployment"],
            "deployment": ["delivered"],
            "delivered": ["completed"],
            "completed": [],
        }

        project = await self.project_repo.find_by_id(
            project_id
        )

        if not project:
            raise ResourceNotFoundException(
                "Project"
            )

        await self._require_project_editor_actor(current_user)
        await self.ensure_project_access(project, current_user)

        current_status = project.get(
            "status",
            "pending",
        )

        if (
            current_status
            not in valid_transitions
        ):
            raise ValidationException(
                f"Invalid current project status: {current_status}"
            )

        if current_status == status:
            status_events = {
                "in_progress": "project_started",
                "testing": "project_testing",
                "deployment": "project_deployment",
                "delivered": "project_delivered",
                "completed": "project_completed",
            }
            event_key = status_events.get(status)
            if event_key and not await self.timeline_repo.find_system_event(
                project_id,
                event_key,
            ):
                try:
                    await self._ensure_status_timeline_event(
                        project_id,
                        status,
                        current_user["id"],
                    )
                except Exception:
                    logger_project.exception(
                        "Failed to recover project lifecycle event for %s",
                        project_id,
                    )
                    raise
                return True
            raise ValidationException(
                f"Project is already in '{status}' status."
            )

        if (
            status
            not in valid_transitions
        ):
            raise ValidationException(
                "Invalid project status"
            )

        if (
            status
            not in valid_transitions[
                current_status
            ]
        ):
            raise ValidationException(
                f"Cannot change project status from "
                f"{current_status} to {status}"
            )

        if status in {"delivered", "completed"}:
            total, completed = await self.deliverables_repo.all_non_cancelled_completed(
                project_id
            )
            if total == 0 or total != completed:
                raise ValidationException(
                    "At least one deliverable must exist and all non-cancelled deliverables must be completed before the project can be delivered or completed."
                )

            requirement = await self.requirement_repo.find_by_project(project_id)
            if not requirement and project.get("leadId"):
                requirement = await self.requirement_repo.find_by_lead(
                    str(project["leadId"])
                )
            if requirement and requirement.get("status") != "APPROVED":
                raise ValidationException(
                    "The project requirement must be approved before delivery or completion."
                )

        if status == "completed":
            financial = await self.invoice_repo.get_financial_summary(
                project_id,
                await self._commercial_value(project),
                project,
            )
            if financial["outstandingAmount"] > 0:
                raise ValidationException(
                    "All project payments must be complete before the project can be completed."
                )

        updated = await self.project_repo.update_status_if_current(
            project_id,
            current_status,
            status,
        )

        if not updated:
            latest = await self.project_repo.find_by_id(project_id)
            if latest and latest.get("status") == status:
                event_key = {
                    "in_progress": "project_started",
                    "testing": "project_testing",
                    "deployment": "project_deployment",
                    "delivered": "project_delivered",
                    "completed": "project_completed",
                }.get(status)
                if event_key and not await self.timeline_repo.find_system_event(
                    project_id,
                    event_key,
                ):
                    await self._ensure_status_timeline_event(
                        project_id,
                        status,
                        current_user["id"],
                    )
                return True
            raise ValidationException(
                "Project status changed before this request completed."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Project Status Updated",
            entity="Project",
            entity_id=project_id,
            details={
                "previousStatus": current_status,
                "newStatus": status,
            },
        )

        try:
            await self._ensure_status_timeline_event(
                project_id,
                status,
                current_user["id"],
            )
        except Exception:
            logger_project.exception(
                "Project status updated but lifecycle event recording failed for %s",
                project_id,
            )
            raise

        await self.notification_service.notify_project_participants(
            project,
            notif_type="project",
            title="Project status updated",
            message=f"Project '{project.get('title', 'Project')}' moved from {current_status.replace('_', ' ')} to {status.replace('_', ' ')}.",
            entity_id=project_id,
            entity_type="Project",
            event_key=f"project_status:{project_id}:{status}",
            exclude_user_id=current_user["id"],
        )

        if status == "completed":
            try:
                client = await self.user_repo.find_by_id(str(project["userId"]))
                if client and client.get("email"):
                    financial = await self.invoice_repo.get_financial_summary(project_id, await self._commercial_value(project), project)
                    progress = await self.deliverables_repo.get_progress_summary(project_id)
                    send_project_completion_email(
                        client["email"], client.get("name", "there"), project.get("title", "your project"),
                        float(financial.get("totalProjectValue", project.get("budget") or 0)),
                        float(financial.get("totalPaid", financial.get("totalProjectValue", project.get("budget") or 0) or 0)),
                        int(progress.get("completedDeliverables", progress.get("completed", 0))),
                    )
            except Exception as exc:
                logger_project.error(f"Failed to send project completion email: {exc}")

        logger_project.info(
            f"Project {project_id} status updated to {status}"
        )

        return updated

    async def set_budget(
        self,
        project_id: str,
        budget: float,
        current_user: dict,
    ) -> bool:
        """Set the budget of a project."""

        if budget <= 0:
            raise ValidationException(
                "Budget must be greater than zero."
            )

        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")

        await self._require_project_editor_actor(current_user)
        await self.ensure_project_access(project, current_user)

        previous_budget = project.get("budget")

        updated = await self.project_repo.update(
            project_id,
            {
                "budget": budget,
            },
        )

        if not updated:
            raise ValidationException(
                "Failed to update project budget."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="Project Budget Updated",
            entity="Project",
            entity_id=project_id,
            details={
                "previousBudget": previous_budget,
                "newBudget": budget,
            },
        )

        await self._record_system_timeline_event(
            project_id=project_id,
            title="Project Budget Updated",
            description=f"Project budget changed from {previous_budget} to {budget}.",
            created_by=(current_user["id"] if current_user else "system"),
            event_type="budget_updated",
            event_key=(
                f"budget_updated:{previous_budget}:{budget}:"
                f"{datetime.now(timezone.utc).isoformat()}"
            ),
        )

        await self.notification_service.notify_admins(
            notif_type="project",
            title="Project budget updated",
            message=f"Project budget changed from {previous_budget} to {budget}.",
            entity_id=project_id,
            entity_type="Project",
            event_key=f"project_budget:{project_id}:{previous_budget}:{budget}",
            exclude_user_id=current_user["id"],
        )

        logger_project.info(
            f"Project {project_id} budget set to {budget}"
        )

        return updated

    async def set_payment_schedule(
        self,
        project_id: str,
        schedule: dict,
        current_user: dict,
    ) -> bool:
        """Set a project schedule before any stage invoice exists."""

        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")
        await self._require_project_editor_actor(current_user)
        await self.ensure_project_access(project, current_user)
        if await self.invoice_repo.find_all_by_project(project_id):
            raise ValidationException("Payment schedule cannot change after an invoice is generated.")
        updated = await self.project_repo.update(project_id, {"paymentSchedule": schedule})
        if not updated:
            raise ValidationException("Failed to update payment schedule.")
        return updated

    async def get_my_projects(
        self,
        user_id: str,
    ) -> list[dict]:
        """Return projects belonging to a user."""

        projects = await self.project_repo.find_by_user(
            user_id
        )

        for project in projects:
            self._serialize_project(project)
            await self._with_progress(project)

        logger_project.info(
            f"Fetched {len(projects)} projects for user {user_id}"
        )

        return projects

    async def get_all_projects(
        self,
        current_user: dict,
    ) -> list[dict]:
        """Return all projects."""

        if current_user.get("role") == "super_admin":
            projects = await self.project_repo.get_all_sorted()
        elif current_user.get("role") == "sub_admin":
            leads = await self.lead_repo.find_many(
                {"assignedTo": current_user["id"]},
                limit=1_000_000,
            )
            lead_ids = [str(lead["_id"]) for lead in leads]
            projects = await self.project_repo.find_many(
                {
                    "$or": [
                        {"assignedSubAdmin": current_user["id"]},
                        {"leadId": {"$in": lead_ids}},
                    ]
                },
                limit=1_000_000,
            )
            projects.sort(
                key=lambda project: project.get("createdAt"),
                reverse=True,
            )
        else:
            raise PermissionException("Project access denied.")

        for project in projects:
            self._serialize_project(project)
            await self._with_progress(project)

        logger_project.info(
            f"Fetched {len(projects)} projects"
        )

        return projects

    async def get_project_by_id(
        self,
        project_id: str,
        current_user: dict,
    ) -> dict:
        """Return a project by ID."""

        project = await self.project_repo.find_by_id(
            project_id
        )

        if not project:
            raise ResourceNotFoundException(
                "Project"
            )

        await self.ensure_project_access(project, current_user)
        self._serialize_project(project)
        await self._with_progress(project)

        return project

    async def assign_admin(
        self,
        project_id: str,
        admin_id: str,
        current_user: dict | None = None,
    ) -> bool:
        """Assign an admin to a project."""

        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")
        if str(project.get("assignedAdmin")) == str(admin_id):
            raise ValidationException("Project is already assigned to this admin.")

        previous_assignee = project.get("assignedAdmin")
        admin = await self.user_repo.find_by_id(admin_id)
        if not admin:
            raise ResourceNotFoundException("User")
        if not admin.get("isActive", True):
            raise ValidationException("Cannot assign an inactive user.")
        if admin.get("role") not in {"super_admin", "sub_admin"}:
            raise ValidationException("Project admin must be an admin user.")

        updated = await self.project_repo.update(
            project_id,
            {
                "assignedAdmin": admin_id,
            },
        )

        if not updated:
            raise ValidationException(
                "Unable to assign admin."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"] if current_user else "system",
            user_role=current_user["role"] if current_user else "system",
            action="Project Admin Assigned",
            entity="Project",
            entity_id=project_id,
            details={
                "assignmentType": "admin",
                "previousAssignee": previous_assignee,
                "newAssignee": admin_id,
            },
        )

        logger_project.info(
            f"Admin {admin_id} assigned to project {project_id}"
        )

        return updated

    async def assign_sub_admin(
        self,
        project_id: str,
        sub_admin_id: str,
        current_user: dict | None = None,
    ) -> bool:
        """Assign a sub-admin to a project."""

        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")
        if str(project.get("assignedSubAdmin")) == str(sub_admin_id):
            raise ValidationException("Project is already assigned to this Sub Admin.")

        previous_assignee = project.get("assignedSubAdmin")
        sub_admin = await self.user_repo.find_by_id(sub_admin_id)
        if not sub_admin:
            raise ResourceNotFoundException("User")
        if not sub_admin.get("isActive", True):
            raise ValidationException("Cannot assign an inactive user.")
        if sub_admin.get("role") != "sub_admin":
            raise ValidationException(
                "Project can only be assigned to a Sub Admin."
            )

        updated = await self.project_repo.update(
            project_id,
            {
                "assignedSubAdmin": sub_admin_id,
            },
        )

        if not updated:
            raise ValidationException(
                "Unable to assign sub admin."
            )

        await self.activity_service.log_activity(
            user_id=current_user["id"] if current_user else "system",
            user_role=current_user["role"] if current_user else "system",
            action="Project Sub Admin Assigned",
            entity="Project",
            entity_id=project_id,
            details={
                "assignmentType": "sub_admin",
                "previousAssignee": previous_assignee,
                "newAssignee": sub_admin_id,
            },
        )

        logger_project.info(
            f"Sub Admin {sub_admin_id} assigned to {project_id}"
        )

        return updated

    async def delete_project(
        self,
        project_id: str,
        current_user: dict | None = None,
    ) -> bool:
        """Delete a project."""

        project = await self.project_repo.find_by_id(project_id)
        if not project:
            raise ResourceNotFoundException("Project")

        await self.activity_service.log_activity(
            user_id=current_user["id"] if current_user else "system",
            user_role=current_user["role"] if current_user else "system",
            action="Project Deletion Attempted",
            entity="Project",
            entity_id=project_id,
            details={"status": project.get("status")},
        )

        if await self.requirement_repo.exists_by_project(project_id):
            raise ValidationException(
                "Projects with requirements cannot be deleted."
            )
        if project.get("leadId") and await self.requirement_repo.exists_by_lead(
            str(project["leadId"])
        ):
            raise ValidationException(
                "Projects with requirements cannot be deleted."
            )

        if await self.deliverables_repo.exists_any_by_project(project_id):
            raise ValidationException(
                "Projects with deliverables cannot be deleted."
            )
        if await self.timeline_repo.count_by_project(project_id):
            raise ValidationException(
                "Projects with timeline history cannot be deleted."
            )
        if await self.upload_repo.count_by_project(project_id):
            raise ValidationException(
                "Projects with uploaded files cannot be deleted."
            )
        if await self.discussion_repo.count_by_project(project_id):
            raise ValidationException(
                "Projects with discussion history cannot be deleted."
            )
        if await self.invoice_repo.exists_by_project(project_id):
            raise ValidationException(
                "Projects with invoices cannot be deleted."
            )

        deleted = await self.project_repo.delete(
            project_id
        )

        if not deleted:
            raise ResourceNotFoundException(
                "Project"
            )

        logger_project.info(
            f"Project deleted {project_id}"
        )

        await self.activity_service.log_activity(
            user_id=current_user["id"] if current_user else "system",
            user_role=current_user["role"] if current_user else "system",
            action="Project Deleted",
            entity="Project",
            entity_id=project_id,
        )

        return True
