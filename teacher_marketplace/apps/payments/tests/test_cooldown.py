"""
Phase 7g - new-account cooldown (purchase cap + token hold).

Run: python manage.py test apps.payments.tests.test_cooldown --settings=config.settings.test
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.accounts.tests.helpers import make_user
from apps.payments.cooldown import NewAccountCooldownService
from apps.payments.exceptions import PaymentHeldForReview
from apps.payments.models import Payment, PaymentStatus, PaymentType, TokenPackage
from apps.payments.services import PaymentService
from apps.payments.tasks import release_due_cooldown_holds
from apps.teachers.models import Teacher
from apps.wallet.models import WalletHold
from apps.wallet.services import WalletService


def _age_account(teacher, *, days):
    User.objects.filter(pk=teacher.user_id).update(
        created_at=timezone.now() - timedelta(days=days)
    )
    teacher.user.refresh_from_db()


class CooldownCapTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))

    def test_no_cap_when_flag_off(self):
        NewAccountCooldownService.guard_order_amount(self.teacher, Decimal("99999.00"))

    @override_settings(
        TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN=True, TRUST_NEW_ACCOUNT_MAX_PURCHASE=2000
    )
    def test_new_account_over_cap_is_blocked(self):
        with self.assertRaises(PaymentHeldForReview):
            NewAccountCooldownService.guard_order_amount(
                self.teacher, Decimal("5000.00")
            )

    @override_settings(
        TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN=True, TRUST_NEW_ACCOUNT_MAX_PURCHASE=2000
    )
    def test_new_account_under_cap_is_allowed(self):
        NewAccountCooldownService.guard_order_amount(self.teacher, Decimal("1500.00"))

    @override_settings(
        TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN=True,
        TRUST_NEW_ACCOUNT_MAX_PURCHASE=2000,
        TRUST_NEW_ACCOUNT_COOLDOWN_HOURS=24,
    )
    def test_old_account_has_no_cap(self):
        _age_account(self.teacher, days=8)
        NewAccountCooldownService.guard_order_amount(self.teacher, Decimal("50000.00"))


class CooldownHoldTests(TestCase):
    def _payment(self, teacher, *, order="cd_1", tokens=100):
        pkg = TokenPackage.objects.create(
            name=f"Pkg {order}", token_count=tokens, price=Decimal("499.00")
        )
        p = Payment.objects.create(
            teacher=teacher,
            payment_type=PaymentType.TOKEN_PURCHASE,
            token_package=pkg,
            razorpay_order_id=order,
            amount=pkg.final_price,
            token_count=tokens,
            status=PaymentStatus.PENDING,
        )
        WalletService.get_or_create_wallet(teacher)
        return p

    @override_settings(TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN=True)
    def test_tokens_bought_during_cooldown_are_held(self):
        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        p = self._payment(teacher, order="cd_hold")
        PaymentService._mark_payment_successful(p)
        self.assertEqual(WalletService.get_balance(teacher), 100)
        self.assertEqual(WalletService.available_balance(teacher), 0)  # all frozen
        self.assertTrue(
            WalletHold.objects.filter(wallet__teacher=teacher, active=True).exists()
        )

    @override_settings(TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN=True)
    def test_tokens_not_held_for_established_account(self):
        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        _age_account(teacher, days=10)
        p = self._payment(teacher, order="cd_nohold")
        PaymentService._mark_payment_successful(p)
        self.assertEqual(WalletService.available_balance(teacher), 100)
        self.assertFalse(WalletHold.objects.exists())

    def test_no_hold_when_flag_off(self):
        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        p = self._payment(teacher, order="cd_off")
        PaymentService._mark_payment_successful(p)
        self.assertEqual(WalletService.available_balance(teacher), 100)
        self.assertFalse(WalletHold.objects.exists())

    @override_settings(
        TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN=True, TRUST_NEW_ACCOUNT_COOLDOWN_HOURS=24
    )
    def test_release_due_holds_frees_elapsed_cooldowns(self):
        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        p = self._payment(teacher, order="cd_rel")
        PaymentService._mark_payment_successful(p)
        hold = WalletHold.objects.get(wallet__teacher=teacher)
        # age the hold past the cooldown window
        WalletHold.objects.filter(pk=hold.pk).update(
            created_at=timezone.now() - timedelta(hours=30)
        )
        out = release_due_cooldown_holds()
        self.assertEqual(out["released"], 1)
        self.assertEqual(WalletService.available_balance(teacher), 100)

    @override_settings(
        TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN=True, TRUST_NEW_ACCOUNT_COOLDOWN_HOURS=24
    )
    def test_release_keys_off_account_age_not_hold_age(self):
        # A purchase late in the cooldown: hold is fresh, but the account is
        # already past the window -> should release on the next sweep.
        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        _age_account(teacher, days=2)  # account is 2 days old
        p = self._payment(teacher, order="cd_late")
        PaymentService._mark_payment_successful(p)  # credits 100, no hold (aged)
        # simulate a hold that lingered from earlier in the window
        WalletService.place_hold(teacher, 100, "new-account cooldown (cd_late)")
        self.assertEqual(WalletService.available_balance(teacher), 0)
        self.assertEqual(release_due_cooldown_holds()["released"], 1)
        self.assertEqual(WalletService.available_balance(teacher), 100)

    @override_settings(
        TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN=True, TRUST_NEW_ACCOUNT_COOLDOWN_HOURS=24
    )
    def test_release_due_holds_leaves_fresh_holds(self):
        teacher = Teacher.objects.create(user=make_user(role=UserRole.TEACHER))
        p = self._payment(teacher, order="cd_fresh")
        PaymentService._mark_payment_successful(p)
        self.assertEqual(release_due_cooldown_holds()["released"], 0)
        self.assertEqual(WalletService.available_balance(teacher), 0)
