"""Authentication Service."""

import secrets
from passlib.exc import InvalidHashError
from app.config import SUPER_ADMIN_EMAIL, SUPER_ADMIN_NAME, SUPER_ADMIN_PASSWORD
from app.db.models import hash_password, verify_password
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    DuplicateException,
    ResourceNotFoundException,
    ValidationException,
)
from app.logger import logger_auth
from app.repositories.user_repo import UserRepository
from app.repositories.lead_repo import LeadRepository
from app.services.activitylog_service import ActivityLogService
from app.services.email import send_welcome_email


class AuthService:
    """Service for authentication and user management."""

    def __init__(self):
        self.user_repo = UserRepository()
        self.lead_repo = LeadRepository()
        self.activity_service = ActivityLogService()

    @staticmethod
    def _validate_password(password: str) -> None:
        if not isinstance(password, str) or len(password) < 8 or not password.strip():
            raise ValidationException(
                "Password must contain at least 8 non-whitespace characters."
            )

    async def seed_super_admin(
        self,
    ) -> None:
        """Create the default Super Admin if one does not already exist."""

        if await self.user_repo.super_admin_exists():
            logger_auth.info(
                "Super Admin already exists."
            )
            return

        user_data = {
            "name": SUPER_ADMIN_NAME,
            "email": SUPER_ADMIN_EMAIL.strip().lower(),
            "phone": None,
            "passwordHash": hash_password(
                SUPER_ADMIN_PASSWORD
            ),
            "role": "super_admin",
            "isActive": True,
            "mustChangePassword": False,
            "securityVersion": 0,
        }

        await self.user_repo.create(
            user_data
        )

        logger_auth.info(
            f"Default Super Admin created: {SUPER_ADMIN_EMAIL}"
        )

    async def register_client(
        self,
        name: str,
        email: str,
        phone: str | None,
        password: str,
        current_user: dict | None = None,
    ) -> dict:
        """Register a new client."""

        email = email.strip().lower()
        name = name.strip()
        phone = phone.strip() if phone else None
        self._validate_password(password)

        if await self.user_repo.email_exists(
            email
        ):
            logger_auth.warning(
                f"Registration failed: email {email} already exists"
            )
            raise DuplicateException(
                "Email"
            )

        user_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "passwordHash": hash_password(
                password
            ),
            "role": "client",
            "isActive": True,
            "mustChangePassword": False,
            "securityVersion": 0,
        }

        user_id = await self.user_repo.create(
            user_data
        )

        actor_id = current_user["id"] if current_user else user_id
        actor_role = current_user["role"] if current_user else "client"
        await self.activity_service.log_activity(
            user_id=actor_id,
            user_role=actor_role,
            action="User Created",
            entity="User",
            entity_id=user_id,
            details={"createdRole": "client"},
        )

        logger_auth.info(
            f"New client registered: {email}"
        )

        email_sent = True
        try:
            send_welcome_email(name, email, password, "client")
        except Exception as exc:
            email_sent = False
            logger_auth.error(f"Failed to send client welcome email: {exc}")

        return {
            "id": user_id,
            "name": name,
            "email": email,
            "phone": phone,
            "role": "client",
            "emailSent": email_sent,
        }

    async def verify_credentials(
        self,
        email: str,
        password: str,
    ) -> dict:
        """Verify user credentials."""

        email = email.strip().lower()

        user = await self.user_repo.find_by_email(
            email
        )

        valid_password = False
        if user and user.get("isActive", True) and user.get("passwordHash"):
            try:
                valid_password = verify_password(
                    password,
                    user["passwordHash"],
                )
            except (InvalidHashError, TypeError, ValueError):
                valid_password = False

        if not user or not valid_password or user.get("role") not in {
            "super_admin",
            "sub_admin",
            "client",
        }:
            logger_auth.warning(
                f"Login failed for user: {email[:3]}***"
            )
            raise AuthenticationException(
                "Invalid email or password"
            )

        return {
            "id": str(user["_id"]),
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "mustChangePassword": user.get("mustChangePassword", False),
            "securityVersion": user.get("securityVersion", 0),
        }

    async def create_sub_admin(
        self,
        email: str,
        name: str,
        current_user: dict | None = None,
        phone: str | None = None,
    ) -> dict:
        """Create a new Sub Admin."""

        email = email.strip().lower()
        name = name.strip()
        phone = phone.strip() if phone else None

        if await self.user_repo.email_exists(
            email
        ):
            raise DuplicateException(
                "Email"
            )

        temp_password = secrets.token_urlsafe(
            12
        )

        user_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "passwordHash": hash_password(
                temp_password
            ),
            "role": "sub_admin",
            "isActive": True,
            "mustChangePassword": True,
            "securityVersion": 0,
        }

        user_id = await self.user_repo.create(
            user_data
        )

        actor_id = current_user["id"] if current_user else user_id
        actor_role = current_user["role"] if current_user else "system"
        await self.activity_service.log_activity(
            user_id=actor_id,
            user_role=actor_role,
            action="User Created",
            entity="User",
            entity_id=user_id,
            details={"createdRole": "sub_admin"},
        )

        logger_auth.info(
            f"New sub-admin created: {email}"
        )

        try:
            send_welcome_email(name, email, temp_password, "sub_admin")
        except Exception as exc:
            logger_auth.error(f"Failed to send Sub Admin welcome email: {exc}")

        return {
            "user": {
                "id": user_id,
                "name": name,
                "email": email,
                "phone": phone,
                "role": "sub_admin",
                "mustChangePassword": True,
            },
            "temporary_password": temp_password,
        }

    async def get_current_user_profile(
        self,
        user_id: str,
    ) -> dict:
        """Return the profile of the current user."""

        user = await self.user_repo.find_by_id(
            user_id
        )

        if not user:
            raise ResourceNotFoundException(
                "User"
            )

        user["id"] = str(user["_id"])
        user.pop("passwordHash", None)

        return user

    async def update_profile(self, user_id: str, updates: dict) -> dict:
        user = await self.user_repo.find_by_id(user_id)
        if not user or not user.get("isActive", True):
            raise AuthenticationException("Authentication failed.")

        data = {}
        if "name" in updates and updates["name"] is not None:
            name = updates["name"].strip()
            if not name:
                raise ValidationException("Name cannot be blank.")
            data["name"] = name
        if "phone" in updates:
            data["phone"] = updates["phone"].strip() if updates["phone"] else None
        if not data:
            raise ValidationException("At least one profile field is required.")

        if not await self.user_repo.update_profile(user_id, data):
            raise ValidationException("Profile was not changed.")
        if "phone" in data:
            await self.lead_repo.update_client_phone(user_id, data["phone"])
        updated = await self.user_repo.find_by_id(user_id)
        updated["id"] = str(updated["_id"])
        updated.pop("passwordHash", None)
        await self.activity_service.log_activity(
            user_id=user_id,
            user_role=user.get("role", "unknown"),
            action="Profile Updated",
            entity="User",
            entity_id=user_id,
            details={"fields": list(data)},
        )
        return updated

    async def lookup_sub_admin(self, email: str) -> dict:
        """Return a safe active Sub Admin record for administrative assignment."""

        user = await self.user_repo.find_by_email(email.strip().lower())
        if not user or user.get("role") != "sub_admin" or not user.get("isActive", True):
            raise ResourceNotFoundException("Active Sub Admin")
        user["id"] = str(user["_id"])
        user.pop("_id", None)
        user.pop("passwordHash", None)
        user.pop("securityVersion", None)
        return user

    async def get_user_identity(self, user_id: str) -> dict:
        """Return the safe identity fields needed for admin-facing references."""

        user = await self.user_repo.find_by_id(user_id)
        if not user:
            raise ResourceNotFoundException("User")

        return {
            "id": str(user["_id"]),
            "name": user.get("name", "Team member"),
            "email": user.get("email"),
            "role": user.get("role"),
        }

    async def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> dict:
        """Change the authenticated user's password."""

        self._validate_password(new_password)
        user = await self.user_repo.find_by_id(user_id)
        if not user or not user.get("isActive", True):
            raise AuthenticationException("Authentication failed.")

        try:
            valid = verify_password(
                current_password,
                user.get("passwordHash", ""),
            )
        except (InvalidHashError, TypeError, ValueError):
            valid = False

        if not valid:
            raise AuthenticationException("Current password is invalid.")

        updated = await self.user_repo.update_password(
            user_id,
            hash_password(new_password),
        )
        if not updated:
            raise ResourceNotFoundException("User")

        await self.activity_service.log_activity(
            user_id=user_id,
            user_role=user.get("role", "unknown"),
            action="Password Changed",
            entity="User",
            entity_id=user_id,
        )

        return {"message": "Password changed successfully."}

    async def set_user_active(
        self,
        user_id: str,
        is_active: bool,
        current_user: dict,
    ) -> dict:
        """Activate or deactivate a user without deleting history."""

        if current_user.get("role") != "super_admin":
            raise AuthorizationException(
                "Only Super Admin can change account status."
            )

        user = await self.user_repo.find_by_id(user_id)
        if not user:
            raise ResourceNotFoundException("User")

        if not is_active and user.get("role") == "super_admin":
            active_super_admins = await self.user_repo.count(
                {"role": "super_admin", "isActive": {"$ne": False}}
            )
            if active_super_admins <= 1:
                raise ValidationException(
                    "The last active Super Admin cannot be deactivated."
                )

        updated = await self.user_repo.set_active(user_id, is_active)
        if not updated:
            raise ValidationException("Account status was not changed.")

        updated_user = await self.user_repo.find_by_id(user_id)
        updated_user["id"] = str(updated_user["_id"])
        updated_user.pop("passwordHash", None)
        await self.activity_service.log_activity(
            user_id=current_user["id"],
            user_role=current_user["role"],
            action="User Activated" if is_active else "User Deactivated",
            entity="User",
            entity_id=user_id,
            details={"isActive": is_active, "affectedRole": user.get("role")},
        )
        return updated_user
