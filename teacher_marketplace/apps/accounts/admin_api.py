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

  Learning Partner onboarding  (/api/v1/auth/...)
      POST   /become-learning-partner/     submit request (public)
      GET    /learning-partners/           active partners, for signup dropdowns (public)

  Admin-login approval  (/api/v1/auth/admin/...)
      POST   /login/                        admin submits creds -> pending request (public)
      GET    /login/{id}/status/?token=     admin polls; issues tokens once approved (public)
      GET    /login-requests/               pending + recent           (superadmin)
      POST   /login-requests/{id}/approve/  (superadmin)
      POST   /login-requests/{id}/deny/     (superadmin)

  Learning Partner taxonomy requests  (/api/v1/auth/staff/taxonomy-requests/...)
      GET  /                     pending + recent, every partner (superadmin)
      POST /{id}/approve/        creates the real, partner-scoped Subject/
                                  Language row                  (superadmin)
      POST /{id}/deny/                                          (superadmin)
      (submission itself is POST /api/v1/lp/taxonomy-requests/ - see
      apps.learning_partner.views, a Learning Partner's own endpoint)

Every state change is written to the audit log.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
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
    AdminAccountRequest,
    AdminAccountRequestStatus,
    AdminDepartment,
    AdminLoginRequest,
    ImpersonationSession,
    User,
    UserRole,
    UserSession,
)
from apps.accounts.services.admin_account_naming import approve_and_create_admin
from apps.accounts.tokens import issue_pair
from apps.core.exceptions.custom_exceptions import (
    ConflictException,
    PermissionDeniedException,
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.core.throttling import (
    AdminLoginRateThrottle,
    RegisterRateThrottle,
    ResilientAnonRateThrottle,
)
from apps.languages.models import Language
from apps.ops.models import AuditCategory, AuditStatus
from apps.ops.services import AuditService
from apps.subjects.models import Subject
from apps.trust.models import (
    LearningPartnerTaxonomyRequest,
    TaxonomyRequestKind,
    TaxonomyRequestStatus,
)
from apps.trust.services.captcha_service import CaptchaService
from apps.trust.services.staff_login_guard_service import StaffLoginGuardService
from apps.utils.validators import (
    validate_mobile_number,
    validate_name,
    validate_taxonomy_name,
)

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
    is_learning_partner_admin = serializers.BooleanField(read_only=True)
    admin_department_id = serializers.UUIDField(read_only=True)
    admin_department_name = serializers.CharField(
        source="admin_department.name", read_only=True, default=None
    )

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
            "is_learning_partner_admin",
            "admin_department_id",
            "admin_department_name",
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
        if value in (UserRole.ADMIN, UserRole.LEARNING_PARTNER):
            raise serializers.ValidationError(
                "Admin and Learning Partner accounts can only be created "
                "through the admin-account request/approval flow (Super "
                "Admin dashboard -> Admin account requests / Learning "
                "Partners), not created directly here."
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
    # Reassigns an existing Admin between departments. There was previously
    # no way to do this at all - department was set once, at approval, and
    # never touched again (apps.accounts.services.admin_account_naming).
    # Now that department gates real authority (apps.accounts.
    # api_permissions.DEPARTMENT_ROUTE_SCOPE), a Super Admin needs a way to
    # move someone without deleting and recreating their account.
    admin_department_id = serializers.PrimaryKeyRelatedField(
        source="admin_department",
        queryset=AdminDepartment.objects.filter(is_active=True),
        required=False,
    )

    def validate_admin_department_id(self, value):
        target = self.context.get("target")
        if target is not None and target.role != UserRole.ADMIN:
            raise serializers.ValidationError(
                "Only an Admin account has a department to reassign."
            )
        return value

    def validate_role(self, value):
        if value in (UserRole.ADMIN, UserRole.LEARNING_PARTNER):
            raise serializers.ValidationError(
                "A user can only become an Admin or Learning Partner through "
                "the admin-account request/approval flow (Super Admin "
                "dashboard -> Admin account requests / Learning Partners) - "
                "role can't be changed to either here, even by a Super "
                "Admin. Moving an existing Admin/Learning Partner OUT of the "
                "role (e.g. back to teacher) is unaffected."
            )
        return value

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


class AdminAccountRequestCreateSerializer(serializers.Serializer):
    """
    Public "become an Admin" submission - same fields as RegisterSerializer.
    Creates an AdminAccountRequest, never a User: no account exists until a
    Super Admin approves this request and assigns a department (see
    apps.accounts.services.admin_account_naming.approve_and_create_admin).
    """

    email = serializers.EmailField()
    mobile = serializers.CharField(max_length=17, validators=[validate_mobile_number])
    first_name = serializers.CharField(max_length=150, validators=[validate_name])
    last_name = serializers.CharField(max_length=150, validators=[validate_name])
    requested_department_id = serializers.PrimaryKeyRelatedField(
        source="requested_department",
        queryset=AdminDepartment.objects.filter(is_active=True),
        help_text="The department the requester wants to join.",
    )
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    password_confirm = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )

    def validate_first_name(self, value):
        return _normalise_name(value)

    def validate_last_name(self, value):
        return _normalise_name(value)

    def validate_email(self, value):
        value = User.objects.normalize_email(value)
        if User.all_objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        if AdminAccountRequest.objects.filter(
            email__iexact=value, status=AdminAccountRequestStatus.PENDING
        ).exists():
            raise serializers.ValidationError(
                "A request with this email is already awaiting review."
            )
        return value

    def validate_mobile(self, value):
        value = value.strip()
        if User.all_objects.filter(mobile=value).exists():
            raise serializers.ValidationError(
                "A user with this mobile number already exists."
            )
        if AdminAccountRequest.objects.filter(
            mobile=value, status=AdminAccountRequestStatus.PENDING
        ).exists():
            raise serializers.ValidationError(
                "A request with this mobile number is already awaiting review."
            )
        return value

    def validate_password(self, value):
        from django.contrib.auth import password_validation

        password_validation.validate_password(value)
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        return attrs


class BecomeLearningPartnerSerializer(serializers.Serializer):
    """
    Public "become a Learning Partner" submission - same underlying request
    table as AdminAccountRequestCreateSerializer (AdminAccountRequest), but
    for an organisation identity rather than a person: organization_name
    instead of first/last name. Creates a request with organization_name
    set; first_name/last_name are left blank. See
    apps.accounts.services.admin_account_naming for how this becomes a
    generated account name on approval.
    """

    organization_name = serializers.CharField(
        max_length=190, validators=[validate_taxonomy_name]
    )
    email = serializers.EmailField()
    mobile = serializers.CharField(max_length=17, validators=[validate_mobile_number])
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    password_confirm = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )

    def validate_organization_name(self, value):
        return " ".join(value.split())

    def validate_email(self, value):
        value = User.objects.normalize_email(value)
        if User.all_objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        if AdminAccountRequest.objects.filter(
            email__iexact=value, status=AdminAccountRequestStatus.PENDING
        ).exists():
            raise serializers.ValidationError(
                "A request with this email is already awaiting review."
            )
        return value

    def validate_mobile(self, value):
        value = value.strip()
        if User.all_objects.filter(mobile=value).exists():
            raise serializers.ValidationError(
                "A user with this mobile number already exists."
            )
        if AdminAccountRequest.objects.filter(
            mobile=value, status=AdminAccountRequestStatus.PENDING
        ).exists():
            raise serializers.ValidationError(
                "A request with this mobile number is already awaiting review."
            )
        return value

    def validate_password(self, value):
        from django.contrib.auth import password_validation

        password_validation.validate_password(value)
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        return attrs


class AdminAccountRequestSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None
    )
    requested_department_name = serializers.CharField(
        source="requested_department.name", read_only=True, default=None
    )
    reviewed_by_email = serializers.CharField(
        source="reviewed_by.email", read_only=True, default=None
    )
    created_admin_account_name = serializers.CharField(
        source="created_user.admin_account_name", read_only=True, default=None
    )

    class Meta:
        model = AdminAccountRequest
        fields = (
            "id",
            "email",
            "mobile",
            "first_name",
            "last_name",
            "organization_name",
            "status",
            "requested_department",
            "requested_department_name",
            "department",
            "department_name",
            "created_admin_account_name",
            "reviewed_by_email",
            "reviewed_at",
            "deny_reason",
            "requested_ip",
            "requested_user_agent",
            "created_at",
        )
        read_only_fields = fields


class AdminDepartmentSerializer(serializers.ModelSerializer):
    admin_count = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = AdminDepartment
        fields = (
            "id",
            "name",
            "slug",
            "is_active",
            "admin_count",
            "capabilities",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "slug",
            "admin_count",
            "capabilities",
            "created_at",
            "updated_at",
        )

    def get_admin_count(self, obj) -> int:
        return obj.admins.filter(is_active=True).count()

    def get_capabilities(self, obj) -> list:
        from apps.accounts.api_permissions import DEPARTMENT_CAPABILITY_LABELS

        return list(DEPARTMENT_CAPABILITY_LABELS.get(obj.slug, ()))

    def validate_name(self, value):
        value = value.strip() if isinstance(value, str) else value
        qs = AdminDepartment.all_objects.filter(name__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A department with this name already exists."
            )
        return value


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

        if (
            "admin_department" in changes
            and changes["admin_department"] != target.admin_department
        ):
            _guard_target(actor, target)
            old_department = target.admin_department
            target.admin_department = changes["admin_department"]
            AuditService.record(
                request=request,
                category=AuditCategory.USER,
                action="user.department_reassigned",
                target=target,
                message=(
                    f"{target.email}: "
                    f"{old_department.name if old_department else '(none)'} -> "
                    f"{target.admin_department.name}"
                ),
                old_department=old_department.slug if old_department else None,
                new_department=target.admin_department.slug,
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

        if user.admin_account_name:
            # Admins created via the self-service admin-account-request flow
            # sign in with their generated account name at the new staff
            # gateway (/staff/login-admin/), not here with email - keeps
            # exactly one working login path per account.
            raise ValidationException(
                detail="This account signs in from the admin login page."
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


# ======================================================================
# Staff gateway direct login (Super Admin: direct; Admin: account-name +
# password, one-time-approved at account-creation - see
# apps.accounts.services.admin_account_naming). Super Admin and Admin are
# reached only via the hidden triple-click gateway, never linked from any
# nav. Learning Partner sign-in (further below) is a separate, dedicated
# endpoint and page - reached from the normal "I am a Learning Partner"
# link on the landing page, not the hidden gateway - so a partner never
# needs to type an admin account name to get in, and an admin account
# name is never accepted there either.
# ======================================================================
@extend_schema(
    tags=["Authentication"],
    summary="Super Admin direct sign-in (staff gateway)",
    request=inline_serializer(
        "StaffSuperAdminLoginRequest",
        {
            "email": drf_serializers.EmailField(),
            "password": drf_serializers.CharField(),
        },
    ),
    responses={200: OpenApiResponse(description="Signed in; auth cookies set.")},
)
class StaffSuperAdminLoginView(APIView):
    permission_classes = []
    authentication_classes = []
    throttle_classes = [ResilientAnonRateThrottle, AdminLoginRateThrottle]

    def post(self, request):
        StaffLoginGuardService.check_ip_block(request, page="superadmin")
        CaptchaService.verify_or_raise(request)

        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password") or ""
        user = authenticate(request, username=email, password=password)
        is_superadmin = user is not None and user.role == UserRole.SUPERADMIN

        if not is_superadmin or not user.is_active:
            # Only attribute the failure to a real account when that
            # account is actually a Super Admin - typing someone else's
            # (student/teacher/admin) email here must never be able to get
            # THEIR account auto-banned; it's tracked as an unresolved
            # (IP-only) attempt instead.
            resolved = user if is_superadmin else None
            StaffLoginGuardService.record_failure(
                request, page="superadmin", identifier=email, resolved_user=resolved
            )
            raise ValidationException(detail="Incorrect email or password.")

        CaptchaService.record_account_use(request, user.id)
        StaffLoginGuardService.record_success(page="superadmin", identifier=email)
        AuditService.record(
            request=request,
            category=AuditCategory.AUTH,
            action="staff_login.superadmin",
            actor=user,
            message=f"Super Admin {user.email} signed in via the staff gateway",
        )
        return _issue_session_response(user, request, "Signed in.")


class LearningPartnerWrongPortalException(ValidationException):
    """
    Raised when a Learning Partner account name is submitted at the Admin
    staff-login page. Learning Partner accounts get their own dedicated
    sign-in page (StaffLearningPartnerLoginView / /learning-partner/login/)
    so they are never mixed in with genuine Admin sign-in attempts (or the
    Admin page's ban-deterrent copy, which is aimed at someone impersonating
    staff, not a partner organisation at the wrong door). The frontend
    (static/js/auth.js's staffAdminLogin) redirects to the Learning Partner
    login page on this error_code rather than showing it inline.
    """

    default_detail = "Learning Partner accounts sign in from the Learning Partner login page."
    error_code = "LEARNING_PARTNER_WRONG_PORTAL"


_STAFF_ACCOUNT_LOGIN_LABEL = {
    UserRole.ADMIN: "Admin",
    UserRole.LEARNING_PARTNER: "Learning Partner",
}


def _staff_login_by_account_name(request, *, role, page):
    """
    Shared account-name + password sign-in, used by both
    StaffAdminLoginView (role=admin) and StaffLearningPartnerLoginView
    (role=learning_partner) - identical mechanics, scoped to exactly one
    role each so an account of the "wrong" kind is never authenticated on
    the "wrong" page even if it somehow reaches this far.

    Cannot use django.contrib.auth.authenticate() - USERNAME_FIELD is
    "email", not admin_account_name - so the lookup + password check are
    done directly here instead.
    """
    StaffLoginGuardService.check_ip_block(request, page=page)
    CaptchaService.verify_or_raise(request)

    account_name = (request.data.get("account_name") or "").strip()
    password = request.data.get("password") or ""

    user = User.objects.filter(admin_account_name=account_name, role=role).first()

    if user is None:
        # Constant-time-ish: still run a hash comparison against a
        # dummy value so "no such account name" and "wrong password"
        # take comparable time (mirrors Django's own ModelBackend,
        # which does the same when a username doesn't resolve).
        check_password(password, make_password(None))
        valid = False
    else:
        valid = user.is_active and user.check_password(password)

    if not valid:
        StaffLoginGuardService.record_failure(
            request, page=page, identifier=account_name, resolved_user=user
        )
        raise ValidationException(detail="Incorrect account name or password.")

    CaptchaService.record_account_use(request, user.id)
    StaffLoginGuardService.record_success(page=page, identifier=account_name)

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        first_login = not user.has_seen_admin_credentials_notice
        if first_login:
            user.has_seen_admin_credentials_notice = True
            user.save(
                update_fields=["has_seen_admin_credentials_notice", "updated_at"]
            )
        session = UserSession.start(
            user, device_info=request.META.get("HTTP_USER_AGENT")
        )

    access, refresh = issue_pair(user, sid=session.session_id)
    label = _STAFF_ACCOUNT_LOGIN_LABEL[role]
    AuditService.record(
        request=request,
        category=AuditCategory.AUTH,
        action=f"staff_login.{page}",
        actor=user,
        message=f"{label} {user.admin_account_name} signed in via the staff gateway",
        first_login=first_login,
    )
    resp = APIResponse.success(
        data={
            "access": access,
            "refresh": refresh,
            "user": AdminUserSerializer(user).data,
            "first_login_notice": first_login,
        },
        message="Signed in.",
    )
    set_auth_cookies(resp, access, refresh)
    return resp


@extend_schema(
    tags=["Authentication"],
    summary="Admin sign-in with the generated account name (staff gateway)",
    request=inline_serializer(
        "StaffAdminLoginRequest",
        {
            "account_name": drf_serializers.CharField(),
            "password": drf_serializers.CharField(),
        },
    ),
    responses={
        200: OpenApiResponse(
            description="Signed in; auth cookies set. `data.first_login_notice` "
            "is true exactly once, on this admin's very first successful login."
        )
    },
)
class StaffAdminLoginView(APIView):
    permission_classes = []
    authentication_classes = []
    throttle_classes = [ResilientAnonRateThrottle, AdminLoginRateThrottle]

    def post(self, request):
        account_name = (request.data.get("account_name") or "").strip()
        # Prohibited outright - a Learning Partner account name never signs
        # in here, correct password or not. See LearningPartnerWrongPortalException.
        if User.objects.filter(
            admin_account_name=account_name, role=UserRole.LEARNING_PARTNER
        ).exists():
            raise LearningPartnerWrongPortalException()
        return _staff_login_by_account_name(request, role=UserRole.ADMIN, page="admin")


@extend_schema(
    tags=["Authentication"],
    summary="Learning Partner sign-in with the generated account name",
    request=inline_serializer(
        "StaffLearningPartnerLoginRequest",
        {
            "account_name": drf_serializers.CharField(),
            "password": drf_serializers.CharField(),
        },
    ),
    responses={
        200: OpenApiResponse(
            description="Signed in; auth cookies set. `data.first_login_notice` "
            "is true exactly once, on this partner's very first successful login."
        )
    },
)
class StaffLearningPartnerLoginView(APIView):
    """
    Dedicated Learning Partner sign-in, separate from StaffAdminLoginView -
    a Learning Partner account name (always "...@LearningPartner") is never
    accepted on the Admin page (see LearningPartnerWrongPortalException
    above), and this page never accepts a plain Admin's account name either
    (the role filter below is exact, not role__in).
    """

    permission_classes = []
    authentication_classes = []
    throttle_classes = [ResilientAnonRateThrottle, AdminLoginRateThrottle]

    def post(self, request):
        return _staff_login_by_account_name(
            request, role=UserRole.LEARNING_PARTNER, page="learning_partner"
        )


# ======================================================================
# Admin-account requests (self-service "become an Admin") + Departments.
# Submitting is public (reached via the hidden staff gateway); review,
# decision, and department management are Super Admin only (unlisted in
# apps.accounts.api_permissions -> allowed only by the superadmin
# short-circuit).
# ======================================================================
@extend_schema(
    tags=["Authentication"],
    summary="Submit a request to become an Admin (staff gateway)",
    request=AdminAccountRequestCreateSerializer,
    responses={
        201: OpenApiResponse(
            description="Request recorded; awaiting Super Admin review. No account exists yet."
        )
    },
)
class AdminAccountRequestCreateView(APIView):
    permission_classes = []
    authentication_classes = []
    throttle_classes = [ResilientAnonRateThrottle, RegisterRateThrottle]

    def post(self, request):
        CaptchaService.verify_or_raise(request)

        serializer = AdminAccountRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        req = AdminAccountRequest.objects.create(
            email=data["email"],
            mobile=data["mobile"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            requested_department=data["requested_department"],
            password_hash=make_password(data["password"]),
            requested_ip=request.META.get("REMOTE_ADDR"),
            requested_user_agent=request.META.get("HTTP_USER_AGENT", "")[:400],
        )
        AuditService.record(
            request=request,
            category=AuditCategory.ADMIN_LOGIN,
            action="admin_account_request.submitted",
            status=AuditStatus.PENDING,
            target=req,
            message=f"{req.email} requested an admin account "
            f"({req.requested_department.name})",
        )
        return APIResponse.created(
            data={"id": str(req.id), "status": req.status},
            message="Your request has been sent to the Super Admin — they "
            "will reach out and appoint you as admin.",
        )


class BecomeLearningPartnerView(APIView):
    """
    Public "become a Learning Partner" submission. Creates the same
    AdminAccountRequest row as the admin-account flow, but with
    organization_name set (first_name/last_name left blank) - see
    apps.accounts.services.admin_account_naming for how this becomes a
    generated 'OrgName@LearningPartner' account name on approval, and
    AdminAccountRequestDecisionView for the department-type enforcement
    that keeps this request approvable only into the Learning Partner
    department.
    """

    permission_classes = []
    authentication_classes = []
    throttle_classes = [ResilientAnonRateThrottle, RegisterRateThrottle]

    def post(self, request):
        CaptchaService.verify_or_raise(request)

        serializer = BecomeLearningPartnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        req = AdminAccountRequest.objects.create(
            email=data["email"],
            mobile=data["mobile"],
            organization_name=data["organization_name"],
            password_hash=make_password(data["password"]),
            requested_ip=request.META.get("REMOTE_ADDR"),
            requested_user_agent=request.META.get("HTTP_USER_AGENT", "")[:400],
        )
        AuditService.record(
            request=request,
            category=AuditCategory.ADMIN_LOGIN,
            action="admin_account_request.submitted",
            status=AuditStatus.PENDING,
            target=req,
            message=f"{req.email} requested a Learning Partner account "
            f"({req.organization_name})",
        )
        return APIResponse.created(
            data={"id": str(req.id), "status": req.status},
            message="Your request has been sent to the Super Admin — they "
            "will review it and reach out.",
        )


class LearningPartnerListView(APIView):
    """
    Public list of active Learning Partner organisations - powers the
    "Are you under one of our learning partners?" dropdown at student/
    teacher signup, which is asked before any session exists.
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request):
        partners = (
            User.objects.filter(role=UserRole.LEARNING_PARTNER, is_active=True)
            .order_by("first_name")
            .values("id", "first_name")
        )
        return APIResponse.success(
            data=[{"id": str(p["id"]), "name": p["first_name"]} for p in partners]
        )


@extend_schema(
    tags=["User Management"],
    summary="List Learning Partner accounts (super admin)",
)
class LearningPartnerAdminListView(APIView):
    """
    Every Learning Partner account (active or not) for the superadmin's
    "Learning Partners" > Active tab - distinct from the public
    LearningPartnerListView above (active-only, minimal shape, for the
    signup dropdown).
    """

    def get(self, request):
        partners = User.objects.filter(role=UserRole.LEARNING_PARTNER).order_by(
            "-created_at"
        )
        data = []
        for p in partners:
            referred = User.objects.filter(learning_partner=p)
            data.append(
                {
                    "id": str(p.id),
                    "organization_name": p.first_name,
                    "email": p.email,
                    "mobile": p.mobile,
                    "admin_account_name": p.admin_account_name,
                    "is_active": p.is_active,
                    "students_count": referred.filter(role=UserRole.STUDENT).count(),
                    "teachers_count": referred.filter(role=UserRole.TEACHER).count(),
                    "created_at": p.created_at,
                }
            )
        return APIResponse.success(data=data)


@extend_schema(
    tags=["User Management"],
    summary="Pending + recent admin-account requests (super admin)",
    responses=AdminAccountRequestSerializer(many=True),
)
class AdminAccountRequestListView(APIView):
    def get(self, request):
        qs = AdminAccountRequest.objects.select_related(
            "department", "reviewed_by", "created_user"
        ).order_by("-created_at")
        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        # Learning Partner requests (organization_name set) live in their
        # own dedicated review tab (Learning Partners > Requests), not this
        # generic staff-department queue - default excludes them; pass
        # ?kind=learning_partner to fetch only them instead.
        if request.query_params.get("kind") == "learning_partner":
            qs = qs.exclude(organization_name="")
        else:
            qs = qs.filter(organization_name="")
        return APIResponse.success(
            data=AdminAccountRequestSerializer(qs[:200], many=True).data
        )


@extend_schema(
    tags=["User Management"],
    summary="Approve (with department) or deny a pending admin-account request (super admin)",
    request=inline_serializer(
        "AdminAccountRequestDecisionBody",
        {
            "department_id": drf_serializers.UUIDField(required=False),
            "reason": drf_serializers.CharField(required=False, allow_blank=True),
        },
    ),
    responses={200: AdminAccountRequestSerializer},
)
class AdminAccountRequestDecisionView(APIView):
    approve = True

    def post(self, request, id):
        req = AdminAccountRequest.objects.filter(id=id).first()
        if req is None:
            raise ResourceNotFoundException(detail="Request not found.")
        if req.status != AdminAccountRequestStatus.PENDING:
            raise ValidationException(detail=f"This request is already {req.status}.")

        if self.approve:
            is_lp_request = bool(req.organization_name)
            department = None
            if not is_lp_request:
                # A Learning Partner request has nothing to pick - it's a
                # role, not a department membership. A regular staff request
                # still needs one; "no way around it" is enforced server-side.
                department_id = request.data.get("department_id")
                if not department_id:
                    raise ValidationException(
                        detail="Select a department to approve this request — "
                        "approval and department assignment happen together."
                    )
                department = AdminDepartment.objects.filter(
                    id=department_id, is_active=True
                ).first()
                if department is None:
                    raise ValidationException(detail="Select a valid, active department.")

            user = approve_and_create_admin(
                req, department=department, reviewed_by=_actor(request)
            )
            AuditService.record(
                request=request,
                category=AuditCategory.ADMIN_LOGIN,
                action="admin_account_request.approved",
                target=user,
                message=f"{req.email} approved as "
                f"{'Learning Partner' if is_lp_request else 'admin'} "
                f"({user.admin_account_name})",
                department=department.slug if department else "learning_partner",
                generated_account_name=user.admin_account_name,
            )
            return APIResponse.success(
                data=AdminAccountRequestSerializer(req).data,
                message=f"Approved. Admin account created: {user.admin_account_name}",
            )

        req.status = AdminAccountRequestStatus.DENIED
        req.deny_reason = (request.data.get("reason") or "")[:500]
        req.reviewed_by = _actor(request)
        req.reviewed_at = timezone.now()
        req.save(
            update_fields=[
                "status",
                "deny_reason",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            ]
        )
        AuditService.record(
            request=request,
            category=AuditCategory.ADMIN_LOGIN,
            action="admin_account_request.denied",
            target=req,
            message=f"{req.email} admin request denied",
        )
        return APIResponse.success(
            data=AdminAccountRequestSerializer(req).data, message="Request denied."
        )


@extend_schema(
    tags=["Authentication"],
    summary="List active admin departments (public, for the request-access form)",
)
class AdminDepartmentPublicListView(APIView):
    """
    Public list of active departments - powers the mandatory department
    dropdown on the "Request admin access" signup page (staff gateway).
    Deliberately separate from AdminDepartmentListCreateView (Super Admin
    only, full detail incl. admin_count) - this is a minimal, anonymous-safe
    shape, same pattern as LearningPartnerListView.
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request):
        depts = (
            AdminDepartment.objects.filter(is_active=True)
            .order_by("name")
            .values("id", "name")
        )
        return APIResponse.success(
            data=[{"id": str(d["id"]), "name": d["name"]} for d in depts]
        )


@extend_schema_view(
    get=extend_schema(
        tags=["User Management"], summary="List admin departments (super admin)"
    ),
    post=extend_schema(
        tags=["User Management"], summary="Create an admin department (super admin)"
    ),
)
class AdminDepartmentListCreateView(APIView):
    def get(self, request):
        qs = AdminDepartment.objects.all().order_by("name")
        return APIResponse.success(data=AdminDepartmentSerializer(qs, many=True).data)

    def post(self, request):
        serializer = AdminDepartmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        department = serializer.save()
        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="admin_department.created",
            target=department,
            message=f"Department created: {department.name}",
        )
        return APIResponse.created(
            data=AdminDepartmentSerializer(department).data,
            message="Department created.",
        )


@extend_schema_view(
    get=extend_schema(
        tags=["User Management"], summary="Retrieve an admin department (super admin)"
    ),
    put=extend_schema(
        tags=["User Management"], summary="Update an admin department (super admin)"
    ),
    patch=extend_schema(
        tags=["User Management"],
        summary="Partially update an admin department (super admin)",
    ),
    delete=extend_schema(
        tags=["User Management"], summary="Delete an admin department (super admin)"
    ),
)
class AdminDepartmentDetailView(APIView):
    def _get_department(self, id):
        department = AdminDepartment.all_objects.filter(id=id).first()
        if department is None:
            raise ResourceNotFoundException(detail="Department not found.")
        return department

    def get(self, request, id):
        return APIResponse.success(
            data=AdminDepartmentSerializer(self._get_department(id)).data
        )

    def put(self, request, id):
        return self._update(request, id, partial=False)

    def patch(self, request, id):
        return self._update(request, id, partial=True)

    def _update(self, request, id, partial):
        department = self._get_department(id)
        serializer = AdminDepartmentSerializer(
            department, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        department = serializer.save()
        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="admin_department.updated",
            target=department,
            message=f"Department updated: {department.name}",
        )
        return APIResponse.success(
            data=AdminDepartmentSerializer(department).data,
            message="Department updated.",
        )

    def delete(self, request, id):
        department = self._get_department(id)
        if department.admins.filter(is_active=True).exists():
            raise ConflictException(
                detail="This department has active admins assigned to it and "
                "cannot be removed."
            )
        name = department.name
        department.delete()  # soft delete, per BaseModel
        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="admin_department.deleted",
            target=department,
            message=f"Department deleted: {name}",
        )
        return APIResponse.no_content(message="Department deleted.")


# ======================================================================
# Learning Partner taxonomy requests (Phase LP-3) - a Learning Partner
# submits these via GET/POST /api/v1/lp/taxonomy-requests/
# (apps.learning_partner.views.LPTaxonomyRequestListCreateView, which
# imports LearningPartnerTaxonomyRequestSerializer from this module, same
# way it already imports AdminUserSerializer). Everything below is the
# Super Admin's review side.
# ======================================================================
class LearningPartnerTaxonomyRequestSerializer(serializers.ModelSerializer):
    learning_partner_name = serializers.CharField(
        source="learning_partner.first_name", read_only=True, default=None
    )
    reviewed_by_email = serializers.CharField(
        source="reviewed_by.email", read_only=True, default=None
    )
    created_subject_name = serializers.CharField(
        source="created_subject.name", read_only=True, default=None
    )
    created_language_name = serializers.CharField(
        source="created_language.name", read_only=True, default=None
    )

    class Meta:
        model = LearningPartnerTaxonomyRequest
        fields = (
            "id",
            "learning_partner",
            "learning_partner_name",
            "kind",
            "name",
            "note",
            "status",
            "created_subject",
            "created_subject_name",
            "created_language",
            "created_language_name",
            "reviewed_by_email",
            "reviewed_at",
            "deny_reason",
            "created_at",
        )
        read_only_fields = (
            "id",
            "learning_partner",
            "learning_partner_name",
            "status",
            "created_subject",
            "created_subject_name",
            "created_language",
            "created_language_name",
            "reviewed_by_email",
            "reviewed_at",
            "deny_reason",
            "created_at",
        )

    def validate_name(self, value):
        value = value.strip() if isinstance(value, str) else value
        try:
            validate_taxonomy_name(value)
        except Exception:
            raise serializers.ValidationError(
                "Enter a valid subject/language name."
            )
        return value


@extend_schema(
    tags=["User Management"],
    summary="Pending + recent Learning Partner taxonomy requests (super admin)",
    responses=LearningPartnerTaxonomyRequestSerializer(many=True),
)
class TaxonomyRequestListView(APIView):
    def get(self, request):
        qs = LearningPartnerTaxonomyRequest.objects.select_related(
            "learning_partner", "reviewed_by", "created_subject", "created_language"
        ).order_by("-created_at")
        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        kind_param = request.query_params.get("kind")
        if kind_param:
            qs = qs.filter(kind=kind_param)
        return APIResponse.success(
            data=LearningPartnerTaxonomyRequestSerializer(qs[:200], many=True).data
        )


@extend_schema(
    tags=["User Management"],
    summary="Approve (creates the real, partner-scoped row) or deny a "
    "Learning Partner taxonomy request (super admin)",
    request=inline_serializer(
        "TaxonomyRequestDecisionBody",
        {"reason": drf_serializers.CharField(required=False, allow_blank=True)},
    ),
    responses={200: LearningPartnerTaxonomyRequestSerializer},
)
class TaxonomyRequestDecisionView(APIView):
    approve = True

    def post(self, request, id):
        req = LearningPartnerTaxonomyRequest.objects.filter(id=id).first()
        if req is None:
            raise ResourceNotFoundException(detail="Request not found.")
        if req.status != TaxonomyRequestStatus.PENDING:
            raise ValidationException(detail=f"This request is already {req.status}.")

        if self.approve:
            if req.kind == TaxonomyRequestKind.SUBJECT:
                obj = Subject.all_objects.filter(
                    name__iexact=req.name, learning_partner=req.learning_partner
                ).first()
                if obj is None:
                    obj = Subject.objects.create(
                        name=req.name,
                        is_active=True,
                        learning_partner=req.learning_partner,
                    )
                req.created_subject = obj
            else:
                from apps.languages.services import derive_language_code

                obj = Language.all_objects.filter(
                    name__iexact=req.name, learning_partner=req.learning_partner
                ).first()
                if obj is None:
                    obj = Language.objects.create(
                        name=req.name,
                        code=derive_language_code(req.name),
                        is_active=True,
                        learning_partner=req.learning_partner,
                    )
                req.created_language = obj

            req.status = TaxonomyRequestStatus.APPROVED
            req.reviewed_by = _actor(request)
            req.reviewed_at = timezone.now()
            req.save(
                update_fields=[
                    "status",
                    "created_subject",
                    "created_language",
                    "reviewed_by",
                    "reviewed_at",
                    "updated_at",
                ]
            )
            AuditService.record(
                request=request,
                category=AuditCategory.USER,
                action="lp_taxonomy_request.approved",
                target=obj,
                message=f"{req.kind} '{req.name}' approved for "
                f"{req.learning_partner.admin_account_name}",
            )
            return APIResponse.success(
                data=LearningPartnerTaxonomyRequestSerializer(req).data,
                message=f"Approved. '{req.name}' is now visible to "
                f"{req.learning_partner.first_name}.",
            )

        req.status = TaxonomyRequestStatus.DENIED
        req.deny_reason = (request.data.get("reason") or "")[:500]
        req.reviewed_by = _actor(request)
        req.reviewed_at = timezone.now()
        req.save(
            update_fields=[
                "status",
                "deny_reason",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            ]
        )
        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="lp_taxonomy_request.denied",
            target=req,
            message=f"{req.kind} '{req.name}' denied",
        )
        return APIResponse.success(
            data=LearningPartnerTaxonomyRequestSerializer(req).data,
            message="Request denied.",
        )
