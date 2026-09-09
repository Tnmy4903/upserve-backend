"""Shared FastAPI authorization dependencies."""

from collections.abc import Callable

from fastapi import Depends

from app.api.auth import get_current_user
from app.exceptions import AuthorizationException


def require_roles(*roles: str, message: str | None = None) -> Callable:
    """Build a dependency that permits only the supplied database roles."""

    if not roles:
        raise ValueError("At least one role is required.")

    async def dependency(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in roles:
            raise AuthorizationException(message or "Insufficient role permissions.")
        return current_user

    return dependency
