"""AuditService — the only writer of AuditLog rows."""

import logging

from apps.ops.models import AuditLog, AuditStatus

logger = logging.getLogger("apps.ops")

# Header value length we're willing to store.
_UA_MAX = 400


def _client_ip(request):
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditService:
    @staticmethod
    def record(
        *,
        action,
        category,
        request=None,
        actor=None,
        status=AuditStatus.SUCCESS,
        target=None,
        target_type="",
        target_id="",
        target_repr="",
        message="",
        **metadata,
    ):
        """
        Persist one audit row. Never raises — logs and moves on if the
        write fails, so auditing can't break the audited operation.
        """
        try:
            if actor is None and request is not None:
                actor = getattr(request, "user", None)
                if actor is not None and not getattr(actor, "is_authenticated", False):
                    actor = None

            if target is not None and not target_id:
                target_type = target_type or target.__class__.__name__
                target_id = str(getattr(target, "pk", "") or "")
                target_repr = target_repr or str(target)[:255]

            AuditLog.objects.create(
                actor=actor if actor and getattr(actor, "pk", None) else None,
                actor_email=(getattr(actor, "email", "") or "")[:254],
                actor_role=getattr(actor, "role", "") or "",
                category=category,
                action=action,
                status=status,
                target_type=target_type[:40],
                target_id=str(target_id)[:64],
                target_repr=str(target_repr)[:255],
                message=str(message)[:255],
                metadata=metadata or {},
                ip_address=_client_ip(request),
                user_agent=(request.META.get("HTTP_USER_AGENT", "") if request else "")[
                    :_UA_MAX
                ],
            )
        except Exception:  # noqa: BLE001 - auditing must never break the caller
            logger.exception("Failed to write audit log for action=%s", action)
