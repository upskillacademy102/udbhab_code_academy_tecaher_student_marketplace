"""
Unit tests for apps.trust.services.sanction_service.SanctionService,
focused on the _PROTECTED_ROLES change: Admin is now sanctionable (a Super
Admin's ban/unban authority extends to Admin accounts), Super Admin remains
permanently protected.

Run: python manage.py test apps.trust.tests.test_sanction_service \
     --settings=config.settings.test
"""

from django.test import TestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_user
from apps.core.exceptions.custom_exceptions import ValidationException
from apps.trust.models import AccountSanction
from apps.trust.services.sanction_service import SanctionService


class SanctionServiceProtectedRolesTests(TestCase):
    def test_admin_can_be_banned_and_unbanned(self):
        admin = make_user(role=UserRole.ADMIN)
        sanction = SanctionService.apply(admin, reason="test")
        admin.refresh_from_db()
        self.assertFalse(admin.is_active)
        self.assertTrue(sanction.active)

        SanctionService.lift(sanction, reason="cleared")
        admin.refresh_from_db()
        self.assertTrue(admin.is_active)
        sanction.refresh_from_db()
        self.assertFalse(sanction.active)

    def test_superadmin_cannot_be_sanctioned(self):
        superadmin = make_user(role=UserRole.SUPERADMIN)
        with self.assertRaises(ValidationException):
            SanctionService.apply(superadmin, reason="test")
        superadmin.refresh_from_db()
        self.assertTrue(superadmin.is_active)
        self.assertFalse(
            AccountSanction.objects.filter(user=superadmin).exists()
        )

    def test_student_and_teacher_still_sanctionable(self):
        for role in (UserRole.STUDENT, UserRole.TEACHER):
            target = make_user(role=role)
            sanction = SanctionService.apply(target, reason="test")
            target.refresh_from_db()
            self.assertFalse(target.is_active)
            self.assertTrue(sanction.active)

    def test_apply_is_idempotent(self):
        admin = make_user(role=UserRole.ADMIN)
        first = SanctionService.apply(admin, reason="first")
        second = SanctionService.apply(admin, reason="second")
        self.assertEqual(first.id, second.id)
        self.assertEqual(AccountSanction.objects.filter(user=admin).count(), 1)
