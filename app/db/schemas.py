from pydantic import BaseModel, EmailStr, Field, HttpUrl, root_validator
from typing import Any, Optional, List, Dict, Literal
from datetime import datetime, date
from enum import Enum

# ───────────────────────────────
# 📦 Auth/User Schemas
# ───────────────────────────────

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str = Field(min_length=8)

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    SUB_ADMIN = "sub_admin"
    CLIENT = "client"


class AdminCreate(BaseModel):
    email: EmailStr
    name: str
    phone: Optional[str] = Field(default=None, max_length=20)


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: UserRole  # "super_admin" | "sub_admin" | "client"
    phone: Optional[str] = None
    mustChangePassword: bool = False
class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserOut

class SubAdminCreateResponse(BaseModel):
    user: UserOut
    temporary_password: str


class PasswordChange(BaseModel):
    currentPassword: str = Field(min_length=1)
    newPassword: str = Field(min_length=8)


class AccountStatusUpdate(BaseModel):
    isActive: bool

class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    phone: Optional[str] = None

# ───────────────────────────────
# 📝 Blog Schemas
# ───────────────────────────────

class BlogCreate(BaseModel):
    title: str
    slug: str
    content: str
    thumbnail: Optional[HttpUrl]

class BlogOut(BlogCreate):
    id: str
    views: int
    createdAt: datetime
    updatedAt: datetime

# ───────────────────────────────
# 📁 Project Schemas
# ───────────────────────────────

class ProjectStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    TESTING = "testing"
    DEPLOYMENT = "deployment"
    DELIVERED = "delivered"
    COMPLETED = "completed"

class ProjectCreate(BaseModel):
    title: str
    description: str
    deadline: Optional[date] = None
    budget: Optional[float] = Field(
        default=None,
        ge=0
    )

class ProjectInvoiceStage(str, Enum):
    ADVANCE = "advance"
    MILESTONE = "milestone"
    FINAL = "final"

class PaymentSchedule(BaseModel):
    advancePercentage: float = Field(ge=0)
    milestonePercentage: float = Field(ge=0)
    finalPercentage: float = Field(ge=0)

    @root_validator(skip_on_failure=True)
    def percentages_must_total_100(cls, values):
        total = sum(values.get(field, 0) for field in ("advancePercentage", "milestonePercentage", "finalPercentage"))
        if abs(total - 100) > 1e-9:
            raise ValueError("Payment schedule percentages must total exactly 100%.")
        return values

class ProjectInvoiceSummary(BaseModel):
    stage: ProjectInvoiceStage
    percentage: float
    amount: float
    invoiceId: Optional[str] = None
    status: str
    isPaid: bool = False

class ProjectOut(ProjectCreate):
    id: str
    userId: str

    quotationId: Optional[str] = None
    leadId: Optional[str] = None

    assignedAdmin: Optional[str] = None
    assignedSubAdmin: Optional[str] = None

    status: ProjectStatus

    progressPercentage: Optional[float] = None
    totalDeliverables: int = 0
    completedDeliverables: int = 0
    cancelledDeliverables: int = 0
    totalProjectValue: float = 0
    totalPaid: float = 0
    outstandingAmount: float = 0
    invoiceSchedule: List[ProjectInvoiceSummary] = Field(default_factory=list)
    paymentSchedule: PaymentSchedule = Field(default_factory=lambda: PaymentSchedule(
        advancePercentage=40, milestonePercentage=30, finalPercentage=30
    ))

    createdAt: datetime
    updatedAt: datetime

class StatusUpdate(BaseModel):
    status: ProjectStatus


class BudgetUpdate(BaseModel):
    budget: float = Field(gt=0)

class PaymentScheduleUpdate(PaymentSchedule):
    pass

class InvoiceGenerate(BaseModel):
    dueDate: Optional[date] = None
    stage: Optional[ProjectInvoiceStage] = None

# ───────────────────────────────
# 📎 File Upload Schema
# ───────────────────────────────

class FileUploadOut(BaseModel):
    id: str

    userId: str
    projectId: str

    fileName: str
    storedFileName: str

    fileSize: int
    contentType: Optional[str] = None
    extension: str
    uploaderRole: Optional[str] = None
    clientVisible: bool = True

    uploadedAt: datetime

# ───────────────────────────────
# 🧾 Invoice Enums
# ───────────────────────────────

class InvoiceStatus(str, Enum):
    GENERATED = "generated"
    SENT = "sent"
    PAID = "paid"
    CANCELLED = "cancelled"

class InvoiceStage(str, Enum):
    ADVANCE = "advance"
    MILESTONE = "milestone"
    FINAL = "final"


# ───────────────────────────────
# 🧾 Invoice Schemas
# ───────────────────────────────

class InvoiceOut(BaseModel):
    id: str

    # Relationships
    projectId: str
    clientId: str
    quotationId: Optional[str] = None
    leadId: Optional[str] = None

    # Invoice Details
    invoiceNumber: str
    stage: InvoiceStage = InvoiceStage.FINAL
    percentage: float = 100
    title: str
    description: Optional[str] = None

    # Financial
    amount: float = Field(gt=0)
    currency: str

    # Payment
    status: InvoiceStatus
    isPaid: bool
    paymentAmount: Optional[float] = None
    paymentReference: Optional[str] = None
    paymentMethod: Optional[str] = None
    paidAt: Optional[datetime] = None
    paidBy: Optional[str] = None

    # File
    fileUrl: Optional[str] = None
    downloadUrl: Optional[str] = None

    # Dates
    generatedOn: datetime
    dueDate: Optional[date] = None
    paidOn: Optional[datetime] = None

    createdAt: datetime
    updatedAt: datetime


class PaymentUpdate(BaseModel):
    isPaid: bool = True
    paymentAmount: Optional[float] = Field(default=None, gt=0)
    paymentReference: Optional[str] = None
    paymentMethod: Optional[str] = None


class ActionMessage(BaseModel):
    message: str


class InvoiceSendResponse(ActionMessage):
    email: EmailStr

# ───────────────────────────────
# 📬 Contact Form Schemas
# ───────────────────────────────

class ContactFormCreate(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=100
    )

    email: EmailStr

    phone: Optional[str] = Field(default=None, max_length=20)

    companyName: Optional[str] = Field(default=None, max_length=200)

    business: Optional[str] = Field(default=None, min_length=2, max_length=150)

    message: str = Field(
        min_length=10,
        max_length=5000
    )


class ContactFormOut(ContactFormCreate):
    id: str

    createdAt: datetime
    updatedAt: datetime

# ───────────────────────────────
# 💼 CRM/Lead Schemas
# ───────────────────────────────

class LeadStage(str, Enum):
    NEW = "New"
    CONTACTED = "Contacted"
    QUALIFIED = "Qualified"
    PROPOSAL_SENT = "Proposal Sent"
    NEGOTIATION = "Negotiation"
    WON = "Won"
    LOST = "Lost"

class LeadCreate(BaseModel):
    email: EmailStr

    companyName: Optional[str] = Field(
        default=None,
        max_length=200
    )

    contactPerson: str = Field(
        min_length=2,
        max_length=100
    )

    phone: Optional[str] = Field(
        default=None,
        max_length=20
    )

    business: str = Field(
        min_length=2,
        max_length=150
    )

    leadSource: Optional[str] = Field(
        default=None,
        max_length=100
    )

    notes: Optional[str] = Field(
        default=None,
        max_length=5000
    )

class LeadUpdate(BaseModel):
    companyName: Optional[str] = None
    contactPerson: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    business: Optional[str] = None
    leadSource: Optional[str] = None
    stage: Optional[LeadStage]
    notes: Optional[str] = None

class LeadConvert(BaseModel):
    password: Optional[str] = None

class LeadOut(LeadCreate):
    id: str
    stage: LeadStage
    assignedTo: Optional[str] = None
    assignedToIds: list[str] = Field(default_factory=list)
    clientId: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime

class LeadHistoryEvent(BaseModel):
    action: str
    field: Optional[str] = None
    oldValue: Optional[str] = None
    newValue: Optional[str] = None
    message: Optional[str] = None
    changedBy: str
    timestamp: datetime

# ───────────────────────────────
# 📋 Requirement Schemas
# ───────────────────────────────

class RequirementStatus(str, Enum):
    PENDING = "PENDING"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"

class RequirementCreate(BaseModel):
    leadId: Optional[str] = None
    projectId: Optional[str] = None
    businessName: str = Field(
        min_length=2,
        max_length=200
    )

    businessType: str = Field(
        min_length=2,
        max_length=100
    )

    targetAudience: str = Field(
        min_length=2,
        max_length=300
    )

    goals: str = Field(
        min_length=5,
        max_length=5000
    )

    requiredFeatures: List[str] = Field(
        min_length=1
    )

    preferredTech: List[str] = Field(
        min_length=1
    )

    additionalNotes: Optional[str] = Field(
        default=None,
        max_length=5000
    )

class RequirementUpdate(BaseModel):
    businessName: Optional[str] = None
    businessType: Optional[str] = None
    targetAudience: Optional[str] = None
    goals: Optional[str] = None
    requiredFeatures: Optional[List[str]] = None
    preferredTech: Optional[List[str]] = None
    referenceWebsites: Optional[List[str]] = None
    logoUrl: Optional[str] = None
    deadline: Optional[date] = None
    budgetRange: Optional[str] = None
    additionalNotes: Optional[str] = None

class RequirementAttachmentOut(BaseModel):
    fileName: str
    contentType: str
    fileSize: int
    uploadedAt: datetime

class RequirementOut(RequirementCreate):
    id: str
    status: RequirementStatus
    approvedBy: Optional[str] = None
    approvedAt: Optional[datetime] = None
    remarks: Optional[str] = None
    lastUpdatedBy: Optional[str] = None
    lastUpdatedAt: Optional[datetime] = None
    referenceWebsites: Optional[List[str]] = None
    logoUrl: Optional[str] = None
    deadline: Optional[date] = None
    budgetRange: Optional[str] = None
    attachment: Optional[RequirementAttachmentOut] = None
    history: List[dict] = Field(default_factory=list)
    createdAt: datetime
    updatedAt: datetime

class RequirementApprovalRequest(BaseModel):
    remarks: Optional[str] = None

# ───────────────────────────────
# 💰 Quotation Schemas
# ───────────────────────────────

class QuotationStatus(str, Enum):
    DRAFT = "Draft"
    SENT = "Sent"
    VIEWED = "Viewed"
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    REVISION_REQUESTED = "Revision Requested"
    EXPIRED = "Expired"

class QuotationItemCreate(BaseModel):
    description: str
    quantity: float = Field(
        default=1.0,
        gt=0,
    )
    unitPrice: float = Field(
        ge=0,
    )
    total: float

class QuotationCreate(BaseModel):
    clientId: str
    leadId: Optional[str] = None
    projectId: Optional[str] = None
    services: List[str]
    items: List[QuotationItemCreate]
    timeline: str
    validity: int
    terms: str
    notes: Optional[str] = None

class QuotationUpdate(BaseModel):
    services: Optional[List[str]] = None
    items: Optional[List[QuotationItemCreate]] = None
    timeline: Optional[str] = None
    validity: Optional[int] = None
    terms: Optional[str] = None
    notes: Optional[str] = None
    revisionCount: Optional[int] = None
    lastRevisedBy: Optional[str] = None
    lastRevisedAt: Optional[datetime] = None

class QuotationOut(QuotationCreate):
    id: str
    clientName: Optional[str] = None
    projectTitle: Optional[str] = None
    quotationNumber: str
    status: QuotationStatus
    totalAmount: float
    createdAt: datetime
    updatedAt: datetime
    revisionCount: int
    lastRevisedBy: Optional[str] = None
    lastRevisedAt: Optional[datetime] = None


class QuotationAcceptanceOut(BaseModel):
    quotation: QuotationOut
    project: Dict[str, Any]

# ───────────────────────────────
# 📅 Timeline Event Schemas
# ───────────────────────────────

class TimelineEventCreate(BaseModel):
    title: str = Field(
        min_length=2,
        max_length=200
    )

    description: Optional[str] = Field(
        default=None,
        max_length=2000
    )
    clientVisible: bool = False

class TimelineEventOut(TimelineEventCreate):
    id: str
    projectId: str
    createdBy: str
    createdAt: datetime
    eventType: Optional[str] = None
    isSystemEvent: bool = False
    isDeleted: bool = False
    deletedAt: Optional[datetime] = None
    deletedBy: Optional[str] = None

# ───────────────────────────────
# 💬 Discussion Schemas
# ───────────────────────────────

class DiscussionMessageCreate(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=5000
    )

    attachments: Optional[List[str]] = None

class DiscussionReplyCreate(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=5000
    )
    attachments: Optional[List[str]] = None

class DiscussionReplyOut(BaseModel):
    id: str
    messageId: str
    authorId: str
    authorName: str
    authorRole: Optional[str] = None
    message: str
    attachments: List[str] = Field(default_factory=list)
    edited: bool = False
    createdAt: datetime
    updatedAt: datetime

# ───────────────────────────────
# 📦 Deliverables Schemas
# ───────────────────────────────

class DeliverableStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class DeliverablesCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    dueDate: Optional[date] = None
    clientVisible: bool = True
    deploymentUrl: Optional[str] = None
    sourceCode: Optional[str] = None
    documentation: Optional[str] = None
    credentials: Optional[str] = None
    apkUrl: Optional[str] = None
    websiteUrl: Optional[str] = None
    repositoryLink: Optional[str] = None
    notes: Optional[str] = None

class DeliverablesUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    dueDate: Optional[date] = None
    clientVisible: Optional[bool] = None
    deploymentUrl: Optional[str] = None
    sourceCode: Optional[str] = None
    documentation: Optional[str] = None
    credentials: Optional[str] = None
    apkUrl: Optional[str] = None
    websiteUrl: Optional[str] = None
    repositoryLink: Optional[str] = None
    notes: Optional[str] = None

class DeliverablesOut(DeliverablesCreate):
    # Defaults keep older aggregate records readable during migration.
    title: str = "Project Deliverables"
    clientVisible: bool = True
    id: str
    projectId: str
    status: DeliverableStatus = DeliverableStatus.PENDING
    createdBy: Optional[str] = None
    updatedBy: Optional[str] = None
    completedAt: Optional[datetime] = None
    completedBy: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime
    accountStatus: Optional[Literal["created", "existing", "already_linked"]] = None
    emailStatus: Optional[Literal["sent", "failed", "not_attempted"]] = None
    emailMessage: Optional[str] = None

class DiscussionMessageOut(BaseModel):
    id: str
    projectId: str
    authorId: str
    authorName: str
    authorRole: Optional[str] = None
    message: str
    attachments: List[str] = Field(default_factory=list)
    replies: List[DiscussionReplyOut] = Field(default_factory=list)
    edited: bool = False
    seen: bool = False
    isDeleted: bool = False
    isSystemMessage: bool = False
    deletedAt: Optional[datetime] = None
    deletedBy: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime

class DeliverableStatusUpdate(BaseModel):
    status: DeliverableStatus

# ───────────────────────────────
# 📊 Activity Log Schemas
# ───────────────────────────────

class ActivityLogCreate(BaseModel):
    userId: str
    userRole: str
    actorName: Optional[str] = None
    action: str
    entity: str
    entityId: str
    details: Dict[str, Any] = Field(default_factory=dict)

class ActivityLogOut(ActivityLogCreate):
    id: str
    timestamp: datetime

# ───────────────────────────────
# 🔔 Notification Schemas
# ───────────────────────────────

class NotificationOut(BaseModel):
    id: str
    userId: str
    type: str
    title: str
    message: str
    entityId: Optional[str] = None
    entityType: Optional[str] = None
    eventKey: Optional[str] = None
    read: bool = False
    createdAt: datetime

# ───────────────────────────────
# 🖼️ Portfolio CMS Schemas
# ───────────────────────────────

class PortfolioItemCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)

    slug: str = Field(
        min_length=2,
        max_length=200,
        pattern=r"^[a-z0-9-]+$"
    )

    category: str = Field(
        min_length=2,
        max_length=100
    )

    description: str = Field(
        min_length=10,
        max_length=5000
    )
    techStack: List[str]
    websiteUrl: Optional[str] = None
    githubUrl: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    featured: bool = False
    displayOrder: int = 0

class PortfolioItemUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    techStack: Optional[List[str]] = None
    websiteUrl: Optional[str] = None
    githubUrl: Optional[str] = None
    images: Optional[List[str]] = None
    featured: Optional[bool] = None
    displayOrder: Optional[int] = None
    published: Optional[bool] = None

class PortfolioItemOut(PortfolioItemCreate):
    id: str
    published: bool = True
    createdAt: datetime
    updatedAt: datetime
