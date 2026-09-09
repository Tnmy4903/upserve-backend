# 🚀 Upserve Backend

> **Production-oriented backend for a software agency management MVP.**

Upserve is a FastAPI and MongoDB REST API for managing the agency workflow from client and lead intake through requirements, quotations, project execution, collaboration, deliverables, invoicing, and completion.

---

## ✨ Highlights

- FastAPI REST API with Pydantic validation
- MongoDB with Motor and repository-level data access
- JWT authentication with database-backed user validation
- Super Admin, Sub Admin, and Client roles
- CRM leads, assignments, lead history, and client conversion
- Requirement approval and request-changes workflow
- Quotation creation, revision, sending, acceptance, and rejection
- Detailed quotation PDF generation, email attachment, and authorized dashboard download
- Project lifecycle, configurable payment schedules, and derived deliverable progress
- Timeline events and project discussions with replies
- Project file uploads with client-visible/internal visibility
- Invoice PDF generation, email sending, payment confirmation, and cancellation
- Notifications and append-only activity logs
- Blog and portfolio management

---

# 🛠 Tech Stack

| Category | Technology |
|-----------|------------|
| Backend | FastAPI |
| Language | Python |
| Database | MongoDB |
| Async Driver | Motor |
| Authentication | JWT (HS256) |
| Validation | Pydantic |
| Email | Resend |
| PDF | ReportLab |
| Storage | Configurable local filesystem |

---

# 🏗 Architecture

```text
HTTP Request
     │
     ▼
FastAPI Routers
     │
     ▼
Service Layer
     │
     ▼
Repository Layer
     │
     ▼
MongoDB
```

The API layer handles routing and request authentication. Services enforce business rules and authorization. Repositories contain MongoDB queries, indexes, and conditional updates.

---

# 📂 Project Structure

```text
backend/
├── app/
│   ├── api/             # FastAPI routers
│   ├── db/              # Database connection, models, and schemas
│   ├── repositories/    # MongoDB access and indexes
│   ├── services/        # Business workflows
│   ├── config.py        # Environment configuration
│   ├── exceptions.py    # Application exceptions and HTTP mapping
│   ├── logger.py        # Application loggers
│   └── main.py          # Application startup and router registration
├── requirements.txt
└── .env                 # Local environment configuration
```

Indexes are registered during application startup. No automatic data migration is performed.

---

# 🚀 Core Modules

## 🔐 Authentication and Users

- Login and current-user profile
- Client creation and client account validation
- Super Admin-created Sub Admin accounts with generated temporary passwords
- Mandatory password change for generated Sub Admin accounts
- Password change with security-version token invalidation
- Super Admin user activation and deactivation

JWT claims are not the final authority for role or account state. Each authenticated request validates the current database user, role, active state, and security version. Invalid, inactive, missing, deleted, or unsupported-role users are rejected.

Password reset, MFA, OAuth, refresh tokens, and email verification are not implemented.

## 📊 CRM

- Lead creation with normalized searchable email indexing
- Super Admin lead management and assignment
- Sub Admin access limited to assigned leads
- Lead history and status transitions
- Lead conversion to an existing or newly created client account

## 📋 Requirements

- Client requirement creation for valid projects; requirement context is optional for quotations
- Lead/project relationship validation
- Requirement updates with history
- Super Admin approval and request-changes actions
- Client-submitted requirements with Super Admin review; approved requirements protected from ordinary modification
- Optional one-file requirement attachments: PDF, images, office documents, spreadsheets, presentations, text/CSV, and ZIP
- Attachment size and extension validation, UUID-backed storage, replacement cleanup, and authorized downloads
- Super Admin access across requirement detail/lead contexts; Sub Admin access remains assignment-scoped

## 💼 Quotations

- Server-calculated quotation totals
- Draft, sent, viewed, accepted, rejected, revision-requested, and expired statuses
- Client acceptance and rejection
- Rejected quotations remain as history; Admin can create a new quotation for the same lead/project
- Client rejection does not mark the lead Lost; lead closure remains an explicit Admin action
- Detailed PDF generation for email attachments and authorized quotation PDF downloads
- Atomic status transitions for concurrent requests
- Accepted quotation to project creation with retry recovery

## 📁 Projects and Deliverables

Project lifecycle:

```text
pending → in_progress → testing → deployment → delivered → completed
```

Project status transitions are available to authorized Super Admins and Sub Admins and use conditional database updates. Delivered and completed projects require at least one deliverable and all non-cancelled deliverables to be completed. Completion also requires a paid invoice.

Project progress is read-only and derived from current deliverables:

```text
completed non-cancelled deliverables
------------------------------------ × 100
total non-cancelled deliverables
```

Responses include `progressPercentage`, `totalDeliverables`, `completedDeliverables`, and `cancelledDeliverables`. Progress is `null` when there are no non-cancelled deliverables and is not stored as a separate manual value.

## 💬 Discussions and Timeline

- Project-authorized discussions and replies
- Sender identity and role derived from authentication
- Soft-deleted messages and protected system initialization messages
- Deterministic message ordering and pagination
- Project timeline events for lifecycle changes and deliverable completion
- Idempotent initialization and lifecycle-event recovery

Legacy string/ObjectId project references remain readable where supported.

## 📦 Files

- Project-aware uploads and listings
- Client ownership and Sub Admin project authorization
- Client-visible/internal upload flag
- Configurable local storage root
- File size, empty-file, extension, filename, and collision-safe UUID validation
- Authorized upload-ID downloads
- Legacy Super Admin filename download route
- Metadata and physical-file cleanup/recovery handling

The system does not provide cloud storage, antivirus scanning, deep MIME inspection, or distributed file storage.

## 📄 Invoices and Payments

Invoice lifecycle:

```text
generated → sent → paid
generated/sent → cancelled
```

Paid and cancelled invoices are terminal. Projects use exactly three payment stages: Advance, Milestone, and Final. Each project can configure positive stage percentages totaling 100%; projects without a stored schedule retain a legacy-compatible 40/30/30 default. Advance must be paid before Milestone, and Milestone plus project delivery are required before Final. Invoice amounts are calculated server-side from the accepted quotation value. Payment confirmation is Super Admin-only, atomic, and stores payment amount, reference, method, timestamp, and actor.

Schedule configuration is restricted to authorized project editors and is locked after an invoice is generated. Existing invoice amounts are never recalculated when project data changes.

Invoice sending uses a persistent send claim. A stale uncertain claim can be manually reconciled by an active Super Admin through:

```text
POST /api/invoices/{invoice_id}/reconcile-send
```

This releases the stale claim for controlled review; it does not automatically resend email or guarantee exactly-once external delivery.

---

# 🔐 Role and Access Summary

| Capability | Super Admin | Sub Admin | Client |
|------------|:-----------:|:---------:|:------:|
| Manage users | ✅ | ❌ | ❌ |
| Manage all CRM data | ✅ | Assigned leads only | ❌ |
| Create/manage quotations | ✅ | ❌ | ❌ |
| Approve requirements | ✅ | ❌ | Read-only where authorized |
| Change project status/budget | ✅ | ✅ | ❌ |
| Access assigned projects | ✅ | ✅ | Own projects only |
| Upload files | ✅ | Authorized projects | Own projects |
| Send/confirm/cancel invoices | ✅ | ❌ | ❌ |
| Configure payment schedule | ✅ | ✅ | ❌ |
| View own invoices | ✅ | Authorized project scope | Own projects |
| Manage blog and portfolio content | ✅ | ❌ | ❌ |
| View activity logs | ✅ | Restricted by API policy | ❌ |

Role checks are combined with database-backed ownership, lead assignment, or project assignment. A role alone does not grant access to another client's project.

---

# 📊 Main Business Workflow

```text
Client account / contact intake
          │
          ▼
Lead creation and assignment
          │
          ▼
Requirement creation and approval
          │
          ▼
Quotation creation and sending
          │
          ▼
Client acceptance
          │
          ▼
Project creation and initialization
          │
          ▼
Deliverables, timeline, discussions, and files
          │
          ▼
Project delivered
          │
          ▼
Invoice generated and sent
          │
          ▼
Payment confirmed
          │
          ▼
Project completed
```

---

# 🗄 Database Collections

```text
users, leads, requirements, quotations, projects, deliverables,
timeline_events, discussions, uploads, invoices, notifications,
activity_logs, contact_forms, blogs, portfolio
```

Unique and supporting indexes are registered for user/lead email, lead and requirement relationships, active quotation/project relationships, deliverables, discussions, timeline events, uploads, invoices, notifications, and activity ordering. Rejected quotation history may coexist with a new quotation for the same lead/project.

Legacy records remain readable through targeted string/ObjectId-compatible lookups. The application does not automatically migrate or delete legacy data.

---

# ⚙ Environment Variables

```env
MONGO_URI=<your_mongodb_uri>
DB_NAME=<database_name>
JWT_SECRET=<jwt_secret>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
RESEND_API_KEY=<resend_api_key>
RESEND_FROM_EMAIL=onboarding@resend.dev
ALERT_RECEIVER_EMAIL=<email>
SUPER_ADMIN_NAME=<name>
SUPER_ADMIN_EMAIL=<email>
SUPER_ADMIN_PASSWORD=<password>
UPLOAD_STORAGE_ROOT=app/uploads
MAX_UPLOAD_FILE_SIZE=10485760
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

Do not commit secrets. Required configuration is validated during startup.

---

# 🚀 Running Locally

```bash
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The backend runs at `http://localhost:8000`. Swagger UI is available at `http://localhost:8000/docs`.

---

# 🛡 Error Handling and Security

- Centralized application exception-to-HTTP mapping
- Controlled validation, authorization, authentication, and not-found errors
- Generic unexpected errors return a non-diagnostic 500 response
- Unexpected failures are logged server-side
- Malformed IDs are converted to controlled validation errors
- Password hashes, raw filesystem paths, and internal database details are not exposed in normal API responses
- Activity logging is append-only and best-effort; notification failures do not fail core business operations

---

# ⚠️ Current Limitations

- Email delivery is an external side effect and cannot be guaranteed exactly once.
- Invoice send reconciliation is manual and intentionally does not infer whether the prior email was delivered.
- Files use local filesystem storage and require a shared/persistent storage strategy for multi-instance deployment.
- Payment handling supports exact confirmation for the current invoice stage, not a full accounting or gateway system.
- No background job, push notification, WebSocket, MFA, password-reset, or cloud-storage subsystem exists.

---

**Upserve** — software agency workflow management with a focused production MVP backend.
