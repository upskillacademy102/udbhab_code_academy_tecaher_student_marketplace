"""
apps.trust.services.staff_login_guard_service.StaffLoginGuardService -
brute-force protection on the admin/super-admin staff-login endpoints.

config.settings.test pins STAFF_LOGIN_BRUTEFORCE_THRESHOLD to 10_000 for
the general suite; this file overrides it back to a small, deterministic
value to exercise the threshold deliberately (same tactic as
test_fake_lead_reports.py for the fake-lead auto-ban).

Run: python manage.py test apps.trust.tests.test_staff_login_guard \
     --settings=config.settings.test
"""

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import AdminDepartment, User, UserRole
from apps.accounts.services.admin_account_naming import build_admin_account_name
from apps.accounts.tests.helpers import TEST_PASSWORD, make_user
from apps.trust.models import AccountSanction, AccountSanctionSource
from apps.trust.services.staff_login_guard_service import StaffLoginGuardService

_SMALL = dict(STAFF_LOGIN_BRUTEFORCE_THRESHOLD=3, STAFF_LOGIN_IP_BLOCK_MINUTES=60)

SUPERADMIN_LOGIN = "/api/v1/auth/staff/login-superadmin/"
ADMIN_LOGIN = "/api/v1/auth/staff/login-admin/"


def _make_named_admin(**over):
    department, _ = AdminDepartment.objects.get_or_create(name="Finance")
    defaults = dict(
        first_name="Guard",
        last_name="Test",
        email="guardtest@example.com",
        mobile="919000000300",
    )
    defaults.update(over)
    account_name = build_admin_account_name(
        defaults["first_name"], defaults["last_name"], department
    )
    return User.objects.create_user(
        password=TEST_PASSWORD,
        role=UserRole.ADMIN,
        admin_account_name=account_name,
        admin_department=department,
        **defaults,
    )


@override_settings(**_SMALL)
class AccountAutoBanTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_admin_account_auto_banned_after_threshold(self):
        admin = _make_named_admin()
        for _ in range(3):
            r = self.client.post(
                ADMIN_LOGIN,
                {"account_name": admin.admin_account_name, "password": "wrong"},
                format="json",
            )
            self.assertEqual(r.status_code, 400)

        admin.refresh_from_db()
        self.assertFalse(admin.is_active)
        self.assertTrue(
            AccountSanction.objects.filter(
                user=admin,
                active=True,
                source=AccountSanctionSource.AUTO_STAFF_LOGIN_BRUTEFORCE,
            ).exists()
        )

    def test_success_resets_the_counter(self):
        admin = _make_named_admin(email="reset@example.com", mobile="919000000301")
        for _ in range(2):  # one below threshold
            self.client.post(
                ADMIN_LOGIN,
                {"account_name": admin.admin_account_name, "password": "wrong"},
                format="json",
            )
        good = self.client.post(
            ADMIN_LOGIN,
            {"account_name": admin.admin_account_name, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(good.status_code, 200)

        # Two more failures now - counter should have reset, so this does
        # NOT reach the threshold (would need 3 fresh failures).
        for _ in range(2):
            self.client.post(
                ADMIN_LOGIN,
                {"account_name": admin.admin_account_name, "password": "wrong"},
                format="json",
            )
        admin.refresh_from_db()
        self.assertTrue(admin.is_active)

    def test_superadmin_cannot_be_auto_banned_falls_back_to_ip_block(self):
        sa = make_user(role=UserRole.SUPERADMIN, email="protected-sa@example.com")
        for _ in range(3):
            r = self.client.post(
                SUPERADMIN_LOGIN,
                {"email": sa.email, "password": "wrong"},
                format="json",
            )
            self.assertEqual(r.status_code, 400)
        sa.refresh_from_db()
        self.assertTrue(sa.is_active)
        self.assertFalse(AccountSanction.objects.filter(user=sa).exists())

        # The IP itself should now be cooled down for the superadmin page
        # (fallback triggered instead of the impossible account ban).
        blocked = self.client.post(
            SUPERADMIN_LOGIN,
            {"email": sa.email, "password": TEST_PASSWORD},
            format="json",
        )
        self.assertEqual(blocked.status_code, 429)


@override_settings(**_SMALL)
class UnresolvedIdentifierIpBlockTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_unknown_account_name_blocks_ip_not_any_account(self):
        for _ in range(3):
            r = self.client.post(
                ADMIN_LOGIN,
                {"account_name": "NobodyHere@Finance", "password": "whatever"},
                format="json",
            )
            self.assertEqual(r.status_code, 400)
        self.assertEqual(AccountSanction.objects.count(), 0)

        blocked = self.client.post(
            ADMIN_LOGIN,
            {"account_name": "AnotherGuess@Finance", "password": "whatever"},
            format="json",
        )
        self.assertEqual(blocked.status_code, 429)

    def test_different_ip_unaffected_by_anothers_ip_block(self):
        for _ in range(3):
            self.client.post(
                ADMIN_LOGIN,
                {"account_name": "NobodyHere@Finance", "password": "whatever"},
                format="json",
                REMOTE_ADDR="10.0.0.1",
            )
        blocked_same_ip = self.client.post(
            ADMIN_LOGIN,
            {"account_name": "StillNobody@Finance", "password": "whatever"},
            format="json",
            REMOTE_ADDR="10.0.0.1",
        )
        self.assertEqual(blocked_same_ip.status_code, 429)

        ok_other_ip = self.client.post(
            ADMIN_LOGIN,
            {"account_name": "StillNobody@Finance", "password": "whatever"},
            format="json",
            REMOTE_ADDR="10.0.0.2",
        )
        self.assertEqual(ok_other_ip.status_code, 400)  # rejected, but not IP-blocked


class GuardServiceUnitTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(**_SMALL)
    def test_record_success_clears_counter(self):
        admin = _make_named_admin(email="unit@example.com", mobile="919000000302")
        for _ in range(2):
            StaffLoginGuardService.record_failure(
                None, page="admin", identifier=admin.admin_account_name, resolved_user=admin
            )
        StaffLoginGuardService.record_success(
            page="admin", identifier=admin.admin_account_name
        )
        # One more failure post-reset should not push us over threshold=3.
        StaffLoginGuardService.record_failure(
            None, page="admin", identifier=admin.admin_account_name, resolved_user=admin
        )
        admin.refresh_from_db()
        self.assertTrue(admin.is_active)
