"""Activity Service."""

from datetime import datetime, timezone

from app.exceptions import ResourceNotFoundException, ValidationException
from app.logger import logger_activity
from app.repositories.activitylog_repo import ActivityLogRepository
from app.repositories.user_repo import UserRepository


class ActivityLogService:
    """Service for activity log operations."""

    def __init__(self):
        self.activity_repo = ActivityLogRepository()
        self.user_repo = UserRepository()

    async def log_activity(
        self,
        user_id: str,
        user_role: str,
        action: str,
        entity: str,
        entity_id: str,
        details: dict | None = None,
    ) -> dict | None:
        """Create a new activity log."""

        actor_name = None
        if user_id and user_id != "system":
            try:
                actor = await self.user_repo.find_by_id(str(user_id))
                actor_name = actor.get("name") if actor else None
            except Exception:
                actor_name = None

        log_data = {
            "userId": str(user_id),
            "userRole": str(user_role),
            "actorName": actor_name,
            "action": action.strip(),
            "entity": entity.strip(),
            "entityId": str(entity_id),
            "details": details or {},
            "timestamp": datetime.now(timezone.utc),
        }

        try:
            log_id = await self.activity_repo.create(log_data)
            created = await self.activity_repo.find_by_id(log_id)
            normalized = self.normalize_log(created or {"_id": log_id, **log_data})
            logger_activity.info(f"{action} | {entity} | {entity_id}")
            return normalized
        except Exception:
            logger_activity.exception(
                "Activity log write failed: action=%s entity=%s entity_id=%s",
                action,
                entity,
                entity_id,
            )
            return None

    @staticmethod
    def normalize_log(log: dict) -> dict:
        """Normalize current and legacy activity records for API responses."""

        normalized = dict(log)
        raw_id = normalized.pop("_id", None)
        if raw_id is not None:
            normalized["id"] = str(raw_id)
        elif normalized.get("id") is not None:
            normalized["id"] = str(normalized["id"])

        timestamp = normalized.get("timestamp") or normalized.get("createdAt")
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        normalized["timestamp"] = timestamp

        for field in ("userId", "entityId"):
            if normalized.get(field) is not None:
                normalized[field] = str(normalized[field])

        return normalized

    async def get_all_logs(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return all activity logs."""

        logs = await self.activity_repo.get_all_sorted(
            skip,
            limit,
        )

        return [self.normalize_log(log) for log in logs]

    async def get_user_activity_logs(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return activity logs for a specific user."""

        if not user_id:
            raise ValidationException(
                "User ID is required."
            )

        logs = await self.activity_repo.find_by_user(
            user_id,
            skip,
            limit,
        )

        return [self.normalize_log(log) for log in logs]

    async def get_activity_log(
        self,
        log_id: str,
    ) -> dict:
        """Return a single activity log."""

        log = await self.activity_repo.find_by_id(
            log_id
        )

        if not log:
            raise ResourceNotFoundException(
                "Activity Log"
            )

        return self.normalize_log(log)

    async def get_entity_history(
        self,
        entity_id: str,
        entity: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return activity history for an entity."""

        if not entity_id:
            raise ValidationException(
                "Entity ID is required."
            )

        logs = await self.activity_repo.find_by_entity(
            entity_id,
            entity,
            skip,
            limit,
        )

        return [self.normalize_log(log) for log in logs]
