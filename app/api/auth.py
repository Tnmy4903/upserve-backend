"""
Authentication API
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_SECRET,
)
from app.db.schemas import (
    AdminCreate,
    AccountStatusUpdate,
    LoginResponse,
    PasswordChange,
    SubAdminCreateResponse,
    UserCreate,
    UserLogin,
    UserOut,
    ProfileUpdate,
)
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    ValidationException,
    exception_to_http,
)
from app.logger import logger_auth
from app.services.auth_service import AuthService


auth_router = APIRouter()

security = HTTPBearer(auto_error=False)

auth_service = AuthService()


# ------------------------------------------------------------------
# JWT Token Creation
# ------------------------------------------------------------------

def create_access_token(
    data: dict,
) -> str:
    """Create a JWT access token."""

    to_encode = data.copy()

    now = datetime.now(
        timezone.utc
    )

    expire = now + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    to_encode.update(
        {
            "sub": data["id"],
            "type": "access",
            "exp": expire,
            "iat": now,
        }
    )

    return jwt.encode(
        to_encode,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


# ------------------------------------------------------------------
# Login
# ------------------------------------------------------------------

@auth_router.post(
    "/login",
    response_model=LoginResponse,
)
async def login(
    user: UserLogin,
):
    """Authenticate a user."""

    try:
        token_data = (
            await auth_service.verify_credentials(
                user.email,
                user.password,
            )
        )

        token = create_access_token(
            token_data
        )

        logger_auth.info(
            f"Successful login for role {token_data['role']}"
        )

        return {
            "access_token": token,
            "token_type": "bearer",
            "user": token_data,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Authentication Dependency
# ------------------------------------------------------------------

async def _resolve_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(
        security
    ),
    allow_must_change: bool = False,
) -> dict:
    """Return the currently authenticated user."""

    if credentials is None:
        raise exception_to_http(
            AuthenticationException(
                "Authentication credentials were not provided."
            )
        )

    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[
                JWT_ALGORITHM,
            ],
        )

        user_id = payload.get("sub")

        if not user_id:
            raise AuthenticationException(
                "Invalid token"
            )

        if payload.get("type") != "access":
            raise AuthenticationException(
                "Invalid token type."
            )

        try:
            user = await auth_service.user_repo.find_by_id(str(user_id))
        except ValidationException as exc:
            raise AuthenticationException("Token is invalid.") from exc

        if (
            not user
            or not user.get("isActive", True)
            or user.get("role") not in {"super_admin", "sub_admin", "client"}
        ):
            raise AuthenticationException("User account is not active.")

        try:
            if int(payload.get("securityVersion", 0)) != int(
                user.get("securityVersion", 0)
            ):
                raise AuthenticationException("Token is no longer valid.")
        except (TypeError, ValueError):
            raise AuthenticationException("Token is invalid.")

        must_change = user.get("mustChangePassword", False)
        if must_change and not allow_must_change:
            raise AuthorizationException(
                "Password change is required before accessing the application."
            )

        return {
            "id": str(user["_id"]),
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "mustChangePassword": must_change,
        }

    except AuthenticationException as exc:
        raise exception_to_http(exc)

    except AuthorizationException as exc:
        raise exception_to_http(exc)

    except (JWTError, KeyError, TypeError, ValueError) as exc:
        logger_auth.error(
            f"JWT validation failed: {exc}"
        )

        raise exception_to_http(
            AuthenticationException(
                "Token is invalid or expired"
            )
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Resolve an active, database-backed authenticated user."""

    return await _resolve_current_user(credentials, allow_must_change=False)


async def get_current_user_for_password_change(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Allow forced-password users to reach password change only."""

    return await _resolve_current_user(credentials, allow_must_change=True)


# ------------------------------------------------------------------
# Current User
# ------------------------------------------------------------------

@auth_router.get(
    "/me",
    response_model=UserOut,
)
async def get_me(
    current_user: dict = Depends(
        get_current_user
    ),
):
    """Return the current user's profile."""

    try:
        return await auth_service.get_current_user_profile(
            current_user["id"]
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)

@auth_router.patch(
    "/me",
    response_model=UserOut,
)
async def update_me(
    payload: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update editable fields on the authenticated user's own profile."""
    try:
        return await auth_service.update_profile(
            current_user["id"],
            payload.dict(exclude_unset=True),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@auth_router.get(
    "/sub-admins/lookup",
    response_model=UserOut,
)
async def lookup_sub_admin(
    email: str = Query(..., min_length=3),
    current_user: dict = Depends(get_current_user),
):
    """Resolve an active Sub Admin email for lead assignment."""

    try:
        if current_user.get("role") != "super_admin":
            raise AuthorizationException(
                "Only Super Admins can look up Sub Admins."
            )
        return await auth_service.lookup_sub_admin(email)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@auth_router.get(
    "/users/{user_id}",
    response_model=UserOut,
)
async def get_user_identity(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Resolve a safe user identity for authenticated admin screens."""

    try:
        if current_user.get("role") not in ["super_admin", "sub_admin"]:
            raise AuthorizationException("Admin access only.")
        return await auth_service.get_user_identity(user_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


@auth_router.post(
    "/change-password",
)
async def change_password(
    payload: PasswordChange,
    current_user: dict = Depends(get_current_user_for_password_change),
):
    """Change the authenticated user's password."""

    try:
        return await auth_service.change_password(
            user_id=current_user["id"],
            current_password=payload.currentPassword,
            new_password=payload.newPassword,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Create Client
# ------------------------------------------------------------------

@auth_router.post(
    "/create-client",
    response_model=UserOut,
)
async def create_client(
    client_data: UserCreate,
    current_user: dict = Depends(
        get_current_user
    ),
):
    """Create a client account from the admin workflow."""

    try:
        if current_user.get("role") not in [
            "super_admin",
            "sub_admin",
        ]:
            raise AuthorizationException(
                "Only admins can create clients"
            )

        return await auth_service.register_client(
            name=client_data.name,
            email=client_data.email,
            phone=client_data.phone,
            password=client_data.password,
            current_user=current_user,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


# ------------------------------------------------------------------
# Create Sub Admin
# ------------------------------------------------------------------

@auth_router.post(
    "/create-sub-admin",
    response_model=SubAdminCreateResponse,
)
async def create_sub_admin(
    admin_data: AdminCreate,
    current_user: dict = Depends(
        get_current_user
    ),
):
    """Create a new Sub Admin."""

    try:
        if current_user.get("role") != "super_admin":
            raise AuthorizationException(
                "Only Super Admin can create Sub-Admins"
            )

        return await auth_service.create_sub_admin(
            email=admin_data.email,
            name=admin_data.name,
            phone=admin_data.phone,
            current_user=current_user,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@auth_router.patch(
    "/users/{user_id}/status",
    response_model=UserOut,
)
async def update_user_status(
    user_id: str,
    payload: AccountStatusUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Activate or deactivate a user without deleting historical data."""

    try:
        if current_user.get("role") != "super_admin":
            raise AuthorizationException(
                "Only Super Admin can change account status."
            )
        return await auth_service.set_user_active(
            user_id,
            payload.isActive,
            current_user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise exception_to_http(exc)
