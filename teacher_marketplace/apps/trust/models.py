"""
Core trust models.

``TrustProfile``   - one row per User; the aggregate verification score,
                     risk score/state, and (student-side) lead-quality
                     score that later phases read and write.
``ManualReviewItem`` - the single queue every fraud/verification signal
                     feeds into (teacher-verification docs, duplicate
                     accounts, fake-lead reports, payment disputes,
                     content flags, user reports, reconciliation drift,
                     anomaly alerts). Admins work it from one place.

Both are additive - nothing in the platform reads them until a later
phase wires them in behind a feature flag.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import validate_image_upload


class RiskState(models.TextChoices):
    NORMAL = "normal", _("Normal")
    LIMITED = "limited", _("Limited")  # reduced lead/search visibility
    REVIEW = "review", _("Under review")
    SUSPENDED = "suspended", _("Suspended")


class TrustProfile(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="trust_profile",
        on_delete=models.CASCADE,
    )

    # 0.000 - 1.000. For teachers this is the verification-progress-bar
    # fraction; for students it stays near 0 until they verify contacts.
    verification_score = models.DecimalField(
        _("verification score"),
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.000"),
        validators=[
            MinValueValidator(Decimal("0.000")),
            MaxValueValidator(Decimal("1.000")),
        ],
    )
    is_fully_verified = models.BooleanField(_("fully verified badge"), default=False)

    # 0 - 100. Higher = riskier.
    risk_score = models.PositiveSmallIntegerField(
        _("risk score"),
        default=0,
        validators=[MaxValueValidator(100)],
    )
    risk_state = models.CharField(
        _("risk state"),
        max_length=12,
        choices=RiskState.choices,
        default=RiskState.NORMAL,
        db_index=True,
    )

    # Student-side signal (1.000 = clean history, drops toward 0 as
    # corroborated fake/unreachable leads accumulate). Set in Phase 6.
    lead_quality_score = models.DecimalField(
        _("lead quality score"),
        max_digits=4,
        decimal_places=3,
        default=Decimal("1.000"),
        validators=[
            MinValueValidator(Decimal("0.000")),
            MaxValueValidator(Decimal("1.000")),
        ],
    )

    verification_recomputed_at = models.DateTimeField(null=True, blank=True)
    risk_recomputed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    # Countries this user has previously logged in from (Phase 9 anomaly
    # detection). ISO-2 codes; a login from a country not in this list is an
    # anomaly once the list is non-empty.
    known_countries = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = _("Trust profile")
        verbose_name_plural = _("Trust profiles")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["risk_state", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="trust_profile_verification_score_range",
                check=models.Q(verification_score__gte=0)
                & models.Q(verification_score__lte=1),
            ),
            models.CheckConstraint(
                name="trust_profile_lead_quality_score_range",
                check=models.Q(lead_quality_score__gte=0)
                & models.Q(lead_quality_score__lte=1),
            ),
            models.CheckConstraint(
                name="trust_profile_risk_score_range",
                check=models.Q(risk_score__gte=0) & models.Q(risk_score__lte=100),
            ),
        ]

    def __str__(self):
        return f"TrustProfile<{self.user_id}> score={self.verification_score} risk={self.risk_state}"


class ManualReviewKind(models.TextChoices):
    TEACHER_VERIFICATION = "teacher_verification", _("Teacher verification")
    DUPLICATE_ACCOUNT = "duplicate_account", _("Duplicate account")
    LEAD_QUALITY = "lead_quality", _("Fake / unreachable lead")
    FAKE_LEAD_REPORT = "fake_lead_report", _("Fake lead reports")
    PAYMENT_DISPUTE = "payment_dispute", _("Payment dispute")
    PAYMENT_RISK = "payment_risk", _("Payment risk")
    CONTENT_FLAG = "content_flag", _("Flagged content")
    USER_REPORT = "user_report", _("User report")
    RECONCILIATION = "reconciliation", _("Payment reconciliation drift")
    ANOMALY = "anomaly", _("Anomaly alert")
    RISK_ESCALATION = "risk_escalation", _("Risk escalation")
    SUSPENSION_APPEAL = "suspension_appeal", _("Suspension appeal")
    SUPPORT_TICKET = "support_ticket", _("Support ticket / bug report")


class ManualReviewStatus(models.TextChoices):
    OPEN = "open", _("Open")
    IN_REVIEW = "in_review", _("In review")
    RESOLVED = "resolved", _("Resolved")
    DISMISSED = "dismissed", _("Dismissed")


class ManualReviewItem(BaseModel):
    kind = models.CharField(
        max_length=32, choices=ManualReviewKind.choices, db_index=True
    )
    status = models.CharField(
        max_length=12,
        choices=ManualReviewStatus.choices,
        default=ManualReviewStatus.OPEN,
        db_index=True,
    )
    # 1 = highest priority, 5 = lowest.
    priority = models.PositiveSmallIntegerField(default=3)

    subject_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="review_items",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    summary = models.CharField(max_length=255)
    payload = models.JSONField(default=dict, blank=True)

    # When set, TrustService.open_review_item() will not create a second
    # open item with the same (kind, dedupe_key) - keeps the queue clean
    # when the same signal fires repeatedly.
    dedupe_key = models.CharField(max_length=200, blank=True, db_index=True)

    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="review_items_assigned",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    resolution = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="review_items_resolved",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Manual review item")
        verbose_name_plural = _("Manual review queue")
        ordering = ["priority", "-created_at"]
        indexes = [
            models.Index(fields=["status", "kind", "priority"]),
            models.Index(fields=["kind", "dedupe_key"]),
        ]

    def __str__(self):
        return f"[{self.kind}] {self.summary} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status in (ManualReviewStatus.OPEN, ManualReviewStatus.IN_REVIEW)


class OTPChannel(models.TextChoices):
    EMAIL = "email", _("Email")
    SMS = "sms", _("SMS")


class OTPPurpose(models.TextChoices):
    VERIFY_EMAIL = "verify_email", _("Verify email address")
    VERIFY_MOBILE = "verify_mobile", _("Verify mobile number")
    SENSITIVE_CHANGE = "sensitive_change", _("Confirm a sensitive account change")


class OTPChallenge(BaseModel):
    """
    One issued one-time code. Short-lived, single-use, attempt-capped, and
    stored only as a hash. A new issue for the same (user, purpose)
    supersedes any earlier unconsumed challenge.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="otp_challenges",
        on_delete=models.CASCADE,
    )
    channel = models.CharField(max_length=8, choices=OTPChannel.choices)
    purpose = models.CharField(max_length=32, choices=OTPPurpose.choices, db_index=True)
    destination = models.CharField(
        max_length=255,
        help_text=_("Email or mobile the code was sent to at issue time."),
    )
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("OTP challenge")
        verbose_name_plural = _("OTP challenges")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "purpose", "consumed_at"]),
        ]

    def __str__(self):
        return f"OTP<{self.user_id}/{self.purpose}> {'used' if self.consumed_at else 'pending'}"

    @property
    def is_pending(self) -> bool:
        from django.utils import timezone

        return (
            self.consumed_at is None
            and self.expires_at > timezone.now()
            and self.attempts < self.max_attempts
        )


class SensitiveChangeField(models.TextChoices):
    EMAIL = "email", _("Email address")
    MOBILE = "mobile", _("Mobile number")
    PASSWORD = "password", _("Password")


class SensitiveChangeState(models.TextChoices):
    AWAITING_OTP = "awaiting_otp", _("Awaiting code confirmation")
    SCHEDULED = "scheduled", _("Scheduled (cooldown running)")
    APPLIED = "applied", _("Applied")
    CANCELLED = "cancelled", _("Cancelled")
    EXPIRED = "expired", _("Expired")


class SensitiveChangeRequest(BaseModel):
    """
    A pending change to email / mobile / password. The caller confirms a
    one-time code (``challenge``) before the change is honoured; when
    ``TRUST_ENABLE_STEP_UP_REVERIFICATION`` is ON, email / mobile changes
    then wait out a cooldown (``apply_after``) during which the account
    owner can cancel - the reaction window against a hijacked session
    trying to lock them out.
    """

    ACTIVE_STATES = ("awaiting_otp", "scheduled")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="sensitive_change_requests",
        on_delete=models.CASCADE,
    )
    field = models.CharField(
        max_length=12, choices=SensitiveChangeField.choices, db_index=True
    )
    new_value = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("New email / mobile (not used for password)."),
    )
    new_secret_hash = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Hashed new password (password changes only)."),
    )
    challenge = models.ForeignKey(
        OTPChallenge,
        related_name="sensitive_changes",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    state = models.CharField(
        max_length=16,
        choices=SensitiveChangeState.choices,
        default=SensitiveChangeState.AWAITING_OTP,
        db_index=True,
    )
    apply_after = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = _("Sensitive change request")
        verbose_name_plural = _("Sensitive change requests")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "field", "state"]),
            models.Index(fields=["state", "apply_after"]),
        ]

    def __str__(self):
        return f"Change {self.field} for {self.user_id} ({self.state})"

    @property
    def is_active(self) -> bool:
        return self.state in self.ACTIVE_STATES


class IdentitySignatureKind(models.TextChoices):
    PHONE = "phone", _("Normalised phone number")
    EMAIL = "email", _("Canonicalised email address")
    DEVICE = "device", _("Client device fingerprint")
    ID_NUMBER = "id_number", _("Government ID number")  # populated in Phase 5
    SELFIE_HASH = "selfie_hash", _("Selfie perceptual hash")  # Phase 5


class IdentitySignature(BaseModel):
    """
    A hashed, normalised identity token for one user - so two accounts that
    share a real-world identity (the same phone written differently, the
    same Gmail with dots/plus, the same device, later the same ID / face)
    can be spotted even though ``User.email`` / ``User.mobile`` uniqueness
    only catches byte-identical values.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="identity_signatures",
        on_delete=models.CASCADE,
    )
    kind = models.CharField(
        max_length=16, choices=IdentitySignatureKind.choices, db_index=True
    )
    value_hash = models.CharField(max_length=64, db_index=True)  # sha256 hex
    source = models.CharField(
        max_length=40, blank=True
    )  # "register" / "login" / "gov_id" ...

    class Meta:
        verbose_name = _("Identity signature")
        verbose_name_plural = _("Identity signatures")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind", "value_hash"],
                name="identity_signature_unique_per_user_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["kind", "value_hash"]),
        ]

    def __str__(self):
        return f"{self.kind}:{self.value_hash[:8]} for {self.user_id}"


class DuplicateSignal(BaseModel):
    """
    A recorded collision: ``user`` shares a ``kind`` identity signature with
    ``matched_user``. Feeds a ManualReviewItem; while unresolved (and
    ``TRUST_ENABLE_DEDUP_BLOCKING`` is ON) it blocks the flagged account's
    lead/paid actions.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="duplicate_signals",
        on_delete=models.CASCADE,
    )
    matched_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="matched_by_duplicate_signals",
        on_delete=models.CASCADE,
    )
    kind = models.CharField(max_length=16, choices=IdentitySignatureKind.choices)
    value_hash = models.CharField(max_length=64)
    review_item = models.ForeignKey(
        "trust.ManualReviewItem",
        related_name="duplicate_signals",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = _("Duplicate signal")
        verbose_name_plural = _("Duplicate signals")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "matched_user", "kind"],
                name="duplicate_signal_unique_pair_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "resolved"]),
        ]

    def __str__(self):
        return f"{self.user_id} ~ {self.matched_user_id} on {self.kind}"


class TeacherVerificationKey(models.TextChoices):
    # --- the "floor" (auto-derived, no submission) ------------------
    PROFILE_BASICS = "profile_basics", _("Profile photo, bio & qualification")
    SUBJECTS_SET = "subjects_set", _("Subjects selected")
    AVAILABILITY_SET = "availability_set", _("Availability added")
    EMAIL_VERIFIED = "email_verified", _("Email verified")
    MOBILE_VERIFIED = "mobile_verified", _("Mobile verified")
    # --- reviewed items (teacher submits, provider/admin decides) ---
    GOV_ID = "gov_id", _("Government photo ID")
    SELFIE_LIVENESS = "selfie_liveness", _("Selfie / liveness")
    ADDRESS_PROOF = "address_proof", _("Address proof")
    VIDEO_INTERVIEW = "video_interview", _("Onboarding video call")
    BANK_PENNY_DROP = "bank_penny_drop", _("Bank account (payouts)")


class TeacherVerificationItemStatus(models.TextChoices):
    PENDING = "pending", _("Not started")
    SUBMITTED = "submitted", _("Submitted, under review")
    VERIFIED = "verified", _("Verified")
    REJECTED = "rejected", _("Rejected")


class TeacherVerificationItem(BaseModel):
    """
    One line of a teacher's verification checklist. The five "floor" items
    are auto-derived (``is_auto``) and their ``status`` is recomputed from
    live profile / contact state; the rest are submitted by the teacher and
    decided by a verification provider or an admin.
    """

    teacher = models.ForeignKey(
        "teachers.Teacher",
        related_name="verification_items",
        on_delete=models.CASCADE,
    )
    key = models.CharField(
        max_length=24, choices=TeacherVerificationKey.choices, db_index=True
    )
    status = models.CharField(
        max_length=12,
        choices=TeacherVerificationItemStatus.choices,
        default=TeacherVerificationItemStatus.PENDING,
        db_index=True,
    )
    weight = models.PositiveSmallIntegerField(default=0)
    is_auto = models.BooleanField(default=False)

    evidence_ref = models.CharField(max_length=255, blank=True)  # storage key / doc ref
    provider_ref = models.CharField(max_length=255, blank=True)  # vendor reference
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="teacher_verification_reviews",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    review_item = models.ForeignKey(
        "trust.ManualReviewItem",
        related_name="teacher_verification_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Teacher verification item")
        verbose_name_plural = _("Teacher verification items")
        ordering = ["teacher_id", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "key"],
                name="teacher_verification_item_unique_per_key",
            ),
        ]
        indexes = [
            models.Index(fields=["teacher", "status"]),
        ]

    def __str__(self):
        return f"{self.teacher_id}/{self.key} = {self.status}"


class VerificationEvidencePose(models.TextChoices):
    """Which shot a stored evidence photo is, for the reviewable checklist
    items that take an uploaded image (gov_id, address_proof,
    selfie_liveness)."""

    DOCUMENT_FRONT = "document_front", _("Document - front")
    DOCUMENT_BACK = "document_back", _("Document - back")
    DOCUMENT = "document", _("Document")
    SELFIE_CENTER = "selfie_center", _("Selfie - looking straight ahead")
    SELFIE_LEFT = "selfie_left", _("Selfie - looking left")
    SELFIE_RIGHT = "selfie_right", _("Selfie - looking right")
    SELFIE_UP = "selfie_up", _("Selfie - looking up")
    SELFIE_DOWN = "selfie_down", _("Selfie - looking down")


class TeacherVerificationEvidence(BaseModel):
    """
    One uploaded photo backing a reviewed ``TeacherVerificationItem``:
    gov_id gets two rows (front/back), address_proof one, selfie_liveness
    five (the guided-capture poses). Resubmitting an item replaces its
    evidence rather than accumulating old ID scans indefinitely.
    """

    item = models.ForeignKey(
        TeacherVerificationItem,
        related_name="evidence_files",
        on_delete=models.CASCADE,
    )
    pose = models.CharField(max_length=16, choices=VerificationEvidencePose.choices)
    file = models.ImageField(
        upload_to="teachers/verification/%Y/%m/",
        validators=[validate_image_upload],
    )

    class Meta:
        verbose_name = _("Teacher verification evidence")
        verbose_name_plural = _("Teacher verification evidence")
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["item"]),
        ]

    def __str__(self):
        return f"{self.item_id}:{self.pose}"


class OnboardingCallRequest(BaseModel):
    """
    A teacher's request for the onboarding video call (the
    ``video_interview`` checklist item). Created once, when the teacher
    requests it; ``scheduled_at`` is null until a Super Admin approves the
    request and assigns an Admin to conduct it - at which point it's set
    automatically to ``created_at`` (of that decision) + 24 hours. The
    call's actual pass/fail outcome stays on the linked item's own
    ``status`` via the existing admin verify/reject endpoint - this model
    only tracks who's running the call and when.
    """

    item = models.OneToOneField(
        TeacherVerificationItem,
        related_name="call_request",
        on_delete=models.CASCADE,
    )
    assigned_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="onboarding_calls_assigned",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)
    scheduled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="onboarding_calls_scheduled",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("The Super Admin who approved and scheduled this call."),
    )

    class Meta:
        verbose_name = _("Onboarding call request")
        verbose_name_plural = _("Onboarding call requests")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["assigned_admin"]),
        ]

    def __str__(self):
        return f"call<{self.item_id}> {'scheduled' if self.scheduled_at else 'requested'}"

    @property
    def is_scheduled(self) -> bool:
        return self.scheduled_at is not None


# ======================================================================
# Phase 6 - student-side risk + lead quality
# ======================================================================
class RiskSignalKind(models.TextChoices):
    REQUIREMENT_VELOCITY = "requirement_velocity", _("Too many requirements")
    REQUIREMENT_ABANDONMENT = "requirement_abandonment", _("Requirements abandoned")
    LEAD_QUALITY = "lead_quality", _("Fake / unreachable leads")
    PHONE_UNREACHABLE = "phone_unreachable", _("Contact number unreachable")
    DUPLICATE_ACCOUNT = "duplicate_account", _("Duplicate account")
    PAYMENT_RISK = "payment_risk", _("Payment risk")
    CONTENT_LEAKAGE = "content_leakage", _("Off-platform contact/payment content")
    USER_REPORT = "user_report", _("Reported by another user")
    ANOMALY = "anomaly", _("Anomaly")


class RiskSignal(BaseModel):
    """
    One negative signal about a user. ``TrustService.recompute_risk`` sums
    the ``weight`` of every ACTIVE signal into ``TrustProfile.risk_score``
    (capped at 100) and derives ``risk_state``.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="risk_signals", on_delete=models.CASCADE
    )
    kind = models.CharField(
        max_length=32, choices=RiskSignalKind.choices, db_index=True
    )
    weight = models.PositiveSmallIntegerField(default=10)
    detail = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Risk signal")
        verbose_name_plural = _("Risk signals")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "active"]),
        ]

    def __str__(self):
        return f"{self.kind} (+{self.weight}) for {self.user_id}"


class LeadQualityVerdict(models.TextChoices):
    GENUINE = "genuine", _("Genuine")
    UNREACHABLE = "unreachable", _("Couldn't reach the student")
    FAKE = "fake", _("Fake / spam")


class LeadQualityRating(BaseModel):
    """A teacher's verdict on one lead they unlocked. One per (teacher, lead)."""

    teacher = models.ForeignKey(
        "teachers.Teacher",
        related_name="lead_quality_ratings",
        on_delete=models.CASCADE,
    )
    lead = models.ForeignKey(
        "lead_engine.Lead", related_name="quality_ratings", on_delete=models.CASCADE
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="lead_quality_ratings_received",
        on_delete=models.CASCADE,
    )
    verdict = models.CharField(
        max_length=12, choices=LeadQualityVerdict.choices, db_index=True
    )
    note = models.CharField(max_length=500, blank=True)
    clawed_back = models.BooleanField(
        default=False,
        help_text=_("A token refund was issued to this teacher for this lead."),
    )

    class Meta:
        verbose_name = _("Lead quality rating")
        verbose_name_plural = _("Lead quality ratings")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "lead"],
                name="lead_quality_rating_unique_per_teacher_lead",
            ),
        ]
        indexes = [
            models.Index(fields=["student", "verdict"]),
        ]

    def __str__(self):
        return f"{self.teacher_id} rated lead {self.lead_id}: {self.verdict}"


class AccountSanctionKind(models.TextChoices):
    BAN = "ban", _("Ban")
    SUSPEND = "suspend", _("Suspension")


class AccountSanctionSource(models.TextChoices):
    MANUAL = "manual", _("Super Admin action")
    AUTO_FAKE_LEADS_WEEKLY = "auto_fake_leads_weekly", _(
        "Automatic - fake-lead reports (weekly threshold)"
    )
    AUTO_FAKE_LEADS_MONTHLY = "auto_fake_leads_monthly", _(
        "Automatic - fake-lead reports (monthly threshold)"
    )
    AUTO_STAFF_LOGIN_BRUTEFORCE = "auto_staff_login_bruteforce", _(
        "Automatic - brute-force admin/super-admin login attempts"
    )


class AccountSanction(BaseModel):
    """
    A ban or suspension applied to an account. Both kinds set
    ``User.is_active = False`` and kill the user's active sessions; neither
    lifts on its own - only a Super Admin reactivating the account clears
    an active sanction (``SanctionService.lift``). ``source`` records
    whether a human or the fake-lead auto-ban raised it.

    One user can accumulate several rows over time (banned, lifted,
    re-banned); at most one is ``active`` at a time.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="account_sanctions",
        on_delete=models.CASCADE,
    )
    kind = models.CharField(max_length=12, choices=AccountSanctionKind.choices)
    source = models.CharField(
        max_length=32,
        choices=AccountSanctionSource.choices,
        default=AccountSanctionSource.MANUAL,
        db_index=True,
    )
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="account_sanctions_created",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("The Super Admin who applied it; null for an automatic ban."),
    )
    review_item = models.ForeignKey(
        "trust.ManualReviewItem",
        related_name="account_sanctions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    payload = models.JSONField(default=dict, blank=True)

    active = models.BooleanField(default=True, db_index=True)
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="account_sanctions_lifted",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    lift_reason = models.TextField(blank=True)

    class Meta:
        verbose_name = _("Account sanction")
        verbose_name_plural = _("Account sanctions")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "active"]),
            models.Index(fields=["active", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(active=True),
                name="account_sanction_one_active_per_user",
            ),
        ]

    def __str__(self):
        state = "active" if self.active else "lifted"
        return f"{self.kind} ({state}) - {self.user_id}"

    @property
    def is_automatic(self) -> bool:
        return self.source != AccountSanctionSource.MANUAL


class RequirementContactCheck(BaseModel):
    """
    Cached phone-reachability result for one requirement's student contact.
    An unreachable result blocks (uncharged) lead unlocks for that
    requirement when ``TRUST_ENABLE_PHONE_REACHABILITY_CHECK`` is on.
    """

    requirement = models.OneToOneField(
        "student_requirement.StudentRequirement",
        related_name="contact_check",
        on_delete=models.CASCADE,
    )
    reachable = models.BooleanField()
    detail = models.CharField(max_length=255, blank=True)
    provider_ref = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = _("Requirement contact check")
        verbose_name_plural = _("Requirement contact checks")
        ordering = ["-created_at"]

    def __str__(self):
        return f"req {self.requirement_id}: {'reachable' if self.reachable else 'unreachable'}"


# ======================================================================
# Phase 8 - content moderation, reviews integrity, report & block
# ======================================================================
class ContentFlagStatus(models.TextChoices):
    OPEN = "open", _("Open")
    RESOLVED = "resolved", _("Resolved (content fixed / cleared)")
    DISMISSED = "dismissed", _("Dismissed (false positive)")


class ContentFlag(BaseModel):
    """
    One automated content-scan hit (Phase 8a) - off-platform contact /
    payment info found in a profile field, a review, a verification note,
    etc. Links to a ManualReviewItem for an admin to work.
    """

    subject_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="content_flags",
        on_delete=models.CASCADE,
        help_text=_("The user whose content was flagged."),
    )
    surface = models.CharField(
        max_length=64,
        db_index=True,
        help_text=_(
            "Where the content is, e.g. 'teacher_profile.headline', 'review.text'."
        ),
    )
    object_ref = models.CharField(max_length=64, blank=True)
    categories = models.JSONField(default=list, blank=True)
    excerpt = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=12,
        choices=ContentFlagStatus.choices,
        default=ContentFlagStatus.OPEN,
        db_index=True,
    )
    review_item = models.ForeignKey(
        "trust.ManualReviewItem",
        related_name="content_flags",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Content flag")
        verbose_name_plural = _("Content flags")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["subject_user", "status"]),
        ]

    def __str__(self):
        return f"{self.surface} [{','.join(self.categories)}] ({self.status})"


class UserReportReason(models.TextChoices):
    OFF_PLATFORM = "off_platform", _("Asked to go off-platform / pay directly")
    SPAM = "spam", _("Spam or scam")
    ABUSE = "abuse", _("Abusive or inappropriate behaviour")
    IMPERSONATION = "impersonation", _("Impersonation / fake profile")
    NO_SHOW = "no_show", _("Did not show up / unreachable")
    OTHER = "other", _("Other")


class UserReportStatus(models.TextChoices):
    OPEN = "open", _("Open")
    ACTIONED = "actioned", _("Actioned")
    DISMISSED = "dismissed", _("Dismissed")


class UserReport(BaseModel):
    """One user reporting another (Phase 8d). Opens a USER_REPORT review item."""

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="reports_made",
        on_delete=models.CASCADE,
    )
    reported = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="reports_received",
        on_delete=models.CASCADE,
    )
    reason = models.CharField(max_length=16, choices=UserReportReason.choices)
    detail = models.CharField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=12,
        choices=UserReportStatus.choices,
        default=UserReportStatus.OPEN,
        db_index=True,
    )
    review_item = models.ForeignKey(
        "trust.ManualReviewItem",
        related_name="user_reports",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("User report")
        verbose_name_plural = _("User reports")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                name="user_report_not_self",
                check=~models.Q(reporter=models.F("reported")),
            ),
        ]
        indexes = [
            models.Index(fields=["reported", "status"]),
        ]

    def __str__(self):
        return f"{self.reporter_id} -> {self.reported_id} ({self.reason})"


class UserBlock(BaseModel):
    """
    ``blocker`` never wants to see or be matched with ``blocked``. Filtered
    out of each other's search results + lead distribution when
    ``TRUST_ENABLE_USER_BLOCKING`` is on (Phase 8d).
    """

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="blocks_made",
        on_delete=models.CASCADE,
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="blocks_received",
        on_delete=models.CASCADE,
    )

    class Meta:
        verbose_name = _("User block")
        verbose_name_plural = _("User blocks")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["blocker", "blocked"], name="user_block_unique_pair"
            ),
            models.CheckConstraint(
                name="user_block_not_self",
                check=~models.Q(blocker=models.F("blocked")),
            ),
        ]
        indexes = [
            models.Index(fields=["blocker"]),
            models.Index(fields=["blocked"]),
        ]

    def __str__(self):
        return f"{self.blocker_id} blocks {self.blocked_id}"


# ======================================================================
# Suspension appeals - an in-app path for a risk-suspended user to ask
# a human to re-check the suspension (plan Section 5 residual risk:
# "suspended users have no in-app appeal flow").
# ======================================================================
class SuspensionAppealStatus(models.TextChoices):
    PENDING = "pending", _("Pending review")
    IN_REVIEW = "in_review", _("Under review")
    GRANTED = "granted", _("Approved - access restored")
    DENIED = "denied", _("Declined")
    WITHDRAWN = "withdrawn", _("Withdrawn by the account holder")


class SuspensionAppeal(BaseModel):
    """
    One appeal from a risk-``suspended`` user. Filing one opens a
    ``SUSPENSION_APPEAL`` ManualReviewItem; resolving that item GRANTS the
    appeal (the user's active RiskSignals are deactivated and the risk
    score recomputed, which lifts the suspension), dismissing it DENIES it.

    Inert unless both ``TRUST_ENABLE_RISK_AUTO_ACTIONS`` (so a suspension
    can exist at all) and ``TRUST_ENABLE_SUSPENSION_APPEALS`` (so the
    in-app form is offered) are on.
    """

    OPEN_STATES = ("pending", "in_review")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="suspension_appeals",
        on_delete=models.CASCADE,
    )
    message = models.TextField(max_length=4000)
    contact_email = models.EmailField(blank=True)
    risk_score_at_submit = models.PositiveSmallIntegerField(default=0)
    risk_state_at_submit = models.CharField(max_length=12, blank=True)

    status = models.CharField(
        max_length=12,
        choices=SuspensionAppealStatus.choices,
        default=SuspensionAppealStatus.PENDING,
        db_index=True,
    )
    review_item = models.ForeignKey(
        "trust.ManualReviewItem",
        related_name="suspension_appeals",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="suspension_appeals_decided",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = _("Suspension appeal")
        verbose_name_plural = _("Suspension appeals")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"Appeal<{self.user_id}> ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATES
