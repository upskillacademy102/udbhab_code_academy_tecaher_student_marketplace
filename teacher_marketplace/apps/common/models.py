"""
Common abstract base models for the Teacher Marketplace Platform.

These are ABSTRACT models (Meta.abstract = True) - they create no
database tables of their own. Every concrete model in the project
should inherit from one of these (most commonly BaseModel) instead
of django.db.models.Model directly, to guarantee consistent PKs,
timestamps, soft-delete, and audit behavior project-wide.

Inheritance chain overview:
    UUIDModel        -> just the UUID primary key
    TimestampModel    -> just created_at / updated_at
    SoftDeleteModel    -> just is_deleted / deleted_at + manager
    AuditModel        -> just created_by / updated_by
    BaseModel        -> UUIDModel + TimestampModel + SoftDeleteModel
                          + AuditModel combined (the one most models
                          should actually inherit from)
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


# ==============================================================
# UUID MODEL
# ==============================================================
class UUIDModel(models.Model):
    """
    Abstract base model that replaces Django's default
    auto-incrementing integer PK with a UUID primary key.

    UUIDs are used project-wide (per architecture spec) to avoid
    leaking sequential IDs (e.g. guessing how many teachers exist
    by incrementing a URL) and to make IDs safe to expose in
    public APIs and future distributed/sharded setups.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier (UUID4) for this record.",
    )

    class Meta:
        abstract = True


# ==============================================================
# TIMESTAMP MODEL
# ==============================================================
class TimestampModel(models.Model):
    """
    Abstract base model that adds timezone-aware creation and
    update timestamps to any model that inherits from it.

    USE_TZ = True is set in settings, so these are stored in UTC
    and converted to local time only at the presentation layer.
    """

    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        db_index=True,
        help_text="Timestamp when this record was created (UTC).",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when this record was last updated (UTC).",
    )

    class Meta:
        abstract = True


# ==============================================================
# SOFT DELETE MANAGER + MODEL
# ==============================================================
class SoftDeleteQuerySet(models.QuerySet):
    """
    QuerySet that provides explicit control over soft-deleted
    records, used by both manager variants below.
    """

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)

    def delete(self):
        """
        Bulk soft-delete: overriding queryset.delete() so that
        calling MyModel.objects.filter(...).delete() soft-deletes
        instead of hard-deleting, keeping behavior consistent with
        instance.delete() below.
        """
        return self.update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self):
        """Permanently remove rows from the database. Use with care."""
        return super().delete()


class SoftDeleteManager(models.Manager):
    """
    Default manager for soft-deletable models. Excludes soft-deleted
    records from all normal querysets (e.g. MyModel.objects.all()
    will NOT include deleted rows).
    """

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()


class AllObjectsManager(models.Manager):
    """
    Secondary manager that includes soft-deleted records. Access via
    MyModel.all_objects.all() when you explicitly need deleted rows
    (e.g. an admin "trash" view or an audit report).
    """

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


class SoftDeleteModel(models.Model):
    """
    Abstract base model implementing soft-delete: records are
    flagged as deleted rather than removed from the database,
    preserving referential integrity and audit history (important
    for a marketplace with financial transactions in later phases).

    - `objects` (default manager): excludes soft-deleted rows.
    - `all_objects`: includes soft-deleted rows.
    """

    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this record has been soft-deleted.",
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when this record was soft-deleted, if applicable.",
    )

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, hard=False):
        """
        Overrides the default delete() to soft-delete by default.

        Pass hard=True to actually remove the row from the database
        (e.g. GDPR-style permanent erasure requests).
        """
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["is_deleted", "deleted_at"])
        return None

    def restore(self):
        """Reverses a soft-delete, making the record visible again."""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])


# ==============================================================
# AUDIT MODEL
# ==============================================================
class AuditModel(models.Model):
    """
    Abstract base model that tracks WHO created and last updated a
    record, in addition to TimestampModel's WHEN. Uses
    settings.AUTH_USER_MODEL as a string reference (not a direct
    import of the User model) to avoid circular imports, since
    apps.accounts.User itself may inherit from BaseModel.

    These fields are nullable because:
    - System/seed-created records may have no responsible user.
    - The user who created/updated a record may later be deleted
      (on_delete=SET_NULL preserves the record rather than cascading
      a delete through unrelated data).
    """

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(app_label)s_%(class)s_created",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        help_text="User who created this record, if known.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(app_label)s_%(class)s_updated",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        help_text="User who last updated this record, if known.",
    )

    class Meta:
        abstract = True


# ==============================================================
# BASE MODEL (composed - what most models should actually use)
# ==============================================================
class BaseModel(UUIDModel, TimestampModel, SoftDeleteModel, AuditModel):
    """
    The primary abstract base class for domain models across the
    project. Combines:
        - UUIDModel        -> UUID primary key
        - TimestampModel    -> created_at / updated_at
        - SoftDeleteModel    -> is_deleted / deleted_at + managers
        - AuditModel        -> created_by / updated_by

    Most models (User, Student, Teacher, and everything in later
    phases like Wallet, Transaction, Lead) should inherit from
    this directly rather than composing the pieces manually.

    Models that genuinely don't need all four behaviors (rare) may
    inherit from the individual pieces instead - e.g. a pure lookup
    table might use only UUIDModel + TimestampModel.
    """

    class Meta:
        abstract = True
        ordering = ["-created_at"]
