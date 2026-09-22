"""
Phase LP-3: a teacher can only pick subjects/languages they can actually
see - global ones, plus their own Learning Partner's if they have one.

TeacherProfileWriteSerializer.__init__ rebuilds the subjects/languages
PrimaryKeyRelatedField querysets per-request from the request's viewer
(apps/teacher_profile/serializers.py); apps/teacher_profile/views.py's
TeacherProfileView must pass `context={"request": request}` for that to see
a real viewer at all - both were fixed together, since the second without
the first is a silent no-op that still accepts an out-of-scope id.

Run: python manage.py test apps.teacher_profile.tests.test_learning_partner_scoping \
     --settings=config.settings.test
"""

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_learning_partner_admin, make_user
from apps.subjects.models import Subject
from apps.teachers.models import Teacher

PROFILE_URL = "/api/v1/teachers/profile/"


class TeacherProfileSubjectScopingTests(APITestCase):
    def setUp(self):
        self.lp_a = make_learning_partner_admin("TPPartnerA")
        self.lp_b = make_learning_partner_admin("TPPartnerB")
        self.global_subject = Subject.objects.create(name="TP Global Subject")
        self.scoped_a_subject = Subject.objects.create(
            name="TP Partner A Subject", learning_partner=self.lp_a
        )

    def _teacher(self, **over):
        user = make_user(role=UserRole.TEACHER, **over)
        Teacher.objects.create(user=user)
        return user

    def test_teacher_linked_to_partner_can_use_its_scoped_subject(self):
        teacher = self._teacher(learning_partner=self.lp_a)
        login(self.client, teacher)
        r = self.client.post(
            PROFILE_URL,
            {"subjects": [str(self.scoped_a_subject.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)

    def test_teacher_with_no_partner_cannot_use_a_scoped_subject(self):
        teacher = self._teacher()
        login(self.client, teacher)
        r = self.client.post(
            PROFILE_URL,
            {"subjects": [str(self.scoped_a_subject.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_teacher_linked_to_a_different_partner_cannot_use_it_either(self):
        teacher = self._teacher(learning_partner=self.lp_b)
        login(self.client, teacher)
        r = self.client.post(
            PROFILE_URL,
            {"subjects": [str(self.scoped_a_subject.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_global_subject_always_usable(self):
        teacher = self._teacher()
        login(self.client, teacher)
        r = self.client.post(
            PROFILE_URL,
            {"subjects": [str(self.global_subject.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
