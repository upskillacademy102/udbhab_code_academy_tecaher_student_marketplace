"""
Dual-role accounts: letting one User hold both a Student and a Teacher
profile, and switch which portal is active.

`Student.user` and `Teacher.user` are independent OneToOneFields, so
nothing in the schema stops one User row from having both rows at once
- `role` has always meant "which portal is active right now", not "the
only role this identity is allowed to have". This module is the one
place that flips it, reused by both the API endpoint (apps.accounts.views
.SwitchRoleView) and the web guards (apps.web.views) so the get_or_create
+ role-flip logic isn't duplicated between them.

Deliberately never creates a User row and never goes near RegisterSerializer
or DedupeService - it only ever acts on an already-authenticated, already-
existing User, so the duplicate-account fraud machinery (which runs on new
registrations) is never in play here.
"""

from rest_framework.exceptions import ValidationError

from apps.accounts.models import UserRole

_SWITCHABLE_ROLES = (UserRole.STUDENT, UserRole.TEACHER)


def switch_active_role(user, target_role: str) -> bool:
    """
    Flips `user` to `target_role`, creating the bare Student/Teacher
    row first if it doesn't exist yet. Returns True if a new profile
    row was just created (i.e. this is the user's first time using
    that portal), False if they already had it (a plain switch).
    """
    if target_role not in _SWITCHABLE_ROLES:
        raise ValidationError({"role": "role must be 'student' or 'teacher'."})

    created = False
    if target_role == UserRole.TEACHER:
        from apps.teachers.models import Teacher

        _, created = Teacher.objects.get_or_create(user=user)
    else:
        from apps.students.models import Student

        _, created = Student.objects.get_or_create(user=user)

    if user.role != target_role:
        user.role = target_role
        user.save(update_fields=["role"])

    return created
