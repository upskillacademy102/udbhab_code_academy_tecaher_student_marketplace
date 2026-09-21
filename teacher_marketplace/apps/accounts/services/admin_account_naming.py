"""
Generates the login identifier for admins created via the self-service
admin-account-request flow, e.g. "RajuDas@Finance", and performs the
atomic approve-request-into-User transition.

Normalization: each of first_name/last_name is Title-cased per
whitespace-separated token and joined with no space ("raju" -> "Raju",
"DAS" -> "Das", "van der Berg" -> "VanDerBerg"). A *generated* login
identifier that visibly varies by how someone happened to type their name
at signup is confusing and looks broken - normalizing makes every
generated name the same recognizable shape.
"""

from __future__ import annotations

import re

from django.db import IntegrityError, transaction
from django.utils import timezone


def normalize_name_part(value: str) -> str:
    return "".join(
        tok[:1].upper() + tok[1:].lower() for tok in value.strip().split() if tok
    )


def build_admin_account_name(first_name: str, last_name: str, department) -> str:
    base = normalize_name_part(first_name) + normalize_name_part(last_name)
    return f"{base}@{department.canonical_name}"


@transaction.atomic
def _approve_and_create_admin_once(request, *, department, reviewed_by):
    from apps.accounts.models import AdminAccountRequest, AdminAccountRequestStatus, User, UserRole
    from apps.core.exceptions.custom_exceptions import ValidationException

    # Re-fetch under a row lock so two concurrent approvals of the SAME
    # request (e.g. two open tabs) can't both proceed past this point: the
    # second one blocks here until the first commits, then sees status !=
    # PENDING and fails cleanly - instead of both racing ahead and the
    # second crashing on User.email's unique constraint once the first has
    # already created that admin.
    request = AdminAccountRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != AdminAccountRequestStatus.PENDING:
        raise ValidationException(detail=f"This request is already {request.status}.")

    base_name = build_admin_account_name(
        request.first_name, request.last_name, department
    )
    stem, _, dept_part = base_name.rpartition("@")

    # Lock every admin_account_name that could possibly collide with this
    # stem+department so two concurrent approvals for the same name land on
    # different suffixes instead of racing on the unique constraint. The
    # suffix digit is inserted BEFORE the "@" ("RajuDas2@Finance"), so a
    # plain startswith(f"{stem}@{dept_part}") would only ever match the
    # unsuffixed name - filter by prefix/suffix separately, then confirm
    # the exact "<stem><digits?>@<dept>" shape in Python (a startswith/
    # endswith match alone could also false-positive on an unrelated name
    # that merely shares the same prefix, e.g. "RajuDasgupta@Finance").
    candidates = (
        User.all_objects.select_for_update()
        .filter(
            admin_account_name__startswith=stem,
            admin_account_name__endswith=f"@{dept_part}",
        )
        .values_list("admin_account_name", flat=True)
    )
    shape = re.compile(rf"^{re.escape(stem)}(\d*)@{re.escape(dept_part)}$")
    existing = {name for name in candidates if shape.match(name)}

    final_name, suffix = base_name, 2
    while final_name in existing:
        final_name = f"{stem}{suffix}@{dept_part}"
        suffix += 1

    user = User.objects.create(
        email=User.objects.normalize_email(request.email),
        mobile=request.mobile,
        first_name=request.first_name,
        last_name=request.last_name,
        role=UserRole.ADMIN,
        admin_account_name=final_name,
        admin_department=department,
        # Already-hashed (make_password) at request-submission time - copied
        # verbatim onto User.password, never re-hashed, never seen here.
        password=request.password_hash,
        is_active=True,
    )

    request.status = AdminAccountRequestStatus.APPROVED
    request.department = department
    request.created_user = user
    request.reviewed_by = reviewed_by
    request.reviewed_at = timezone.now()
    request.save(
        update_fields=[
            "status",
            "department",
            "created_user",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )
    return user


def approve_and_create_admin(request, *, department, reviewed_by):
    """
    Approve a pending ``AdminAccountRequest``: generates a unique
    ``admin_account_name`` and creates the ``User`` row, atomically, with
    department assignment as part of the same transaction (never a
    partial "approved but no department" state).

    Retries once on ``IntegrityError`` as a belt-and-braces backstop - the
    ``select_for_update`` lock above should already make a collision on the
    final unique constraint impossible, but a login identifier is worth
    defending twice.
    """
    try:
        return _approve_and_create_admin_once(
            request, department=department, reviewed_by=reviewed_by
        )
    except IntegrityError:
        return _approve_and_create_admin_once(
            request, department=department, reviewed_by=reviewed_by
        )
