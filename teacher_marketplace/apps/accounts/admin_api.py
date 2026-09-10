"""
Privileged account APIs:

  User directory / management  (/api/v1/admin/users/...)
      GET    /                      list + filter          (admin, superadmin)
      POST   /                      create user            (superadmin; admin -> student/teacher only)
      GET    /{id}/                 detail                 (admin, superadmin)
      PATCH  /{id}/                 update                 (superadmin)
      POST   /{id}/activate/        reactivate             (superadmin)
      POST   /{id}/deactivate/      deactivate + kill session (superadmin)
      POST   /{id}/impersonate/     start "act as user"    (superadmin)

  Admin-login approval  (/api/v1/auth/admin/...)
      POST   /login/                        admin submits creds -> pending request (public)
      GET    /login/{id}/status/?token=     admin polls; issues tokens once approved (public)
      GET    /login-requests/               pending + recent           (superadmin)
      POST   /login-requests/{id}/approve/  (superadmin)
      POST   /login-requests/{id}/deny/     (superadmin)

Every state change is written to the audit log.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.accounts.cookies import set_auth_cookies
from apps.accounts.models import (
    AdminLoginRequest,
    ImpersonationSession,
    User,
    UserRole,
    UserSession,
)
from apps.accounts.tokens import issue_pair
from apps.core.exceptions.custom_exceptions import (
    PermissionDeniedException,
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.core.throttling import AdminLoginRateThrottle, ResilientAnonRateThrottle
from apps.ops.models import AuditCategory, AuditStatus
from apps.ops.services import AuditService
from apps.trust.services.captcha_service import CaptchaService
from apps.utils.validators import validate_mobile_number, validate_name

_CREATABLE_BY_ADMIN = {UserRole.STUDENT, UserRole.TEACHER}


def _normalise_name(value):
    """Trim + collapse internal whitespace on a name field."""
    if not isinstance(value, str):
        return value
    return " ".join(value.split())


# ======================================================================
# Serializers
# ======================================================================
class AdminUserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    has_active_session = serializers.SerializerMethodField()
    profile_type = serializers.SerializerMethodField()

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
            "is_active",
            "is_staff",
            "is_email_verified",
            "is_mobile_verified",
            "has_active_session",
            "profile_type",
            "last_login",
            "created_at",
        )
        read_only_fields = fields

    def get_has_active_session(self, obj) -> bool:
        return UserSession.objects.filter(user=obj, is_active=True).exists()

    def get_profile_type(self, obj) -> str:
        if hasattr(obj, "student"):
            return "student"
        if hasattr(obj, "teacher"):
            return "teacher"
        return None


class AdminUserCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    mobile = serializers.CharField(max_length=17, validators=[validate_mobile_number])
    first_name = serializers.CharField(max_length=150, validators=[validate_name])
    last_name = serializers.CharField(max_length=150, validators=[validate_name])
    role = serializers.ChoiceField(choices=UserRole.choices)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_email(self, value):
        v = User.objects.normalize_email(value)
        if User.all_objects.filter(email__iexact=v).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return v

    def validate_mobile(self, value):
        value = value.strip()
        if User.all_objects.filter(mobile=value).exists():
            raise serializers.ValidationError(
                "A user with this mobile number already exists."
            )
        return value

    def validate_first_name(self, value):
        return _normalise_name(value)

    def validate_last_name(self, value):
        return _normalise_name(value)

    def validate_password(self, value):
        from django.contrib.auth import password_validation

        password_validation.validate_password(value)
        return value

    def validate_role(self, value):
        actor = (
            self.context["request"].web_user
            if hasattr(self.context["request"], "web_user")
            else self.context["request"].user
        )
        if actor.role == UserRole.ADMIN and value not in _CREATABLE_BY_ADMIN:
            raise serializers.ValidationError(
                "Admins can only create Student or Teacher accounts."
            )
        return value


class AdminUserUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(
        required=False, max_length=150, validators=[validate_name]
    )
    last_name = serializers.CharField(
        required=False, max_length=150, validators=[validate_name]
    )
    mobile = serializers.CharField(
        required=False, max_length=17, validators=[validate_mobile_number]
    )
    is_active = serializers.BooleanField(required=False)
    is_email_verified = serializers.BooleanField(required=False)
    is_mobile_verified = serializers.BooleanField(required=False)
    role = serializers.ChoiceField(choices=UserRole.choices, required=False)

    def validate_first_name(self, value):
        return _normalise_name(value)

    def validate_last_name(self, value):
        return _normalise_name(value)

    def validate_mobile(self, value):
        value = value.strip()
        target = self.context.get("target")
        qs = User.all_objects.filter(mobile=value)
        if target is not None:
            qs = qs.exclude(pk=target.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A user with this mobile number already exists."
            )
        return value


class AdminLoginRequestSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.get_full_name", read_only=True)
    reviewed_by_email = serializers.CharField(
        source="reviewed_by.email", read_only=True, default=None
    )

    class Meta:
        model = AdminLoginRequest
        fields = (
            "id",
            "user_email",
            "user_name",
            "status",
            "requested_ip",
            "requested_user_agent",
            "reviewed_by_email",
            "reviewed_at",
            "expires_at",
            "created_at",
        )
        read_only_fields = fields


# ======================================================================
# Helpers
# ======================================================================
def _actor(request):
    return getattr(request, "user", None)


def _get_user_or_404(user_id):
    user = User.all_objects.filter(id=user_id).first()
    if user is None:
        raise ResourceNotFoundException(detail="User not found.")
    return user


def _guard_target(actor, target, *, allow_self=False):
    if not allow_self and target.id == actor.id:
        raise PermissionDeniedException(
            detail="You can't perform this action on your own account here."
        )
    if target.role == UserRole.SUPERADMIN and actor.role != UserRole.SUPERADMIN:
        raise PermissionDeniedException(
            detail="Only a Super Admin can manage a Super Admin account."
        )


# ======================================================================
# User management
# ======================================================================
class _Pagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema_view(
    get=extend_schema(
        tags=["User Management"],
        operation_id="admin_users_list",
        summary="List / search platform users (admin, super admin)",
        responses=AdminUserSerializer(many=True),
    ),
    post=extend_schema(
        tags=["User Management"],
        operation_id="admin_users_create",
        summary="Create a user account (super admin)",
        request=AdminUserCreateSerializer,
        responses={201: AdminUserSerializer},
    ),
)
class AdminUserListCreateView(APIView):
    def get(self, request):
        qs = User.all_objects.all().order_by("-created_at")
        p = request.query_params
        if p.get("role"):
            qs = qs.filter(role=p["role"])
        if p.get("is_active") in ("true", "false"):
            qs = qs.filter(is_active=p["is_active"] == "true")
        if p.get("search"):
            s = p["search"]
            qs = qs.filter(
                Q(email__icontains=s)
                | Q(first_name__icontains=s)
                | Q(last_name__icontains=s)
                | Q(mobile__icontains=s)
            )

        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        data = AdminUserSerializer(page, many=True).data
        return APIResponse.paginated(
            data=data,
            pagination_meta={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
        )

    def post(self, request):
        serializer = AdminUserCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        password = data.pop("password")
        user = User.objects.create_user(password=password, **data)
        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="user.created",
            target=user,
            message=f"Created {user.role} account {user.email}",
            role=user.role,
        )
        return APIResponse.created(
            data=AdminUserSerializer(user).data, message="User created."
        )


@extend_schema_view(
    get=extend_schema(
        tags=["User Management"],
        operation_id="admin_users_retrieve",
        summary="Retrieve one user (admin, super admin)",
        responses=AdminUserSerializer,
    ),
    patch=extend_schema(
        tags=["User Management"],
        operation_id="admin_users_update",
        summary="Update a user - role / active state / profile (super admin)",
        request=AdminUserUpdateSerializer,
        responses=AdminUserSerializer,
    ),
)
class AdminUserDetailView(APIView):
    def get(self, request, id):
        return APIResponse.success(data=AdminUserSerializer(_get_user_or_404(id)).data)

    def patch(self, request, id):
        actor = _actor(request)
        target = _get_user_or_404(id)
        serializer = AdminUserUpdateSerializer(
            data=request.data, partial=True, context={"target": target}
        )
        serializer.is_valid(raise_exception=True)
        changes = serializer.validated_data

        if "role" in changes and changes["role"] != target.role:
            _guard_target(actor, target)
            if target.role == UserRole.SUPERADMIN:
                remaining = (
                    User.objects.filter(role=UserRole.SUPERADMIN, is_active=True)
                    .exclude(id=target.id)
                    .count()
                )
                if remaining == 0:
                    raise ValidationException(
                        detail="Can't change the role of the last active Super Admin."
                    )
            old = target.role
            target.role = changes["role"]
            AuditService.record(
                request=request,
                category=AuditCategory.USER,
                action="user.role_changed",
                target=target,
                message=f"{target.email}: {old} -> {target.role}",
                old_role=old,
                new_role=target.role,
            )

        if "is_active" in changes and changes["is_active"] != target.is_active:
            _guard_target(actor, target)
            target.is_active = changes["is_active"]
            if not target.is_active:
                UserSession.objects.filter(user=target, is_active=True).update(
                    is_active=False
                )
            AuditService.record(
                request=request,
                category=AuditCategory.USER,
                action="user.activated" if target.is_active else "user.deactivated",
                target=target,
                message=f"{'Activated' if target.is_active else 'Deactivated'} {target.email}",
            )

        for field in (
            "first_name",
            "last_name",
            "mobile",
            "is_email_verified",
            "is_mobile_verified",
        ):
            if field in changes:
                setattr(target, field, changes[field])

        target.save()
        return APIResponse.success(
            data=AdminUserSerializer(target).data, message="User updated."
        )


@extend_schema(
    tags=["User Management"],
    request=None,
    responses=AdminUserSerializer,
    summary="Activate or deactivate a user account (super admin)",
)
class AdminUserSetActiveView(APIView):
    active = True

    def post(self, request, id):
        actor = _actor(request)
        target = _get_user_or_404(id)
        _guard_target(actor, target)
        target.is_active = self.active
        target.save(update_fields=["is_active"])
        if not self.active:
            UserSession.objects.filter(user=target, is_active=True).update(
                is_active=False
            )
        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="user.activated" if self.active else "user.deactivated",
            target=target,
            message=f"{'Activated' if self.active else 'Deactivated'} {target.email}",
        )
        return APIResponse.success(
            data=AdminUserSerializer(target).data,
            message="Account reactivated." if self.active else "Account deactivated.",
        )


# ======================================================================
# Impersonation
# ======================================================================
@extend_schema(
    tags=["User Management"],
    summary="Start impersonating a user (super admin)",
    request=inline_serializer(
        "AdminImpersonateRequest",
        {"reason": drf_serializers.CharField(required=False, allow_blank=True)},
    ),
    responses={
        200: OpenApiResponse(
            description="`data`: {access, refresh, user, impersonation}. Auth cookies set."
        )
    },
)
class AdminUserImpersonateView(APIView):
    def post(self, request, id):
        actor = _actor(request)
        target = _get_user_or_404(id)

        if target.role == UserRole.SUPERADMIN:
            raise PermissionDeniedException(
                detail="You can't impersonate another Super Admin."
            )
        if target.id == actor.id:
            raise ValidationException(detail="You can't impersonate yourself.")
        if not target.is_active:
            raise ValidationException(detail="This account is deactivated.")

        imp = ImpersonationSession.objects.create(
            target_user=target,
            impersonator=actor,
            reason=(request.data.get("reason") or "")[:255],
        )
        access, refresh = issue_pair(
            target,
            sid=imp.session_id,
            extra_claims={
                "act": str(actor.id),
                "act_email": actor.email,
                "act_role": actor.role,
            },
        )
        AuditService.record(
            request=request,
            category=AuditCategory.IMPERSONATION,
            action="impersonation.start",
            target=target,
            message=f"{actor.email} started acting as {target.email}",
            impersonation_id=str(imp.id),
            reason=imp.reason,
        )
        resp = APIResponse.success(
            data={
                "access": access,
                "refresh": refresh,
                "user": AdminUserSerializer(target).data,
                "impersonation": {
                    "impersonator_email": actor.email,
                    "expires_at": imp.expires_at.isoformat(),
                },
            },
            message=f"You are now acting as {target.get_full_name() or target.email}.",
        )
        set_auth_cookies(resp, access, refresh)
        return resp


# ======================================================================
# Admin-login approval flow
# ======================================================================
def _issue_session_response(user, request, message):
    session = UserSession.start(user, device_info=request.META.get("HTTP_USER_AGENT"))
    access, refresh = issue_pair(user, sid=session.session_id)
    resp = APIResponse.success(
        data={
            "access": access,
            "refresh": refresh,
            "user": AdminUserSerializer(user).data,
        },
        message=message,
    )
    set_auth_cookies(resp, access, refresh)
    return resp


@extend_schema(
    tags=["Authentication"],
    summary="Staff sign-in: Super Admin directly, Admin -> pending approval request",
    request=inline_serializer(
        "AdminLoginRequestBody",
        {
            "email": drf_serializers.EmailField(),
            "password": drf_serializers.CharField(),
        },
    ),
    responses={
        200: OpenApiResponse(description="Super Admin: signed in, auth cookies set."),
        202: OpenApiResponse(
            description="Admin: `data` = {request_id, poll_token, status, expires_at}."
        ),
    },
)
class AdminLoginView(APIView):
    permission_classes = []
    authentication_classes = []
    throttle_classes = [ResilientAnonRateThrottle, AdminLoginRateThrottle]

    def post(self, request):
        CaptchaService.verify_or_raise(request)

        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password") or ""
        user = authenticate(request, username=email, password=password)

        if user is None or not user.is_active:
            AuditService.record(
                request=request,
                category=AuditCategory.SECURITY,
                action="admin_login.bad_credentials",
                status=AuditStatus.FAILURE,
                message=f"Failed staff sign-in for {email or '(blank)'}",
            )
            raise ValidationException(detail="Incorrect email or password.")

        CaptchaService.record_account_use(request, user.id)

        if user.role == UserRole.SUPERADMIN:
            AuditService.record(
                request=request,
                category=AuditCategory.AUTH,
                action="admin_login.superadmin_direct",
                actor=user,
                message=f"Super Admin {user.email} signed in",
            )
            return _issue_session_response(user, request, "Signed in.")

        if user.role != UserRole.ADMIN:
            raise ValidationException(
                detail="This sign-in is for administrator accounts only."
            )

        if not settings.ADMIN_LOGIN_REQUIRES_APPROVAL:
            return _issue_session_response(user, request, "Signed in.")

        # Supersede any earlier pending request from this admin.
        AdminLoginRequest.objects.filter(
            user=user, status=AdminLoginRequest.Status.PENDING
        ).update(status=AdminLoginRequest.Status.EXPIRED)
        req = AdminLoginRequest.objects.create(
            user=user,
            poll_token=secrets.token_urlsafe(24),
            requested_ip=request.META.get("REMOTE_ADDR"),
            requested_user_agent=request.META.get("HTTP_USER_AGENT", "")[:400],
            expires_at=timezone.now()
            + timedelta(minutes=settings.ADMIN_LOGIN_REQUEST_TTL_MINUTES),
        )
        AuditService.record(
            request=request,
            category=AuditCategory.ADMIN_LOGIN,
            action="admin_login.requested",
            actor=user,
            status=AuditStatus.PENDING,
            target=req,
            message=f"{user.email} requested admin access",
        )
        return APIResponse.success(
            data={
                "request_id": str(req.id),
                "poll_token": req.poll_token,
                "status": req.status,
                "expires_at": req.expires_at.isoformat(),
            },
            message="Your request is awaiting Super Admin approval.",
            http_status=status.HTTP_202_ACCEPTED,
        )


@extend_schema(
    tags=["Authentication"],
    summary="Poll a pending admin-login request; issues a session once approved",
    parameters=[
        OpenApiParameter(
            "token",
            str,
            OpenApiParameter.QUERY,
            required=True,
            description="poll_token from admin login",
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="`data`: {status} while pending; a full session once approved."
        )
    },
)
class AdminLoginStatusView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request, request_id):
        token = request.query_params.get("token") or ""
        req = (
            AdminLoginRequest.objects.filter(id=request_id, poll_token=token)
            .select_related("user")
            .first()
        )
        if req is None:
            raise ResourceNotFoundException(detail="Login request not found.")

        if req.status == AdminLoginRequest.Status.PENDING and req.is_expired():
            req.status = AdminLoginRequest.Status.EXPIRED
            req.save(update_fields=["status"])

        if req.status == AdminLoginRequest.Status.APPROVED:
            if not req.user.is_active:
                raise ValidationException(detail="This account is no longer active.")
            req.status = AdminLoginRequest.Status.CONSUMED
            req.save(update_fields=["status"])
            AuditService.record(
                request=request,
                category=AuditCategory.AUTH,
                action="admin_login.completed",
                actor=req.user,
                message=f"{req.user.email} signed in after approval",
            )
            return _issue_session_response(
                req.user, request, "Approved — you're signed in."
            )

        return APIResponse.success(data={"status": req.status})


@extend_schema(
    tags=["User Management"],
    summary="Pending + recent admin-login requests (super admin)",
    responses=AdminLoginRequestSerializer(many=True),
)
class AdminLoginRequestListView(APIView):
    def get(self, request):
        # expire stale ones lazily
        AdminLoginRequest.objects.filter(
            status=AdminLoginRequest.Status.PENDING, expires_at__lte=timezone.now()
        ).update(status=AdminLoginRequest.Status.EXPIRED)

        qs = AdminLoginRequest.objects.select_related("user", "reviewed_by").order_by(
            "-created_at"
        )
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        else:
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=2))
        return APIResponse.success(
            data=AdminLoginRequestSerializer(qs[:100], many=True).data
        )


@extend_schema(
    tags=["User Management"],
    summary="Approve or deny a pending admin-login request (super admin)",
    request=None,
    responses={
        200: OpenApiResponse(
            description="Request marked approved/denied; audit entry recorded."
        )
    },
)
class AdminLoginRequestDecisionView(APIView):
    approve = True

    def post(self, request, id):
        req = AdminLoginRequest.objects.select_related("user").filter(id=id).first()
        if req is None:
            raise ResourceNotFoundException(detail="Login request not found.")
        if req.status != AdminLoginRequest.Status.PENDING:
            raise ValidationException(detail=f"This request is already {req.status}.")
        if req.is_expired():
            req.status = AdminLoginRequest.Status.EXPIRED
            req.save(update_fields=["status"])
            raise ValidationException(detail="This request has expired.")

        req.status = (
            AdminLoginRequest.Status.APPROVED
            if self.approve
            else AdminLoginRequest.Status.DENIED
        )
        req.reviewed_by = _actor(request)
        req.reviewed_at = timezone.now()
        req.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        AuditService.record(
            request=request,
            category=AuditCategory.ADMIN_LOGIN,
            action="admin_login.approved" if self.approve else "admin_login.denied",
            target=req.user,
            message=f"{req.user.email} admin access {'approved' if self.approve else 'denied'}",
        )
        return APIResponse.success(
            data=AdminLoginRequestSerializer(req).data,
            message="Approved." if self.approve else "Denied.",
        )
