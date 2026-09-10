"""
Audit log — an append-only record of privileged and security-relevant
actions (logins, admin-login approvals, impersonation, user management,
role changes, deactivations).

Writes go exclusively through apps.ops.services.AuditService.record(),
which never raises — a failure to write an audit row must not break the
action being audited.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import UUIDModel


class AuditCategory(models.TextChoices):
    AUTH = "auth", _("Authentication")
    ADMIN_LOGIN = "admin_login", _("Admin login approval")
    IMPERSONATION = "impersonation", _("Impersonation")
    USER = "user", _("User management")
    SECURITY = "security", _("Security")
    OPS = "ops", _("Operations")


class AuditStatus(models.TextChoices):
    SUCCESS = "success", _("Success")
    FAILURE = "failure", _("Failure")
    PENDING = "pending", _("Pending")


class AuditLog(UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="audit_events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    actor_email = models.CharField(max_length=254, blank=True)
    actor_role = models.CharField(max_length=20, blank=True)

    category = models.CharField(
        max_length=20, choices=AuditCategory.choices, db_index=True
    )
    action = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=10, choices=AuditStatus.choices, default=AuditStatus.SUCCESS
    )

    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    target_repr = models.CharField(max_length=255, blank=True)

    message = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["category", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
        ]
        verbose_name = "Audit log entry"
        verbose_name_plural = "Audit log"

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.actor_email or 'system'} {self.action}"
