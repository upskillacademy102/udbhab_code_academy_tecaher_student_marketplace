"""
User model for the Teacher Marketplace Platform.

Design notes:
    - Email is the login identifier (USERNAME_FIELD), not a
      separate username field - simpler UX and matches how most
      modern marketplaces authenticate users.
    - Role is a single field with four choices (Student, Teacher,
      Admin, SuperAdmin) rather than four separate proxy models -
      simplest correct design for Phase 1. Role-specific profile
      data (bio, qualifications, etc.) lives in the Student/Teacher
      apps' own models, linked back to this User via a
      OneToOneField, keeping this model focused purely on
      authentication/identity concerns.
    - Inherits from apps.common.models.BaseModel, so User already
      has: UUID primary key, created_at/updated_at, soft-delete
      (is_deleted/deleted_at), and created_by/updated_by audit
      fields - though created_by/updated_by will typically be
      null for self-registered users.
"""

import uuid

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.utils.validators import validate_mobile_number, validate_name


class UserRole(models.TextChoices):
    """
    Enumerates the four roles supported by the platform. Stored as
    a plain CharField choice (not a separate table) since roles are
    a small, fixed, rarely-changing set - a full RBAC/permissions
    table would be over-engineering for this platform's needs.
    """

    STUDENT = "student", _("Student")
    TEACHER = "teacher", _("Teacher")
    ADMIN = "admin", _("Admin")
    SUPERADMIN = "superadmin", _("Super Admin")


class UserManager(BaseUserManager):
    """
    Custom manager required whenever USERNAME_FIELD is changed away
    from Django's default 'username' - Django's manager needs to
    know how to create regular users and superusers using email
    instead.
    """

    use_in_migrations = True

    def _create_user(self, email: str, password: str, **extra_fields):
        if not email:
            raise ValueError(_("The Email field must be set."))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", UserRole.STUDENT)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.SUPERADMIN)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    """
    Custom User model, combining:
        - AbstractBaseUser: password hashing, last_login, core auth
          machinery, without Django's default username field.
        - PermissionsMixin: is_superuser, groups, user_permissions -
          required for Django Admin's permission system to work.
        - BaseModel (apps.common): UUID PK, timestamps, soft-delete,
          audit fields.

    Note on MRO/field ordering: BaseModel provides `id` as a UUID
    PK, which overrides AbstractBaseUser's implicit integer PK.
    Django resolves this correctly because BaseModel's UUIDField
    is explicitly named `id`, matching what AbstractBaseUser expects
    to be the primary key field name.
    """

    email = models.EmailField(
        _("email address"),
        unique=True,
        db_index=True,
        error_messages={
            "unique": _("A user with that email already exists."),
        },
    )
    mobile = models.CharField(
        _("mobile number"),
        max_length=17,
        unique=True,
        validators=[validate_mobile_number],
        help_text=_("Mobile number with country code, e.g. +919876543210."),
    )
    first_name = models.CharField(
        _("first name"),
        max_length=150,
        validators=[validate_name],
    )
    last_name = last_name = models.CharField(
        _("last name"),
        max_length=150,
        validators=[validate_name],
    )
    role = models.CharField(
        _("role"),
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.STUDENT,
        db_index=True,
    )

    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into the Django Admin site."),
    )
    is_email_verified = models.BooleanField(
        _("email verified"),
        default=False,
        help_text=_("Whether the user has verified their email address."),
    )
    is_mobile_verified = models.BooleanField(
        _("mobile verified"),
        default=False,
        help_text=_("Whether the user has verified their mobile number."),
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["mobile", "first_name", "last_name"]

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["role", "is_active"]),
        ]

    def __str__(self):
        return f"{self.get_full_name()} ({self.email})"

    def get_full_name(self):
        """Returns the first_name plus the last_name, with a space in between."""
        full_name = f"{self.first_name} {self.last_name}"
        return full_name.strip()

    def get_short_name(self):
        """Returns the short name (first name) for the user."""
        return self.first_name

    @property
    def is_student(self) -> bool:
        return self.role == UserRole.STUDENT

    @property
    def is_teacher(self) -> bool:
        return self.role == UserRole.TEACHER

    @property
    def is_admin_role(self) -> bool:
        """
        Named is_admin_role (not is_admin) to avoid any confusion
        with Django's own is_staff/is_superuser semantics - this
        strictly reflects our own `role` field.
        """
        return self.role == UserRole.ADMIN

    @property
    def is_superadmin_role(self) -> bool:
        return self.role == UserRole.SUPERADMIN

    @property
    def is_platform_staff(self) -> bool:
        """
        True for Admin or Super Admin - i.e. anyone who manages the
        platform rather than transacting on it. Used where a list
        endpoint is shared between a consumer view (active rows only)
        and an admin management view (every row, incl. deactivated).
        """
        return self.role in (UserRole.ADMIN, UserRole.SUPERADMIN)

    @property
    def has_student_profile(self) -> bool:
        """
        Whether a Student row exists for this user, independent of
        `role` - `role` is which portal is currently active, this is
        which profiles actually exist. A user can hold both a Student
        and a Teacher row at once (see apps.accounts.role_switch).
        """
        return hasattr(self, "student_profile")

    @property
    def has_teacher_profile(self) -> bool:
        return hasattr(self, "teacher_profile")


class UserSession(BaseModel):
    """
    Tracks the single currently-active session per User. A new
    login overwrites session_id (invalidating any tokens issued
    under the previous session_id instantly, without needing the
    old device to explicitly log out - satisfies "one active
    session per account, new login auto-invalidates the old one").
    Logout sets is_active=False, which invalidates the CURRENT
    session's access tokens immediately too, not just the refresh
    token (SimpleJWT's blacklist alone only covers refresh tokens -
    access tokens are stateless JWTs that would otherwise remain
    valid until natural expiry after logout).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="session",
        on_delete=models.CASCADE,
    )
    session_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    device_info = models.CharField(max_length=255, null=True, blank=True)
    last_used_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Session"
        verbose_name_plural = "User Sessions"

    def __str__(self):
        return f"Session for {self.user.email} ({'active' if self.is_active else 'inactive'})"

    def rotate(self, device_info: str = None):
        """
        Called on every new login. Generates a fresh session_id and
        marks the session active. Any access/refresh token minted
        under the previous session_id is instantly rejected by
        apps.accounts.authentication.SessionAwareJWTAuthentication
        (its `sid` claim no longer matches), so a login on a new
        device silently logs out the old one.
        """
        self.session_id = uuid.uuid4()
        self.is_active = True
        if device_info is not None:
            self.device_info = device_info[:255]
        self.save(
            update_fields=["session_id", "is_active", "device_info", "updated_at"]
        )

    def deactivate(self):
        """
        Called on logout. Flips is_active to False, which immediately
        invalidates the CURRENT session's access tokens too (not just
        the blacklisted refresh token) - SimpleJWT's blacklist alone
        only covers refresh tokens.
        """
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])

    @classmethod
    def start(cls, user, device_info: str = None) -> "UserSession":
        """
        Get-or-create this user's single session row and rotate it -
        the one call a login view needs. Returns the active session
        carrying the new session_id.
        """
        session, _ = cls.objects.get_or_create(user=user)
        session.rotate(device_info=device_info)
        return session

    @classmethod
    def active_sid_for(cls, user_id) -> "uuid.UUID | None":
        """
        The session_id of the user's currently-active session, or
        None if they have no session or it has been deactivated.
        Used by the authentication layer to validate a token's `sid`.
        """
        row = (
            cls.objects.filter(user_id=user_id, is_active=True)
            .values_list("session_id", flat=True)
            .first()
        )
        return row


def _default_impersonation_expiry():
    from datetime import timedelta

    from django.utils import timezone

    return timezone.now() + timedelta(minutes=settings.IMPERSONATION_TTL_MINUTES)


class ImpersonationSession(BaseModel):
    """
    A Super Admin acting as another user. Kept separate from
    ``UserSession`` so impersonating someone does NOT disturb their
    real session (they stay logged in on their own device). The
    impersonation access token carries ``act`` (impersonator id) and
    ``sid`` = this row's ``session_id``; the auth layer validates it
    against this table instead of ``UserSession``.
    """

    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="impersonated_sessions",
        on_delete=models.CASCADE,
    )
    impersonator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="impersonations_started",
        on_delete=models.CASCADE,
    )
    session_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    reason = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(default=_default_impersonation_expiry)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Impersonation session"
        verbose_name_plural = "Impersonation sessions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.impersonator_id} as {self.target_user_id}"

    def is_valid(self):
        from django.utils import timezone

        return self.is_active and self.expires_at > timezone.now()

    def end(self):
        from django.utils import timezone

        self.is_active = False
        self.ended_at = timezone.now()
        self.save(update_fields=["is_active", "ended_at", "updated_at"])

    @classmethod
    def active_for(cls, target_user_id, session_id):
        from django.utils import timezone

        return (
            cls.objects.filter(
                target_user_id=target_user_id,
                session_id=session_id,
                is_active=True,
                expires_at__gt=timezone.now(),
            )
            .select_related("impersonator")
            .first()
        )


class AdminLoginRequest(BaseModel):
    """
    A pending request for an ``admin``-role account to obtain a
    session. Requires an active Super Admin to approve it before the
    admin can poll for tokens (``settings.ADMIN_LOGIN_REQUIRES_APPROVAL``).
    Super Admin login is direct — bootstrapped via ``createsuperuser``.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        DENIED = "denied"
        EXPIRED = "expired"
        CONSUMED = "consumed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="admin_login_requests",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    poll_token = models.CharField(max_length=64, db_index=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)
    requested_user_agent = models.CharField(max_length=400, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="admin_logins_reviewed",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        verbose_name = "Admin login request"
        verbose_name_plural = "Admin login requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} — {self.status}"

    def is_expired(self):
        from django.utils import timezone

        return self.expires_at <= timezone.now()
