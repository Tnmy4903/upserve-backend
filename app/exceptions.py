"""
Production-ready exception handling for FastAPI
"""
import logging
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


class AppException(Exception):
    """Base exception for application"""
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code: str = "INTERNAL_ERROR"
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(self.message)


class AuthenticationException(AppException):
    """Authentication failed"""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status.HTTP_401_UNAUTHORIZED, "AUTH_ERROR")


class AuthorizationException(AppException):
    """User not authorized for this action"""
    def __init__(self, message: str = "Not authorized"):
        super().__init__(message, status.HTTP_403_FORBIDDEN, "FORBIDDEN")


class ResourceNotFoundException(AppException):
    """Resource not found"""
    def __init__(self, resource: str = "Resource"):
        super().__init__(f"{resource} not found", status.HTTP_404_NOT_FOUND, "NOT_FOUND")


class ValidationException(AppException):
    """Validation error"""
    def __init__(self, message: str):
        super().__init__(message, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR")


class DuplicateException(AppException):
    """Resource already exists"""
    def __init__(self, resource: str = "Resource"):
        super().__init__(f"{resource} already exists", status.HTTP_400_BAD_REQUEST, "DUPLICATE")


class PermissionException(AppException):
    """User lacks required permission"""

    def __init__(
        self,
        permission: str = None,
        message: str = None
    ):

        if message:
            msg = message
        else:
            msg = f"User lacks {permission} permission"

        super().__init__(
            msg,
            status.HTTP_403_FORBIDDEN,
            "PERMISSION_DENIED"
        )


def exception_to_http(exc: Exception) -> HTTPException:
    """
    Convert application exceptions to HTTPException.
    """

    if isinstance(exc, AppException):
        logger.warning(
            f"{exc.error_code}: {exc.message}"
        )

        return HTTPException(
            status_code=exc.status_code, detail=exc.message
        )

    logger.exception(
        "Unhandled exception occurred."
    )

    return HTTPException(
        status_code=500, detail="Internal Server Error"
    )
