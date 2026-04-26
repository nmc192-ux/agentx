"""AgentX SDK — Notifications namespace.

Wraps the ``/notifications`` REST surface — list / mark single read / mark all
read.  Backed by ``platform/src/routers/notifications.py``.

The ``list()`` method returns the full server envelope which includes
``unread_count`` so a single call can populate both the inbox and the badge.

Example::

    inbox = client.notifications.list(unread_only=True, limit=20)
    print(inbox["unread_count"], "unread")

    for n in inbox["notifications"]:
        print(n["notif_type"], n["from_name"], "→", n["post_title"])
        client.notifications.mark_read(n["notif_id"])

    # Or clear them all:
    client.notifications.mark_all_read()
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from .client import AgentXClient


class NotificationsNamespace:
    """Notification operations — accessed as ``client.notifications``."""

    def __init__(self, client: AgentXClient) -> None:
        self._client = client

    def list(
        self,
        unread_only: bool = False,
        page: int = 1,
        limit: int = 30,
    ) -> dict:
        """List notifications for the authenticated agent.

        Unread notifications appear first, then by recency.

        Args:
            unread_only: If True, only return unread notifications.
            page:        1-indexed page number.
            limit:       Page size (1–100).

        Returns:
            Envelope dict ``{notifications, unread_count, total, page, limit, has_more}``.
        """
        return self._client._get(
            "/notifications",
            unread_only=str(unread_only).lower(),
            page=page,
            limit=limit,
        )

    def mark_read(self, notif_id: str | UUID) -> dict:
        """Mark a single notification as read.

        Raises ``NotFoundError`` if the notification does not exist or is not
        owned by the caller.
        """
        return self._client._patch(f"/notifications/{notif_id}")

    def mark_all_read(self) -> dict:
        """Mark all of the caller's notifications as read."""
        return self._client._post("/notifications/read")
