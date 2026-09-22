"""
Phase LP-3: Subject scoping to a Learning Partner.

The matrix this file exists to protect: a global subject (learning_partner=
None) is visible to everyone; a partner-scoped one only to that partner's
own admin and to Super Admin (full oversight) - never to another partner,
a plain admin, or an unrelated student/teacher. This is the "most likely to
hide a leak" matrix the implementation plan calls out explicitly, so it's
tested exhaustively rather than with one or two spot checks.

Run: python manage.py test apps.subjects.tests.test_learning_partner_scoping \
     --settings=config.settings.test
"""

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, login_lp, make_learning_partner_admin, make_user
from apps.subjects.models import Subject


class SubjectPartitionConstraintTests(APITestCase):
    """Model-level: the partial-unique constraints actually behave as designed."""

    def test_two_partners_can_have_the_same_name(self):
        lp_a = make_learning_partner_admin("PartnerA")
        lp_b = make_learning_partner_admin("PartnerB")
        Subject.objects.create(name="Robotics", learning_partner=lp_a)
        Subject.objects.create(name="Robotics", learning_partner=lp_b)  # must not raise

    def test_a_partner_and_the_global_list_can_have_the_same_name(self):
        lp_a = make_learning_partner_admin("PartnerC")
        Subject.objects.create(name="Chess")  # global
        Subject.objects.create(name="Chess", learning_partner=lp_a)  # must not raise

    def test_global_name_still_unique_globally(self):
        Subject.objects.create(name="Origami")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Subject.objects.create(name="Origami")

    def test_one_partner_cannot_have_the_same_name_twice(self):
        lp_a = make_learning_partner_admin("PartnerD")
        Subject.objects.create(name="Pottery", learning_partner=lp_a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Subject.objects.create(name="Pottery", learning_partner=lp_a)


class SubjectVisibilityMatrixTests(APITestCase):
    def setUp(self):
        self.lp_a = make_learning_partner_admin("VisPartnerA")
        self.lp_b = make_learning_partner_admin("VisPartnerB")
        self.global_subject = Subject.objects.create(name="Global Subject X")
        self.partner_a_subject = Subject.objects.create(
            name="Partner A Only Subject", learning_partner=self.lp_a
        )

    def _list_names(self):
        r = self.client.get("/api/v1/subjects/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        return {row["name"] for row in r.data["data"]}

    def test_global_subject_visible_to_everyone(self):
        for user in (
            make_user(role=UserRole.STUDENT),
            make_user(role=UserRole.TEACHER),
            make_user(role=UserRole.ADMIN),
        ):
            self.client.logout()
            login(self.client, user)
            self.assertIn(self.global_subject.name, self._list_names())
        self.client.logout()
        login_lp(self.client, self.lp_a)
        self.assertIn(self.global_subject.name, self._list_names())

    def test_partner_subject_visible_to_its_own_partner(self):
        login_lp(self.client, self.lp_a)
        self.assertIn(self.partner_a_subject.name, self._list_names())

    def test_partner_subject_hidden_from_another_partner(self):
        login_lp(self.client, self.lp_b)
        self.assertNotIn(self.partner_a_subject.name, self._list_names())

    def test_partner_subject_hidden_from_plain_admin(self):
        login(self.client, make_user(role=UserRole.ADMIN))
        self.assertNotIn(self.partner_a_subject.name, self._list_names())

    def test_partner_subject_hidden_from_unrelated_student(self):
        login(self.client, make_user(role=UserRole.STUDENT))
        self.assertNotIn(self.partner_a_subject.name, self._list_names())

    def test_partner_subject_visible_to_superadmin(self):
        login(self.client, make_user(role=UserRole.SUPERADMIN))
        self.assertIn(self.partner_a_subject.name, self._list_names())

    def test_detail_404s_not_403s_for_out_of_scope_subject(self):
        # Existence must never leak via a different status code.
        login_lp(self.client, self.lp_b)
        r = self.client.get(f"/api/v1/subjects/{self.partner_a_subject.id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_200s_for_the_owning_partner(self):
        login_lp(self.client, self.lp_a)
        r = self.client.get(f"/api/v1/subjects/{self.partner_a_subject.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["learning_partner_name"], "VisPartnerA")

    def test_superadmin_can_still_edit_a_partner_scoped_subject_directly(self):
        login(self.client, make_user(role=UserRole.SUPERADMIN))
        r = self.client.patch(
            f"/api/v1/subjects/{self.partner_a_subject.id}/",
            {"name": "Partner A Renamed"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
