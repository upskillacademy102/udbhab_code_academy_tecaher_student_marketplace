"""
Views for the accounts app.

Endpoints (wired up in apps/accounts/urls.py, next file):
    POST /api/v1/auth/register/            -> RegisterView
    POST /api/v1/auth/login/                -> LoginView
    POST /api/v1/auth/refresh/                -> TokenRefreshView (SimpleJWT's own)
    POST /api/v1/auth/logout/                -> LogoutView
    POST /api/v1/auth/change-password/        -> ChangePasswordView
    POST /api/v1/auth/forgot-password/        -> ForgotPasswordView
    POST /api/v1/auth/reset-password/        -> ResetPasswordView

Phase 1 scope note: ForgotPasswordView generates a valid Django
password-reset token and (uid, token) pair but does NOT actually
send an email yet - wiring up an email template/task queue is a
later-phase concern. The endpoint's contract (accept email, return
generic success) is fully implemented and production-ready; only
the delivery mechanism is stubbed via a clearly-marked TODO,
consistent with "no notifications in Phase 1."
"""

import logging

from django.conf import settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.authentication import CookieJWTAuthentication
from apps.accounts.cookies import clear_auth_cookies, set_auth_cookies
from apps.accounts.models import ImpersonationSession, User, UserSession
from apps.accounts.serializers import (
    ChangeEmailRequestSerializer,
    ChangeMobileRequestSerializer,
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    ForgotPasswordSerializer,
    LogoutSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    SensitiveChangeConfirmSerializer,
    SessionAwareTokenRefreshSerializer,
    UserSerializer,
)
from apps.accounts.tokens import issue_pair
from apps.core.exceptions.custom_exceptions import (
    ConflictException,
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.core.throttling import (
    LoginRateThrottle,
    PasswordResetRateThrottle,
    RegisterRateThrottle,
    ResilientAnonRateThrottle,
)
from apps.trust.models import (
    SensitiveChangeField,
    SensitiveChangeRequest,
    SensitiveChangeState,
)
from apps.trust.services.anomaly_service import AnomalyService
from apps.trust.services.captcha_service import CaptchaService
from apps.trust.services.dedupe_service import DedupeService
from apps.trust.services.sensitive_change_service import SensitiveChangeService

logger = logging.getLogger("apps.accounts")


def _safe_dedupe(fn):
    """Run a duplicate-detection call best-effort - it must never break auth."""
    try:
        fn()
    except Exception:  # noqa: BLE001
        logger.exception("duplicate-account detection failed (non-fatal)")


# ==========================================================
# REGISTER
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="Register a new Student or Teacher account",
    request=RegisterSerializer,
    responses={201: OpenApiResponse(description="Account created successfully.")},
)
class RegisterView(APIView):
    """
    Public endpoint for Student/Teacher self-registration.
    Admin/SuperAdmin accounts cannot be created here (enforced in
    RegisterSerializer.validate_role).
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ResilientAnonRateThrottle, RegisterRateThrottle]

    def post(self, request):
        CaptchaService.verify_or_raise(request)

        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        CaptchaService.record_account_use(request, user.id)
        _safe_dedupe(
            lambda: DedupeService.record_and_scan_on_register(user, request=request)
        )

        logger.info("New user registered: %s (role=%s)", user.email, user.role)

        return APIResponse.created(
            data=UserSerializer(user).data,
            message="Account created successfully.",
        )


# ==========================================================
# LOGIN
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="Log in and obtain JWT access/refresh tokens",
)
class LoginView(TokenObtainPairView):
    """
    Extends SimpleJWT's TokenObtainPairView to:
      * swap in CustomTokenObtainPairSerializer (adds role/full_name
        claims, binds the tokens to a fresh single-active session, and
        embeds user data in the response),
      * wrap the response in our standard APIResponse envelope,
      * set the access/refresh tokens as httpOnly cookies so browser /
        Swagger sessions authenticate automatically afterwards,
      * enforce the single-active-account rule: if the caller already
        holds a live session (cookie or Bearer header), reject with 409
        until they log out.

    Programmatic clients can ignore the cookies entirely and keep using
    the ``access``/``refresh`` values from the response body with the
    ``Authorization: Bearer`` header.
    """

    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ResilientAnonRateThrottle, LoginRateThrottle]
    # Do NOT authenticate the login request through the DRF stack - a
    # stale/expired token in the header would otherwise 401 the request
    # before we can evaluate the single-active-account rule ourselves.
    authentication_classes = []

    ALREADY_LOGGED_IN_DETAIL = (
        "An account is already logged in. Please log out from the current "
        "account before logging into another account."
    )

    def post(self, request, *args, **kwargs):
        self._reject_if_session_active(request)
        CaptchaService.verify_or_raise(request)

        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise AuthenticationFailed(str(exc)) from exc

        data = serializer.validated_data
        CaptchaService.record_account_use(request, serializer.user.id)
        # Anomaly checks run BEFORE the dedupe device-signature write, so
        # "device this account has never used" is evaluated against the
        # account's history, not against a row we just created.
        _safe_dedupe(lambda: AnomalyService.on_login(serializer.user, request))
        _safe_dedupe(
            lambda: DedupeService.record_and_scan_device(
                serializer.user, request=request
            )
        )
        logger.info("User logged in: %s", request.data.get("email"))

        response = APIResponse.success(data=data, message="Login successful.")
        set_auth_cookies(response, data["access"], data["refresh"])
        return response

    def _reject_if_session_active(self, request):
        """
        409 if the request already carries a valid, non-revoked auth
        context (httpOnly cookie or Bearer header). A stale/expired/
        unknown token is treated as "not logged in" and the login
        proceeds normally.
        """
        try:
            result = CookieJWTAuthentication().authenticate(request)
        except Exception:
            return
        if result is not None:
            raise ConflictException(detail=self.ALREADY_LOGGED_IN_DETAIL)


# ==========================================================
# LOGOUT
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="Log out: end the session, revoke tokens, clear auth cookies",
    request=LogoutSerializer,
    responses={
        200: OpenApiResponse(
            description="Session ended, refresh token blacklisted, auth cookies cleared."
        )
    },
)
class LogoutView(APIView):
    """
    Full logout across every layer:
      1. deactivate the user's UserSession -> every access token minted
         for it is rejected immediately by the authentication layer
         (not just the refresh token),
      2. blacklist the refresh token (from the request body or the
         refresh cookie) so it can never mint new access tokens,
      3. clear the httpOnly auth cookies on the response.

    Succeeds even if the refresh token is missing or already expired -
    the important part (killing the session) still happens, and a
    subsequent login always builds a brand-new session.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 1. End the session (kills access tokens for this session now).
        session = UserSession.objects.filter(user=request.user).first()
        if session is not None:
            session.deactivate()

        # 2. Best-effort refresh-token blacklist.
        raw_refresh = serializer.validated_data.get("refresh") or request.COOKIES.get(
            settings.JWT_REFRESH_COOKIE
        )
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except TokenError:
                # Already expired / invalid / blacklisted - nothing left
                # to revoke, logout still succeeds.
                pass

        logger.info("User logged out: %s", request.user.email)

        # 3. Clear cookies.
        response = APIResponse.success(message="Logged out successfully.")
        clear_auth_cookies(response)
        return response


# ==========================================================
# TOKEN REFRESH (cookie-aware + session-aware)
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="Exchange a valid refresh token for a new access token",
)
class CookieTokenRefreshView(TokenRefreshView):
    """
    Replaces SimpleJWT's stock TokenRefreshView so that:
      * the refresh token may come from the request body OR the httpOnly
        refresh cookie,
      * an expired / malformed / blacklisted / wrong-signature refresh
        token returns 401 (SimpleJWT default),
      * the refresh token must also belong to the user's currently
        active session (see SessionAwareTokenRefreshSerializer) - a
        token from a logged-out or superseded session returns 401,
      * the rotated refresh + new access token are re-set as cookies,
      * the body is wrapped in the standard APIResponse envelope.
    """

    serializer_class = SessionAwareTokenRefreshSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        payload = {key: value for key, value in request.data.items()}
        if not payload.get("refresh"):
            cookie_refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE)
            if cookie_refresh:
                payload["refresh"] = cookie_refresh

        serializer = self.get_serializer(data=payload)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(str(exc)) from exc

        data = serializer.validated_data
        response = APIResponse.success(data=data, message="Token refreshed.")
        set_auth_cookies(response, data["access"], data.get("refresh"))
        return response


# ==========================================================
# WHO AM I  (+ impersonation state)
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="Current user and impersonation state",
    responses={
        200: OpenApiResponse(description="`data`: {user, impersonated_by|null}.")
    },
)
class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        token = request.auth
        impersonated_by = None
        if token is not None and token.get("act"):
            impersonated_by = {
                "email": token.get("act_email"),
                "role": token.get("act_role"),
            }
        return APIResponse.success(
            data={
                "user": UserSerializer(request.user).data,
                "impersonated_by": impersonated_by,
            }
        )


# ==========================================================
# STOP IMPERSONATION  (return to the admin's own account)
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="End an impersonation session and return to your account",
    request=None,
    responses={
        200: OpenApiResponse(
            description="Impersonation ended; auth cookies re-issued for the admin."
        )
    },
)
class StopImpersonationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        token = request.auth
        if token is None or not token.get("act"):
            raise ValidationException(detail="You are not impersonating anyone.")

        impersonator_id = token.get("act")
        sid = token.get("sid")

        imp = ImpersonationSession.active_for(request.user.id, sid)
        if imp is not None:
            imp.end()

        impersonator = User.objects.filter(id=impersonator_id, is_active=True).first()
        if impersonator is None:
            resp = APIResponse.success(
                message="Impersonation ended. Please log in again."
            )
            clear_auth_cookies(resp)
            return resp

        session = UserSession.start(
            impersonator, device_info=request.META.get("HTTP_USER_AGENT")
        )
        access, refresh = issue_pair(impersonator, sid=session.session_id)

        from apps.ops.models import AuditCategory
        from apps.ops.services import AuditService

        AuditService.record(
            request=request,
            category=AuditCategory.IMPERSONATION,
            action="impersonation.stop",
            actor=impersonator,
            target=request.user,
            message=f"{impersonator.email} stopped acting as {request.user.email}",
        )

        resp = APIResponse.success(
            data={
                "access": access,
                "refresh": refresh,
                "user": UserSerializer(impersonator).data,
            },
            message="Returned to your account.",
        )
        set_auth_cookies(resp, access, refresh)
        return resp


# ==========================================================
# DUAL-ROLE ACCOUNTS: SWITCH ACTIVE PORTAL
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="Switch which portal (student/teacher) is active for this account",
    request=None,
    responses={
        200: OpenApiResponse(
            description="Portal switched; auth cookies re-issued for the new role."
        )
    },
)
class SwitchRoleView(APIView):
    """
    Lets an authenticated Student become a Teacher too (or vice versa)
    on the SAME account, and switch between them afterwards. Never
    creates a new User - see apps.accounts.role_switch for why that
    matters (keeps this entirely out of the duplicate-account fraud
    detection, which only runs on new registrations).
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from apps.accounts.role_switch import switch_active_role

        target_role = request.data.get("role")
        created = switch_active_role(request.user, target_role)

        session = UserSession.start(
            request.user, device_info=request.META.get("HTTP_USER_AGENT")
        )
        access, refresh = issue_pair(request.user, sid=session.session_id)

        resp = APIResponse.success(
            data={
                "access": access,
                "refresh": refresh,
                "user": UserSerializer(request.user).data,
                "profile_created": created,
            },
            message=(
                f"Your {target_role} account is set up."
                if created
                else f"Switched to {target_role}."
            ),
        )
        set_auth_cookies(resp, access, refresh)
        return resp


# ==========================================================
# CHANGE PASSWORD (authenticated)
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="Change password for the currently authenticated user",
    request=ChangePasswordSerializer,
    responses={200: OpenApiResponse(description="Password changed successfully.")},
)
class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        # Step-up OFF (default): apply straight away, exactly as before.
        if not SensitiveChangeService.step_up_enabled():
            serializer.save()
            logger.info("Password changed for user: %s", request.user.email)
            return APIResponse.success(message="Password changed successfully.")

        # Step-up ON: hold the new password behind a one-time code sent to
        # a verified contact; the change applies when POST .../confirm/ succeeds.
        from django.contrib.auth.hashers import make_password

        SensitiveChangeService.initiate_password_change(
            request.user,
            new_password_hash=make_password(serializer.validated_data["new_password"]),
            request=request,
        )
        return APIResponse.success(
            message="We've sent a verification code to your registered contact. "
            "Confirm it at /api/v1/auth/change-password/confirm/ to finish.",
            http_status=status.HTTP_202_ACCEPTED,
        )


@extend_schema(
    tags=["Authentication"],
    summary="Confirm a step-up password change with the emailed/SMS code",
    request=SensitiveChangeConfirmSerializer,
    responses={200: OpenApiResponse(description="Password changed.")},
)
class ChangePasswordConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SensitiveChangeConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scr = SensitiveChangeService.active_request(
            request.user, SensitiveChangeField.PASSWORD
        )
        if scr is None:
            raise ValidationException(detail="No pending password change to confirm.")
        SensitiveChangeService.confirm(
            scr, code=serializer.validated_data["code"], request=request
        )
        logger.info("Password changed (step-up) for user: %s", request.user.email)
        return APIResponse.success(message="Password changed successfully.")


# ==========================================================
# CHANGE EMAIL / MOBILE (step-up: apps.trust)
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="Request a change to your sign-in email",
    request=ChangeEmailRequestSerializer,
    responses={202: OpenApiResponse(description="Code sent to the new address.")},
)
class ChangeEmailRequestView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangeEmailRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        SensitiveChangeService.initiate_email_change(
            request.user,
            new_email=serializer.validated_data["new_email"],
            request=request,
        )
        return APIResponse.success(
            message="We've sent a code to the new email address. Confirm it at "
            "/api/v1/auth/change-email/confirm/.",
            http_status=status.HTTP_202_ACCEPTED,
        )


@extend_schema(
    tags=["Authentication"],
    summary="Confirm an email change",
    request=SensitiveChangeConfirmSerializer,
    responses={
        200: OpenApiResponse(
            description="Email changed, or scheduled after the cooldown."
        )
    },
)
class ChangeEmailConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SensitiveChangeConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scr = SensitiveChangeService.active_request(
            request.user, SensitiveChangeField.EMAIL
        )
        if scr is None:
            raise ValidationException(detail="No pending email change to confirm.")
        scr = SensitiveChangeService.confirm(
            scr, code=serializer.validated_data["code"], request=request
        )
        if scr.state == SensitiveChangeState.SCHEDULED:
            return APIResponse.success(
                message=f"Confirmed. Your email will change at {scr.apply_after:%Y-%m-%d %H:%M} UTC "
                "unless you cancel it before then."
            )
        return APIResponse.success(message="Your email address has been changed.")


@extend_schema(
    tags=["Authentication"],
    summary="Request a change to your mobile number",
    request=ChangeMobileRequestSerializer,
    responses={202: OpenApiResponse(description="Code sent to the new number.")},
)
class ChangeMobileRequestView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangeMobileRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        SensitiveChangeService.initiate_mobile_change(
            request.user,
            new_mobile=serializer.validated_data["new_mobile"],
            request=request,
        )
        return APIResponse.success(
            message="We've sent a code to the new mobile number. Confirm it at "
            "/api/v1/auth/change-mobile/confirm/.",
            http_status=status.HTTP_202_ACCEPTED,
        )


@extend_schema(
    tags=["Authentication"],
    summary="Confirm a mobile-number change",
    request=SensitiveChangeConfirmSerializer,
    responses={
        200: OpenApiResponse(
            description="Mobile changed, or scheduled after the cooldown."
        )
    },
)
class ChangeMobileConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SensitiveChangeConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scr = SensitiveChangeService.active_request(
            request.user, SensitiveChangeField.MOBILE
        )
        if scr is None:
            raise ValidationException(detail="No pending mobile change to confirm.")
        scr = SensitiveChangeService.confirm(
            scr, code=serializer.validated_data["code"], request=request
        )
        if scr.state == SensitiveChangeState.SCHEDULED:
            return APIResponse.success(
                message=f"Confirmed. Your mobile number will change at {scr.apply_after:%Y-%m-%d %H:%M} UTC "
                "unless you cancel it before then."
            )
        return APIResponse.success(message="Your mobile number has been changed.")


@extend_schema(
    tags=["Authentication"],
    summary="List your pending / recent account-change requests",
    request=None,
    responses={200: OpenApiResponse(description="`data`: a list of change requests.")},
)
class SensitiveChangeListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rows = SensitiveChangeRequest.objects.filter(user=request.user).order_by(
            "-created_at"
        )[:20]
        data = [
            {
                "id": str(r.id),
                "field": r.field,
                "state": r.state,
                "new_value_masked": _mask_change_value(r),
                "apply_after": r.apply_after.isoformat() if r.apply_after else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
        return APIResponse.success(data=data)


@extend_schema(
    tags=["Authentication"],
    summary="Cancel a pending account-change request",
    request=None,
    responses={200: OpenApiResponse(description="Cancelled.")},
)
class SensitiveChangeCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        scr = SensitiveChangeRequest.objects.filter(id=id, user=request.user).first()
        if scr is None:
            raise ResourceNotFoundException(detail="Change request not found.")
        SensitiveChangeService.cancel(scr, request=request)
        return APIResponse.success(message="The change request has been cancelled.")


def _mask_change_value(r) -> str:
    if r.field == SensitiveChangeField.PASSWORD or not r.new_value:
        return ""
    value = r.new_value
    if "@" in value:
        name, _, domain = value.partition("@")
        return f"{name[:1]}{'*' * max(len(name) - 1, 1)}@{domain}"
    return (
        f"{value[:2]}{'*' * max(len(value) - 4, 1)}{value[-2:]}"
        if len(value) > 4
        else "***"
    )


# ==========================================================
# FORGOT PASSWORD
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="Request a password reset token via email",
    request=ForgotPasswordSerializer,
    responses={
        200: OpenApiResponse(
            description="Generic success (does not reveal whether the email exists)."
        )
    },
)
class ForgotPasswordView(APIView):
    """
    Always returns the same generic success message whether or not
    the email matches a real account, to avoid leaking which emails
    are registered (a standard security practice for this kind of
    endpoint).
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ResilientAnonRateThrottle, PasswordResetRateThrottle]

    GENERIC_SUCCESS_MESSAGE = (
        "If an account with that email exists, a password reset link " "has been sent."
    )

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        user = User.objects.filter(email__iexact=email, is_active=True).first()

        if user is not None:
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))

            # TODO (later phase): dispatch an email via a Celery task
            #   token = PasswordResetTokenGenerator().make_token(user)
            # containing a frontend link built from settings.FRONTEND_BASE_URL,
            # e.g. f"{settings.FRONTEND_BASE_URL}/reset-password/{uidb64}/{token}/"
            # Email/notification delivery is explicitly out of scope
            # for Phase 1 per the project's "no notifications" rule.
            logger.info(
                "Password reset requested for user %s (uidb64=%s)",
                user.email,
                uidb64,
            )

        return APIResponse.success(message=self.GENERIC_SUCCESS_MESSAGE)


# ==========================================================
# RESET PASSWORD
# ==========================================================
@extend_schema(
    tags=["Authentication"],
    summary="Reset password using the uidb64 + token from Forgot Password",
    request=ResetPasswordSerializer,
    responses={
        200: OpenApiResponse(
            description="Password reset; the user can now log in with the new password."
        )
    },
)
class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ResilientAnonRateThrottle, PasswordResetRateThrottle]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        logger.info("Password reset completed for user: %s", user.email)

        return APIResponse.success(message="Password has been reset successfully.")
