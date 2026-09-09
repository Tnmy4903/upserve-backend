"""
Project Discussions API
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import get_current_user
from app.db.schemas import (
    DiscussionMessageCreate,
    DiscussionMessageOut,
    DiscussionReplyCreate,
)
from app.exceptions import exception_to_http
from app.services.discussion_service import DiscussionService


discussion_router = APIRouter()

discussion_service = DiscussionService()


@discussion_router.post(
    "/projects/{project_id}/discussions",
    response_model=DiscussionMessageOut,
)
async def add_message(
    project_id: str,
    msg: DiscussionMessageCreate,
    current_user: dict = Depends(get_current_user),
):
    """Add message to project discussion."""

    try:
        return await discussion_service.add_message(
            project_id=project_id,
            current_user=current_user,
            author_id=current_user["id"],
            author_name=current_user["name"],
            message=msg.message,
            attachments=msg.attachments,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@discussion_router.get(
    "/projects/{project_id}/discussions",
    response_model=list[DiscussionMessageOut],
)
async def get_project_discussions(
    project_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    """Get project discussion."""

    try:
        return await discussion_service.get_project_discussion(
            project_id=project_id,
            current_user=current_user,
            skip=skip,
            limit=limit,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@discussion_router.post(
    "/discussions/{message_id}/replies",
    response_model=dict,
)
async def add_reply(
    message_id: str,
    reply: DiscussionReplyCreate,
    current_user: dict = Depends(get_current_user),
):
    """Add reply to discussion message."""

    try:
        return await discussion_service.add_reply(
            message_id=message_id,
            current_user=current_user,
            author_id=current_user["id"],
            author_name=current_user["name"],
            message=reply.message,
            attachments=reply.attachments,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@discussion_router.get(
    "/discussions/{message_id}",
    response_model=DiscussionMessageOut,
)
async def get_message(
    message_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get discussion message."""

    try:
        return await discussion_service.get_message(
            message_id=message_id,
            current_user=current_user,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)


@discussion_router.delete(
    "/discussions/{message_id}",
    response_model=dict,
)
async def delete_message(
    message_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete discussion message."""

    try:
        return await discussion_service.delete_message(
            message_id=message_id,
            current_user=current_user,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise exception_to_http(exc)