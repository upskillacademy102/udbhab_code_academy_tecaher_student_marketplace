"""
GET /api/v1/public/stats/ — the one JSON endpoint apps.web owns, used by
the landing page's real-numbers section.

Run: python manage.py test apps.web.tests.test_public_stats \
     --settings=config.settings.test
"""

from django.core.cache import cache
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_user
from apps.subjects.models import Subject
from apps.teacher_profile.models import TeacherProfile, VerificationStatus
from apps.teachers.models import Teacher

URL = "/api/v1/public/stats/"


class PublicStatsTests(APITestCase):
    def setUp(self):
        cache.clear()  # the view caches for 5 minutes; start each test clean

    def test_anonymous_can_read_it(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()["data"]
        self.assertIn("verified_teachers", data)
        self.assertIn("subjects", data)
        self.assertIn("students", data)

    def test_counts_are_real(self):
        Subject.objects.create(name="Origami")
        t1 = Teacher.objects.create(user=make_user(role=UserRole.TEACHER), experience_years=2)
        TeacherProfile.objects.create(teacher=t1, verification_status=VerificationStatus.VERIFIED)
        t2 = Teacher.objects.create(
            user=make_user(role=UserRole.TEACHER, email="t2@x.test"), experience_years=1
        )
        TeacherProfile.objects.create(teacher=t2, verification_status=VerificationStatus.PENDING)
        make_user(role=UserRole.STUDENT)

        data = self.client.get(URL).json()["data"]
        self.assertGreaterEqual(data["subjects"], 1)
        self.assertGreaterEqual(data["verified_teachers"], 1)
        self.assertGreaterEqual(data["students"], 1)

    def test_response_is_cached_briefly(self):
        before = self.client.get(URL).json()["data"]
        Subject.objects.create(name="Origami")
        after = self.client.get(URL).json()["data"]
        self.assertEqual(before["subjects"], after["subjects"])  # served from cache
        cache.clear()
        fresh = self.client.get(URL).json()["data"]
        self.assertEqual(fresh["subjects"], before["subjects"] + 1)
