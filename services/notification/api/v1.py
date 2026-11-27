"""Notification API v1 routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from services.notification.application.service import NotificationApplicationService
from services.notification.domain.models import Notification
from shared.security.zero_trust import ZeroTrustContext


def _serialize_notification(n: Notification) -> dict:
    return {
        "notification_id": n.notification_id,
        "user_id": n.user_id,
        "order_id": n.order_id,
        "event_type": n.event_type,
        "channel": n.channel,
        "title": n.title,
        "message": n.message,
        "is_read": n.is_read,
        "created_at": n.created_at,
    }


def create_v1_router(get_service: callable, require_user: callable) -> APIRouter:
    router = APIRouter(prefix="/api/v1/notifications", tags=["notifications-v1"])

    @router.get("")
    def list_notifications(
        ctx: ZeroTrustContext = Depends(require_user),
        svc: NotificationApplicationService = Depends(get_service),
    ) -> dict:
        items = svc.list_notifications(ctx.user.user_id)
        unread_count = sum(1 for n in items if not n.is_read)
        return {
            "api_version": "v1",
            "degraded": False,
            "unread_count": unread_count,
            "items": [_serialize_notification(n) for n in items],
        }

    @router.post("/{notification_id}/read")
    def mark_read(
        notification_id: str,
        ctx: ZeroTrustContext = Depends(require_user),
        svc: NotificationApplicationService = Depends(get_service),
    ) -> dict:
        updated = svc.mark_read(notification_id, ctx.user.user_id)
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
        return {"notification_id": notification_id, "is_read": True}

    @router.post("/read-all")
    def mark_all_read(
        ctx: ZeroTrustContext = Depends(require_user),
        svc: NotificationApplicationService = Depends(get_service),
    ) -> dict:
        count = svc.mark_all_read(ctx.user.user_id)
        return {"marked_read": count}

    return router
