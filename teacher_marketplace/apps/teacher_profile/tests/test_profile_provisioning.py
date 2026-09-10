"""
A freshly-registered teacher must be able to create their marketplace
Teaching Profile straight away - without first submitting a separate
"basic details" form. The basic apps.teachers.Teacher row is provisioned
lazily by TeacherProfileView.

Run:  python manage.py test apps.teacher_profile --settings=config.settings.test
"""

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.languages.models import Language
from apps.subjects.models import Subject
from apps.teacher_profile.models import TeacherProfile
from apps.teachers.models import Teacher


class TeacherProfileProvisioningTest(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.math = Subject.objects.create(name="Karate")
        cls.english = Language.objects.create(name="English", code="en")

    def test_new_teacher_can_create_marketplace_profile_without_a_teacher_row(self):
        user = make_user(role=UserRole.TEACHER, email="karate@teacher.test")
        self.assertFalse(Teacher.objects.filter(user=user).exists())

        login(self.client, user)
        resp = self.client.post(
            "/api/v1/teachers/profile/",
            {
                "headline": "Karate Teacher",
                "teaching_mode": "both",
                "hourly_rate": 100,
                "subjects": [str(self.math.id)],
                "languages": [str(self.english.id)],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        # the basic Teacher record was provisioned automatically
        self.assertTrue(Teacher.objects.filter(user=user).exists())
        self.assertEqual(TeacherProfile.objects.filter(teacher__user=user).count(), 1)

    def test_get_before_any_profile_still_404s_cleanly(self):
        user = make_user(role=UserRole.TEACHER, email="k2@teacher.test")
        login(self.client, user)
        resp = self.client.get("/api/v1/teachers/profile/")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", str(resp.json()).lower())

    def test_basic_details_still_editable_after_marketplace_profile_created(self):
        user = make_user(role=UserRole.TEACHER, email="k3@teacher.test")
        login(self.client, user)
        self.client.post(
            "/api/v1/teachers/profile/",
            {
                "headline": "x",
                "teaching_mode": "online",
                "subjects": [str(self.math.id)],
                "languages": [str(self.english.id)],
            },
            format="json",
        )
        patch = self.client.patch(
            "/api/v1/teachers/me/",
            {"bio": "10 years teaching karate", "experience_years": 10},
            format="json",
        )
        self.assertEqual(patch.status_code, 200, patch.content)
        self.assertEqual(Teacher.objects.get(user=user).experience_years, 10)

    def test_post_teachers_me_upserts_instead_of_ignoring_the_body(self):
        user = make_user(role=UserRole.TEACHER, email="k4@teacher.test")
        login(self.client, user)
        # first POST creates
        r1 = self.client.post("/api/v1/teachers/me/", {"bio": "first"}, format="json")
        self.assertEqual(r1.status_code, 201, r1.content)
        # second POST must APPLY the new data, not silently return the old row
        r2 = self.client.post(
            "/api/v1/teachers/me/",
            {"bio": "updated", "experience_years": 12, "qualification_level": "other"},
            format="json",
        )
        self.assertEqual(r2.status_code, 200, r2.content)
        t = Teacher.objects.get(user=user)
        self.assertEqual(t.bio, "updated")
        self.assertEqual(t.experience_years, 12)
        self.assertEqual(t.qualification_level, "other")

    def test_invalid_qualification_level_is_a_clean_field_error(self):
        user = make_user(role=UserRole.TEACHER, email="k5@teacher.test")
        login(self.client, user)
        self.client.post("/api/v1/teachers/me/", {"bio": "x"}, format="json")
        resp = self.client.post(
            "/api/v1/teachers/me/", {"qualification_level": "Black belt"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        # the error must be keyed to the field so the UI can highlight it
        self.assertIn("qualification_level", str(body).lower())

    def test_blank_qualification_level_is_accepted(self):
        user = make_user(role=UserRole.TEACHER, email="k6@teacher.test")
        login(self.client, user)
        resp = self.client.post(
            "/api/v1/teachers/me/",
            {"bio": "x", "qualification_level": None, "city": None},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
