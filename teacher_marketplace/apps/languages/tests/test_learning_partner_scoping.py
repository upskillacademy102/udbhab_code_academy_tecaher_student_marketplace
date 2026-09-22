"""
Phase LP-3: Language scoping to a Learning Partner.

Mirrors apps.subjects.tests.test_learning_partner_scoping exactly - see that
file's docstring for the full reasoning.

Run: python manage.py test apps.languages.tests.test_learning_partner_scoping \
     --settings=config.settings.test
"""

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, login_lp, make_learning_partner_admin, make_user
from apps.languages.models import Language


class LanguagePartitionConstraintTests(APITestCase):
    def test_two_partners_can_have_the_same_name(self):
        lp_a = make_learning_partner_admin("LangPartnerA")
        lp_b = make_learning_partner_admin("LangPartnerB")
        Language.objects.create(name="Konkani", code="kok1", learning_partner=lp_a)
        Language.objects.create(name="Konkani", code="kok2", learning_partner=lp_b)

    def test_global_name_still_unique_globally(self):
        Language.objects.create(name="Elvish", code="elv")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Language.objects.create(name="Elvish", code="elv2")

    def test_global_code_still_unique_globally(self):
        Language.objects.create(name="Dwarvish", code="dwv")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Language.objects.create(name="Not Dwarvish", code="dwv")

    def test_one_partner_cannot_have_the_same_code_twice(self):
        lp_a = make_learning_partner_admin("LangPartnerC")
        Language.objects.create(name="Sindarin", code="snd", learning_partner=lp_a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Language.objects.create(name="Different Name", code="snd", learning_partner=lp_a)


class LanguageVisibilityMatrixTests(APITestCase):
    def setUp(self):
        self.lp_a = make_learning_partner_admin("LangVisA")
        self.lp_b = make_learning_partner_admin("LangVisB")
        self.global_language = Language.objects.create(name="Global Language X", code="glx")
        self.partner_a_language = Language.objects.create(
            name="Partner A Only Language", code="paol", learning_partner=self.lp_a
        )

    def _list_names(self):
        r = self.client.get("/api/v1/languages/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        return {row["name"] for row in r.data["data"]}

    def test_global_language_visible_to_everyone(self):
        login(self.client, make_user(role=UserRole.STUDENT))
        self.assertIn(self.global_language.name, self._list_names())

    def test_partner_language_visible_to_its_own_partner(self):
        login_lp(self.client, self.lp_a)
        self.assertIn(self.partner_a_language.name, self._list_names())

    def test_partner_language_hidden_from_another_partner(self):
        login_lp(self.client, self.lp_b)
        self.assertNotIn(self.partner_a_language.name, self._list_names())

    def test_partner_language_hidden_from_plain_admin(self):
        login(self.client, make_user(role=UserRole.ADMIN))
        self.assertNotIn(self.partner_a_language.name, self._list_names())

    def test_partner_language_visible_to_superadmin(self):
        login(self.client, make_user(role=UserRole.SUPERADMIN))
        self.assertIn(self.partner_a_language.name, self._list_names())

    def test_detail_404s_for_out_of_scope_language(self):
        login_lp(self.client, self.lp_b)
        r = self.client.get(f"/api/v1/languages/{self.partner_a_language.id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_200s_for_the_owning_partner(self):
        login_lp(self.client, self.lp_a)
        r = self.client.get(f"/api/v1/languages/{self.partner_a_language.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["learning_partner_name"], "LangVisA")
