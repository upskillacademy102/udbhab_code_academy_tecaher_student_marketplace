"""
Permission classes for the Teacher Marketplace Platform.

PRIMARY MECHANISM
    ``RoleBasedAPIPermission`` (below) is installed globally in
    ``REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`` and enforces the
    centralised, default-deny role -> HTTP-method -> endpoint policy
    defined in ``apps.accounts.api_permissions``. Views should NOT add
    per-role permission classes any more - grant the route in the
    registry instead.

LEGACY ROLE CLASSES
    ``IsStudent`` / ``IsTeacher`` / ``IsAdminRole`` / ``IsSuperAdminRole``
    / ``IsAdminOrSuperAdmin`` / ``IsAdminOrSuperAdminOrReadOnly`` are kept
    for backwards compatibility and for the occasional need to compose an
    extra check onto a single view. They are no longer referenced by any
    view after the centralisation refactor.

OBJECT-LEVEL CLASSES
    ``IsOwnerOrReadOnly`` / ``IsSelf`` implement per-object ownership
    checks (``has_object_permission``) and are orthogonal to the
    role-vs-endpoint policy - use them alongside the global default when
    a view exposes someone else's object by id.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.api_permissions import is_allowed, is_public


class RoleBasedAPIPermission(BasePermission):
    """
    The project-wide authorisation gate. Installed globally via
    ``REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`` alongside
    ``IsAuthenticated`` (which must stay FIRST so that missing/invalid/
    expired credentials produce 401, not 403).

    Decision is delegated entirely to the centralised registry in
    ``apps.accounts.api_permissions`` - this class holds no per-endpoint
    knowledge of its own:

        * route in PUBLIC_ROUTE_NAMES        -> allow (even anonymous)
        * not authenticated                  -> deny (IsAuthenticated already
                                                returned 401 first)
        * is_allowed(role, method, route)    -> allow / deny (DEFAULT DENY)

    Any endpoint with no explicit rule for the caller's role + HTTP
    method is denied.
    """

    message = "Your account role does not have permission to use this endpoint."

    def has_permission(self, request, view):
        resolver_match = request.resolver_match
        route_name = resolver_match.view_name if resolver_match is not None else None

        if is_public(route_name):
            return True

        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            # IsAuthenticated (ordered first) will have already raised
            # 401; returning False here is just belt-and-braces.
            return False

        return is_allowed(getattr(user, "role", None), request.method, route_name)


class IsStudent(BasePermission):
    """Allows access only to authenticated users with the Student role."""

    message = "This action is restricted to Student accounts."

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.is_student
        )


class IsTeacher(BasePermission):
    """Allows access only to authenticated users with the Teacher role."""

    message = "This action is restricted to Teacher accounts."

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.is_teacher
        )


class IsAdminRole(BasePermission):
    """
    Allows access only to authenticated users with the Admin role.
    Distinct from Django's is_staff (Django Admin site access) -
    this checks OUR platform-specific `role` field instead, so a
    user can be an "Admin" on the marketplace without necessarily
    having Django Admin site access, or vice versa.
    """

    message = "This action is restricted to Admin accounts."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_admin_role
        )


class IsSuperAdminRole(BasePermission):
    """Allows access only to authenticated users with the SuperAdmin role."""

    message = "This action is restricted to Super Admin accounts."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_superadmin_role
        )


class IsAdminOrSuperAdmin(BasePermission):
    """
    Convenience permission for endpoints that should be accessible
    to either platform Admins or Super Admins (e.g. future
    moderation/reporting endpoints), without requiring the
    SuperAdmin-only restriction of IsSuperAdminRole.
    """

    message = "This action is restricted to Admin or Super Admin accounts."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_admin_role or request.user.is_superadmin_role)
        )


class IsAdminOrSuperAdminOrReadOnly(BasePermission):
    """
    Allows unrestricted read access (GET/HEAD/OPTIONS) to anyone,
    but restricts write methods (POST/PUT/PATCH/DELETE) to
    authenticated Admin or SuperAdmin users only.

    Used by reference-data apps (subjects, languages, location)
    that expose public read APIs but restrict mutation to platform
    admins.
    """

    message = "Only Admin or Super Admin accounts can modify this resource."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_admin_role or request.user.is_superadmin_role)
        )


class IsOwnerOrReadOnly(BasePermission):
    """
    Object-level permission: allows read access (GET/HEAD/OPTIONS)
    to anyone with base permission to view the object at all, but
    restricts write access (PUT/PATCH/DELETE) to the object's
    owner only.

    Expects the model instance to expose an `owner`-like attribute.
    Since Student/Teacher profile models (built in the next apps)
    will each have a OneToOneField back to User, this checks a
    configurable `owner_field_name` (default: "user") rather than
    hardcoding a single attribute name, so it can be reused across
    both apps.
    """

    owner_field_name = "user"

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        owner = getattr(obj, self.owner_field_name, None)
        return owner is not None and owner == request.user


class IsSelf(BasePermission):
    """
    Object-level permission restricting access to the User instance
    that represents the requesting user themselves (e.g. a future
    "update my own account" endpoint operating directly on User
    rather than a Student/Teacher profile).
    """

    def has_object_permission(self, request, view, obj):
        return obj == request.user
