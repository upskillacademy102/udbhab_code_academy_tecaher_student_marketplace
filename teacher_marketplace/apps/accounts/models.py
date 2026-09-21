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
from django.utils.text import slugify
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

    admin_account_name = models.CharField(
        _("admin account name"),
        max_length=190,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text=_(
            "Login identifier for role=admin accounts created via the "
            "self-service admin-account-request flow, e.g. 'RajuDas@Finance'. "
            "Null for every other role, and for admin accounts that predate "
            "this flow (they keep signing in the old, email-based way)."
        ),
    )
    admin_department = models.ForeignKey(
        "accounts.AdminDepartment",
        verbose_name=_("admin department"),
        related_name="admins",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=_("Department this admin was assigned when approved. Null for non-admins."),
    )
    has_seen_admin_credentials_notice = models.BooleanField(
        _("has seen admin credentials notice"),
        default=False,
        help_text=_(
            "Flips to True the first time this admin successfully signs in "
            "via the admin login page - after that, the one-time "
            "account-name-and-password reveal is never shown again."
        ),
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


class AdminDepartment(BaseModel):
    """
    Reference data for where an approved admin sits, e.g. Finance, Support.
    Same shape/soft-delete pattern as ``apps.subjects.Subject`` - picked from
    a fixed list at admin-approval time (never free-typed), and named (not
    hard-deleted) so historical ``User.admin_account_name`` values that
    reference it stay meaningful.
    """

    name = models.CharField(_("name"), max_length=80, unique=True, db_index=True)
    slug = models.SlugField(_("slug"), max_length=90, unique=True, blank=True)
    is_active = models.BooleanField(_("is active"), default=True, db_index=True)

    class Meta:
        verbose_name = _("Admin department")
        verbose_name_plural = _("Admin departments")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def canonical_name(self) -> str:
        """Space-stripped form used in a generated admin account name,
        e.g. 'Content Moderation' -> 'ContentModeration'."""
        return "".join(self.name.split())


class AdminAccountRequestStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    APPROVED = "approved", _("Approved")
    DENIED = "denied", _("Denied")


class AdminAccountRequest(BaseModel):
    """
    A self-service request to become an Admin. Distinct from
    ``AdminLoginRequest`` (which gates a single *login attempt* for an
    admin who already exists) - this gates *account creation itself*.

    No ``User`` row exists for this request until it is approved: the
    requester's details plus their chosen password are held here in
    ``pending`` status. Approving is a single atomic action
    (``apps.accounts.services.admin_account_naming.approve_and_create_admin``)
    that creates the ``User`` with role=admin, a department, and a generated
    ``admin_account_name`` all at once - there is no partial state where a
    ``User`` exists but is unapproved, and no way to approve without also
    assigning a department.
    """

    email = models.EmailField(_("email address"), db_index=True)
    mobile = models.CharField(
        _("mobile number"), max_length=17, validators=[validate_mobile_number]
    )
    first_name = models.CharField(
        _("first name"), max_length=150, validators=[validate_name]
    )
    last_name = models.CharField(
        _("last name"), max_length=150, validators=[validate_name]
    )
    # Hashed with django.contrib.auth.hashers.make_password the moment the
    # request is submitted - never stored or logged in plaintext, not even
    # for the duration of the request. Copied verbatim (not re-hashed) onto
    # the created User's `password` field on approval.
    password_hash = models.CharField(_("password hash"), max_length=255)

    status = models.CharField(
        _("status"),
        max_length=10,
        choices=AdminAccountRequestStatus.choices,
        default=AdminAccountRequestStatus.PENDING,
        db_index=True,
    )
    department = models.ForeignKey(
        "accounts.AdminDepartment",
        verbose_name=_("department"),
        related_name="account_requests",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=_("Set only at approval time, together with status=approved."),
    )
    created_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("created user"),
        related_name="admin_account_request",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("The User row created on approval. Null while pending/denied."),
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("reviewed by"),
        related_name="admin_account_requests_reviewed",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True)
    deny_reason = models.CharField(_("deny reason"), max_length=500, blank=True)
    requested_ip = models.GenericIPAddressField(
        _("requested ip"), null=True, blank=True
    )
    requested_user_agent = models.CharField(
        _("requested user agent"), max_length=400, blank=True
    )

    class Meta:
        verbose_name = _("Admin account request")
        verbose_name_plural = _("Admin account requests")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"{self.email} ({self.status})"
