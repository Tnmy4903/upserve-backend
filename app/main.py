from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio
import logging
from app.db.database import client
from app.config import CORS_ORIGINS
from app.services.auth_service import AuthService
from app.repositories.user_repo import UserRepository
from app.repositories.lead_repo import LeadRepository
from app.repositories.requirement_repo import RequirementRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.deliverables_repo import DeliverablesRepository
from app.repositories.discussion_repo import DiscussionRepository
from app.repositories.timeline_repo import TimelineRepository
from app.repositories.upload_repo import UploadRepository
from app.repositories.invoice_repo import InvoiceRepository
from app.repositories.notification_repo import NotificationRepository
from app.repositories.activitylog_repo import ActivityLogRepository
from app.repositories.content_media_repo import ContentMediaRepository
from app.repositories.quotation_repo import QuotationRepository
from app.exceptions import AppException

from app.api import (
    auth,
    admin,
    blogs,
    projects,
    invoices,
    uploads,
    contact,
    crm,
    requirements,
    quotations,
    timeline,
    discussions,
    deliverables,
    activity_logs,
    notifications,
    portfolio,
    content_media,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown events.
    """

    await client.admin.command("ping")
    print("✅ Connected to MongoDB")

    await asyncio.gather(
        UserRepository().ensure_indexes(),
        LeadRepository().ensure_indexes(),
        RequirementRepository().ensure_indexes(),
        QuotationRepository().ensure_indexes(),
        ProjectRepository().ensure_indexes(),
        DeliverablesRepository().ensure_indexes(),
        DiscussionRepository().ensure_indexes(),
        TimelineRepository().ensure_indexes(),
        UploadRepository().ensure_indexes(),
        InvoiceRepository().ensure_indexes(),
        NotificationRepository().ensure_indexes(),
        ActivityLogRepository().ensure_indexes(),
        ContentMediaRepository().ensure_indexes(),
    )

    auth_service = AuthService()
    await auth_service.seed_super_admin()

    yield

    client.close()
    print("MongoDB connection closed.")

app = FastAPI(
    title="Upserve Backend API",
    description="Backend API for Upserve agency workflow, project management, and portfolio.",
    version="1.0.0",
    lifespan=lifespan
)

# Compress larger JSON responses while leaving small responses untouched.
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)


@app.exception_handler(AppException)
async def handle_app_exception(request: Request, exc: AppException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception):
    logging.getLogger(__name__).exception("Unhandled application exception", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

# -------------------------------------------------------
# CORS
# -------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------
# Authentication
# -------------------------------------------------------
app.include_router(
    auth.auth_router,
    prefix="/api/auth",
    tags=["Authentication"]
)

# -------------------------------------------------------
# Admin
# -------------------------------------------------------
app.include_router(
    admin.admin_router,
    prefix="/api/admin",
    tags=["Admin"]
)

# -------------------------------------------------------
# Blog
# -------------------------------------------------------
app.include_router(
    blogs.blog_router,
    prefix="/api/blogs",
    tags=["Blogs"]
)

# -------------------------------------------------------
# Projects
# -------------------------------------------------------
app.include_router(
    projects.project_router,
    prefix="/api/projects",
    tags=["Projects"]
)

# -------------------------------------------------------
# Invoices
# -------------------------------------------------------
app.include_router(
    invoices.invoice_router,
    prefix="/api/invoices",
    tags=["Invoices"]
)

# -------------------------------------------------------
# Uploads
# -------------------------------------------------------
app.include_router(
    uploads.upload_router,
    prefix="/api/uploads",
    tags=["Uploads"]
)

app.include_router(
    content_media.content_media_router,
    prefix="/api/content",
    tags=["Content Media"]
)

# -------------------------------------------------------
# Public APIs
# -------------------------------------------------------
app.include_router(
    contact.contact_router,
    prefix="/api/public",
    tags=["Public"]
)

# -------------------------------------------------------
# CRM
# -------------------------------------------------------
app.include_router(
    crm.lead_router,
    prefix="/api",
    tags=["CRM"]
)

app.include_router(
    requirements.requirement_router,
    prefix="/api",
    tags=["Requirements"]
)

app.include_router(
    quotations.quotation_router,
    prefix="/api",
    tags=["Quotations"]
)

app.include_router(
    timeline.timeline_router,
    prefix="/api",
    tags=["Timeline"]
)

app.include_router(
    discussions.discussion_router,
    prefix="/api",
    tags=["Discussions"]
)

app.include_router(
    deliverables.deliverables_router,
    prefix="/api",
    tags=["Deliverables"]
)

app.include_router(
    activity_logs.activity_router,
    prefix="/api",
    tags=["Activity Logs"]
)

app.include_router(
    notifications.notification_router,
    prefix="/api",
    tags=["Notifications"]
)

# -------------------------------------------------------
# Portfolio & CMS
# -------------------------------------------------------
app.include_router(
    portfolio.portfolio_router,
    prefix="/api",
    tags=["Portfolio"]
)


# -------------------------------------------------------
# Root Endpoint
# -------------------------------------------------------
@app.get("/", tags=["Health"])
async def root():
    return {
        "application": "Upserve Backend API",
        "version": "1.0.0",
        "status": "running"
    }


# -------------------------------------------------------
# Health Check
# -------------------------------------------------------
@app.get("/health", tags=["Health"])
async def health():
    return {
        "application": app.title,
        "version": app.version,
        "status": "healthy"
    }
