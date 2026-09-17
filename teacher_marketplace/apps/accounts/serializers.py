"""
Serializers for the accounts app.

Covers:
    - RegisterSerializer         -> POST /api/v1/auth/register/
    - CustomTokenObtainPairSerializer -> POST /api/v1/auth/login/
    - ChangePasswordSerializer    -> POST /api/v1/auth/change-password/
    - ForgotPasswordSerializer    -> POST /api/v1/auth/forgot-password/
    - ResetPasswordSerializer    -> POST /api/v1/auth/reset-password/
    - LogoutSerializer            -> POST /api/v1/auth/logout/
    - UserSerializer                -> read-only representation of a User,
                                       reused by other serializers/views.

Phase 1 scope note: these serializers validate shape and field-level
rules only (uniqueness, password strength, matching confirmation
fields). Actual side effects (creating the user, sending reset
emails, verifying reset tokens) are intentionally kept in the view/
service layer, not here - serializers should describe data, not
perform actions.
"""

from django.contrib.auth import password_validation
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.authentication import SESSION_CLAIM
from apps.accounts.models import User, UserRole, UserSession
from apps.utils.validators import validate_mobile_number, validate_name


# ==========================================================
# READ-ONLY USER REPRESENTATION
# ==========================================================
class UserSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a User, used to embed user info in
    login responses and any "me" / profile-fetch endpoints. Never
    exposes the password field.
    """

    full_name = serializers.CharField(source="get_full_name", read_only=True)
    has_student_profile = serializers.BooleanField(read_only=True)
    has_teacher_profile = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "mobile",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "has_student_profile",
            "has_teacher_profile",
            "is_active",
            "is_email_verified",
            "is_mobile_verified",
            "created_at",
        )
        read_only_fields = fields


class UserNameUpdateSerializer(serializers.ModelSerializer):
    """
    Lets a signed-in user (student or teacher) change their own display
    name from `PATCH /api/v1/auth/me/`. Kept separate from
    `UserSerializer` (which is entirely read-only) since this is the one
    piece of `User` that account holder is allowed to write directly.
    """

    first_name = serializers.CharField(validators=[validate_name])
    last_name = serializers.CharField(validators=[validate_name])

    class Meta:
        model = User
        fields = ("first_name", "last_name")


class PublicUserSerializer(serializers.ModelSerializer):
    """
    Contact-safe representation of a User, for anywhere a person's
    profile is shown to *other* users (e.g. a teacher in student-facing
    search / profile). Deliberately omits email and mobile — direct
    contact details are only ever revealed through the lead-unlock flow.
    """

    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "is_email_verified",
            "is_mobile_verified",
            "created_at",
        )
        read_only_fields = fields


# ==========================================================
# REGISTER
# ==========================================================
class RegisterSerializer(serializers.ModelSerializer):
    """
    Handles new user self-registration. Restricts `role` to Student
    or Teacher only - Admin/SuperAdmin accounts must never be
    self-registerable through the public API and should only be
    created via Django Admin or a trusted internal process.
    """

    password = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
    )
    mobile = serializers.CharField(validators=[validate_mobile_number])
    first_name = serializers.CharField(validators=[validate_name])
    last_name = serializers.CharField(validators=[validate_name])

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "mobile",
            "first_name",
            "last_name",
            "role",
            "password",
            "password_confirm",
        )
        read_only_fields = ("id",)

    def validate_role(self, value):
        allowed_self_registration_roles = {UserRole.STUDENT, UserRole.TEACHER}
        if value not in allowed_self_registration_roles:
            raise serializers.ValidationError(
                "Self-registration is only allowed for Student or Teacher roles."
            )
        return value

    def validate_email(self, value):
        normalized = User.objects.normalize_email(value)
        if User.all_objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized

    def validate_mobile(self, value):
        if User.all_objects.filter(mobile=value).exists():
            raise serializers.ValidationError(
                "A user with this mobile number already exists."
            )
        return value

    def validate_password(self, value):
        # Runs Django's full AUTH_PASSWORD_VALIDATORS pipeline,
        # which now includes our PasswordStrengthValidator
        # (registered in config/settings/base.py).
        password_validation.validate_password(value)
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        return user


# ==========================================================
# LOGIN (JWT token obtain, customized)
# ==========================================================
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends SimpleJWT's default TokenObtainPairSerializer to:
        1. Use `email` as the login field (handled automatically
           since USERNAME_FIELD = "email" on our User model -
           SimpleJWT reads this from the model, no override needed
           for the field name itself).
        2. Embed basic user info + role directly in both the JWT
           claims AND the response body, so frontend clients don't
           need a second request just to know who logged in.
        3. Reject login for inactive or soft-deleted accounts with
           a clear message rather than SimpleJWT's generic error.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Custom claims embedded directly in the JWT payload itself,
        # so downstream services can trust role/user_id from the
        # token alone without an extra DB lookup.
        token["email"] = user.email
        token["role"] = user.role
        token["full_name"] = user.get_full_name()
        return token

    def validate(self, attrs):
        # Authenticates the credentials and sets self.user. The tokens
        # super() builds here are discarded - we re-issue below once the
        # login session has been (re)started, so both tokens carry the
        # right `sid` claim.
        super().validate(attrs)

        if not self.user.is_active:
            raise serializers.ValidationError(
                "This account has been deactivated. Please contact support."
            )
        if getattr(self.user, "is_deleted", False):
            raise serializers.ValidationError("This account is no longer available.")

        # Administrator accounts must go through the Super-Admin approval
        # flow (POST /api/v1/auth/admin/login/), not this endpoint.
        from django.conf import settings as dj_settings

        if self.user.role == UserRole.ADMIN and getattr(
            dj_settings, "ADMIN_LOGIN_REQUIRES_APPROVAL", True
        ):
            raise serializers.ValidationError(
                "Administrator accounts sign in through the staff approval flow."
            )

        # Start a fresh single-active session (rotates session_id, so any
        # token from a previous login on another device stops working).
        session = UserSession.start(self.user, device_info=self._device_info())

        refresh = self.get_token(self.user)
        refresh[SESSION_CLAIM] = str(session.session_id)
        access = refresh.access_token  # inherits the `sid` claim

        return {
            "refresh": str(refresh),
            "access": str(access),
            "user": UserSerializer(self.user).data,
        }

    def _device_info(self) -> str | None:
        request = self.context.get("request")
        if request is None:
            return None
        return request.META.get("HTTP_USER_AGENT")


# ==========================================================
# TOKEN REFRESH (session-aware)
# ==========================================================
class SessionAwareTokenRefreshSerializer(TokenRefreshSerializer):
    """
    Adds single-active-session enforcement to SimpleJWT's refresh flow.

    SimpleJWT already rejects an expired / malformed / bad-signature /
    blacklisted refresh token (raises TokenError -> 401). On top of that
    we require the refresh token's ``sid`` claim to match the user's
    currently-active :class:`UserSession`, so a refresh token issued
    before a logout (or before a newer login rotated the session) can no
    longer mint fresh access tokens.
    """

    def validate(self, attrs):
        # Validates signature / expiry / blacklist. Raises TokenError on
        # failure, which the view/handler turns into 401.
        refresh = RefreshToken(attrs["refresh"])

        token_sid = refresh.get(SESSION_CLAIM)
        user_id = refresh.get("user_id")
        if not token_sid or not user_id:
            raise InvalidToken("This session is no longer active. Please log in again.")

        if refresh.get("act"):
            # Impersonation refresh token — validate against ImpersonationSession.
            from apps.accounts.models import ImpersonationSession

            if ImpersonationSession.active_for(user_id, token_sid) is None:
                raise InvalidToken("This impersonation session has ended.")
        else:
            active_sid = UserSession.active_sid_for(user_id)
            if active_sid is None or str(active_sid) != str(token_sid):
                raise InvalidToken(
                    "This session is no longer active. Please log in again."
                )

        return super().validate(attrs)


# ==========================================================
# LOGOUT
# ==========================================================
class LogoutSerializer(serializers.Serializer):
    """
    Optionally accepts the refresh token to blacklist on logout. It may
    also be read from the httpOnly refresh cookie by the view, so the
    body field is not required. The blacklisting call and the session
    deactivation both happen in the view (side effects, not pure
    serialization).
    """

    refresh = serializers.CharField(required=False, allow_blank=True)


# ==========================================================
# CHANGE PASSWORD (authenticated user changes their own password)
# ==========================================================
class ChangePasswordSerializer(serializers.Serializer):
    """
    Used by an already-authenticated user to change their own
    password, given their current password for confirmation.
    """

    old_password = serializers.CharField(
        required=True, write_only=True, style={"input_type": "password"}
    )
    new_password = serializers.CharField(
        required=True, write_only=True, style={"input_type": "password"}
    )
    new_password_confirm = serializers.CharField(
        required=True, write_only=True, style={"input_type": "password"}
    )

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value, user=self.context["request"].user)
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "New passwords do not match."}
            )
        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {
                    "new_password": "New password must be different from the old password."
                }
            )
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


# ==========================================================
# SENSITIVE CONTACT CHANGES (step-up: apps.trust)
# ==========================================================
class ChangeEmailRequestSerializer(serializers.Serializer):
    """Start a change of the caller's own sign-in email."""

    new_email = serializers.EmailField(required=True)
    current_password = serializers.CharField(
        required=True, write_only=True, style={"input_type": "password"}
    )

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_email(self, value):
        return User.objects.normalize_email(value)


class ChangeMobileRequestSerializer(serializers.Serializer):
    """Start a change of the caller's own mobile number."""

    new_mobile = serializers.CharField(
        required=True, max_length=17, validators=[validate_mobile_number]
    )
    current_password = serializers.CharField(
        required=True, write_only=True, style={"input_type": "password"}
    )

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_mobile(self, value):
        return value.strip()


class SensitiveChangeConfirmSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=4, max_length=10, trim_whitespace=True)


# ==========================================================
# FORGOT PASSWORD (request a reset link/token via email)
# ==========================================================
class ForgotPasswordSerializer(serializers.Serializer):
    """
    Accepts an email address and, if a matching active account
    exists, the view will generate a reset token and (in a later
    phase) email it out. Deliberately does NOT reveal whether the
    email exists in the system, to avoid leaking account existence
    to an attacker enumerating emails.
    """

    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        # Intentionally does not raise if the email doesn't exist -
        # the view will silently no-op in that case. Raising here
        # would let an attacker enumerate registered emails.
        return User.objects.normalize_email(value)


# ==========================================================
# RESET PASSWORD (consume the token from the Forgot Password step)
# ==========================================================
class ResetPasswordSerializer(serializers.Serializer):
    """
    Consumes a uidb64 + token pair (Django's standard password
    reset token scheme, the same mechanism Django's own built-in
    password reset views use) along with a new password.
    """

    uidb64 = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(
        required=True, write_only=True, style={"input_type": "password"}
    )
    new_password_confirm = serializers.CharField(
        required=True, write_only=True, style={"input_type": "password"}
    )

    default_error_messages = {
        "invalid_token": "The password reset link is invalid or has expired.",
    }

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "Passwords do not match."}
            )

        user = self._get_user(attrs["uidb64"])
        if user is None:
            raise serializers.ValidationError(
                {"uidb64": self.default_error_messages["invalid_token"]}
            )

        token_generator = PasswordResetTokenGenerator()
        if not token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError(
                {"token": self.default_error_messages["invalid_token"]}
            )

        password_validation.validate_password(attrs["new_password"], user=user)

        attrs["user"] = user
        return attrs

    @staticmethod
    def _get_user(uidb64: str):
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            return User.all_objects.get(pk=uid)
        except (
            TypeError,
            ValueError,
            OverflowError,
            User.DoesNotExist,
            ValidationError,
        ):
            return None

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user
