"""
Reviews & ratings (Phase 8c).

A student reviews a teacher they had a real lead relationship with (the
teacher unlocked the student's lead, or accepted its assignment). Integrity
rules are enforced in ``ReviewIntegrityService``; ``TeacherProfile.rating``
is recomputed from PUBLISHED reviews only.

Nothing here is exposed or recomputed unless ``TRUST_ENABLE_REVIEW_SYSTEM``
is on - the endpoints 404/403 and the rating stays admin-managed as before.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import validate_no_control_characters


class ReviewStatus(models.TextChoices):
    PUBLISHED = "published", _("Published")
    PENDING = "pending", _("Pending moderation")
    FLAGGED = "flagged", _("Flagged (integrity / content)")
    REMOVED = "removed", _("Removed")


class Review(BaseModel):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="reviews_written",
        on_delete=models.CASCADE,
        help_text=_("The student writing the review."),
    )
    teacher = models.ForeignKey(
        "teachers.Teacher",
        related_name="reviews",
        on_delete=models.CASCADE,
    )
    source_lead = models.ForeignKey(
        "lead_engine.Lead",
        related_name="reviews",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("The lead that establishes the author<->teacher relationship."),
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    text = models.CharField(
        max_length=2000,
        blank=True,
        validators=[validate_no_control_characters],
    )
    status = models.CharField(
        max_length=12,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PUBLISHED,
        db_index=True,
    )
    flag_reason = models.CharField(max_length=255, blank=True)
    # coarse fingerprint of the submitting client (rating-ring detection)
    author_fingerprint = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        verbose_name = _("Review")
        verbose_name_plural = _("Reviews")
        ordering = ["-created_at"]
        constraints = [
            # One review per lead. (Self-review prevention lives in
            # ReviewIntegrityService - it needs the author<->teacher.user
            # join, which a CheckConstraint cannot express.)
            models.UniqueConstraint(
                fields=["author", "source_lead"],
                name="review_unique_per_author_lead",
                condition=models.Q(source_lead__isnull=False),
            ),
            models.CheckConstraint(
                name="review_rating_range",
                check=models.Q(rating__gte=1) & models.Q(rating__lte=5),
            ),
        ]
        indexes = [
            models.Index(fields=["teacher", "status"]),
            models.Index(fields=["author", "status"]),
        ]

    def __str__(self):
        return f"{self.author_id} -> teacher {self.teacher_id}: {self.rating}★ ({self.status})"
