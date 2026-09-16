"""Audit trail writing.

Every state-changing action records a row. The table is append-only: nothing in
the application ever updates or deletes one, and ``user_id`` uses
``ON DELETE SET NULL`` so that removing a user cannot erase the record of what
that user did.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fai.core.logging import get_logger
from fai.db.models import ActivityLog

log = get_logger(__name__)

# Actions are named "<resource>.<verb>" so that the log can be filtered by
# resource family without parsing.
ACTION_USER_REGISTERED = "user.registered"
ACTION_USER_LOGIN = "user.login"
ACTION_USER_LOGIN_FAILED = "user.login_failed"
ACTION_USER_LOGOUT = "user.logout"
ACTION_USER_ROLE_CHANGED = "user.role_changed"
ACTION_TOKEN_REFRESHED = "token.refreshed"
ACTION_TOKEN_REUSE_DETECTED = "token.reuse_detected"
ACTION_DOCUMENT_UPLOADED = "document.uploaded"
ACTION_DOCUMENT_DELETED = "document.deleted"
ACTION_ANALYSIS_RUN = "analysis.run"
ACTION_FLAG_UPDATED = "flag.updated"
ACTION_REPORT_GENERATED = "report.generated"
ACTION_EXPLANATION_REQUESTED = "explanation.requested"


async def record(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str | uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Append one audit row.

    The row is added to the caller's transaction rather than committed here, so
    that an action and its audit record either both land or neither does. An
    audit trail that survives a rolled-back action is worse than none, because
    it is confidently wrong.
    """
    db.add(
        ActivityLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            detail=detail or {},
            ip_address=ip_address,
            # Bounded: this is an attacker-controlled header and the column is
            # unbounded text.
            user_agent=user_agent[:1024] if user_agent else None,
        )
    )
    log.info(
        "activity_recorded",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
    )
