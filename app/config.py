import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
JWT_SECRET = os.getenv("JWT_SECRET")

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
SUPPORTED_JWT_ALGORITHMS = {"HS256"}

try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 1440)
    )
except ValueError:
    raise RuntimeError(
        "ACCESS_TOKEN_EXPIRE_MINUTES must be an integer."
    )

DB_NAME = os.getenv("DB_NAME", "").strip()

UPLOAD_STORAGE_ROOT = os.getenv(
    "UPLOAD_STORAGE_ROOT",
    "app/uploads",
)

try:
    MAX_UPLOAD_FILE_SIZE = int(
        os.getenv("MAX_UPLOAD_FILE_SIZE", 10 * 1024 * 1024)
    )
except ValueError:
    raise RuntimeError(
        "MAX_UPLOAD_FILE_SIZE must be an integer."
    )

ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".jpg", ".jpeg", ".png", ".webp", ".zip",
}

_raw_cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173",
)
CORS_ORIGINS = [
    origin.strip()
    for origin in _raw_cors_origins.split(",")
    if origin.strip()
]

ALERT_RECEIVER_EMAIL = os.getenv("ALERT_RECEIVER_EMAIL")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv(
    "RESEND_FROM_EMAIL",
    "hello@upserve.in",
).strip()

# Validate required environment variables
if not MONGO_URI:
    raise RuntimeError(
        "MONGO_URI environment variable is missing."
    )

if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET environment variable is missing."
    )

if not DB_NAME:
    raise RuntimeError(
        "DB_NAME environment variable is missing."
    )

if not CORS_ORIGINS or "*" in CORS_ORIGINS:
    raise RuntimeError(
        "CORS_ORIGINS must contain one or more explicit origins and cannot contain '*'."
    )

# Validate JWT algorithm
if JWT_ALGORITHM not in SUPPORTED_JWT_ALGORITHMS:
    raise RuntimeError(
        f"Unsupported JWT algorithm: {JWT_ALGORITHM}"
    )

SUPER_ADMIN_NAME = os.getenv("SUPER_ADMIN_NAME")
SUPER_ADMIN_EMAIL = os.getenv("SUPER_ADMIN_EMAIL")
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD")

if not SUPER_ADMIN_NAME:
    raise RuntimeError("SUPER_ADMIN_NAME environment variable is missing.")

if not SUPER_ADMIN_EMAIL:
    raise RuntimeError("SUPER_ADMIN_EMAIL environment variable is missing.")

if not SUPER_ADMIN_PASSWORD:
    raise RuntimeError("SUPER_ADMIN_PASSWORD environment variable is missing.")
