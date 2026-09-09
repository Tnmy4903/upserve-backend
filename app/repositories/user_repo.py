"""User Repository."""

from app.repositories.base_repo import BaseRepository
from pymongo.errors import DuplicateKeyError
from app.exceptions import DuplicateException


class UserRepository(BaseRepository):
    """Repository for user operations."""

    def __init__(self):
        super().__init__("users")

    async def ensure_indexes(self) -> None:
        """Ensure normalized user emails are unique."""

        await self.collection.create_index(
            "email",
            unique=True,
            name="users_email_unique",
        )

    async def create(self, data: dict) -> str:
        """Create a user and translate duplicate emails."""

        try:
            return await super().create(data)
        except DuplicateKeyError:
            raise DuplicateException("Email")

    async def update_password(
        self,
        user_id: str,
        password_hash: str,
    ) -> bool:
        """Replace a password and invalidate previously issued tokens."""

        from datetime import datetime, timezone
        from bson import ObjectId

        result = await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "passwordHash": password_hash,
                    "mustChangePassword": False,
                    "updatedAt": datetime.now(timezone.utc),
                },
                "$inc": {"securityVersion": 1},
            },
        )
        return result.modified_count > 0

    async def set_active(
        self,
        user_id: str,
        is_active: bool,
    ) -> bool:
        """Change account state and invalidate existing tokens."""

        from datetime import datetime, timezone
        from bson import ObjectId

        result = await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "isActive": is_active,
                    "updatedAt": datetime.now(timezone.utc),
                },
                "$inc": {"securityVersion": 1},
            },
        )
        return result.modified_count > 0

    async def update_profile(self, user_id: str, data: dict) -> bool:
        return await self.update(user_id, data)

    async def find_by_email(
        self,
        email: str,
    ) -> dict | None:
        """Find a user by email address."""

        return await self.find_one(
            {"email": email}
        )

    async def email_exists(
        self,
        email: str,
    ) -> bool:
        """Check whether an email address already exists."""

        user = await self.find_by_email(
            email
        )

        return user is not None

    async def get_active_by_role(
        self,
        role: str,
    ) -> list[dict]:
        """Return active users with a role, including legacy active records."""

        return await self.find_many(
            {
                "role": role,
                "isActive": {"$ne": False},
            }
        )

    async def count_by_role(
        self,
        role: str,
    ) -> int:
        """Return the total number of users for a role."""

        return await self.count(
            {"role": role}
        )

    async def get_admin_count(
        self,
    ) -> int:
        """Return the total number of admin users."""

        return await self.count(
            {
                "role": {
                    "$in": [
                        "super_admin",
                        "sub_admin",
                    ]
                }
            }
        )

    async def super_admin_exists(
        self,
    ) -> bool:
        """Check whether a Super Admin already exists."""

        user = await self.find_one(
            {"role": "super_admin"}
        )

        return user is not None
