"""
Regression tests for teacher-workspace pages — the values the templates hard-code
must line up with what the API accepts.

Run:  python manage.py test apps.web.tests.test_teacher_pages --settings=config.settings.test
"""

import re
from pathlib import Path

from django.conf import settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.teacher_profile.models import ExceptionType, TeacherProfile

TEMPLATES = Path(settings.BASE_DIR) / "templates" / "web"


class AvailabilityPageContractTests(APITestCase):
    """
    BUG (2026-08-31 teacher-workflow audit): the "Add exception" form on
    templates/web/teacher/availability.html POSTed
    ``exception_type: "temporary_unavailability"`` but the model choice is
    ``temporary_unavailable`` -> every time-off addition 400'd.
    """

    def _teacher_with_profile(self):
        user = make_user(role=UserRole.TEACHER)
        from apps.teachers.models import Teacher

        teacher = Teacher.objects.create(user=user)
        TeacherProfile.objects.create(teacher=teacher)
        login(self.client, user)
        return user

    def test_availability_template_uses_a_real_exception_type(self):
        html = (TEMPLATES / "teacher" / "availability.html").read_text(encoding="utf-8")
        used = set(re.findall(r"exception_type:\s*[\"']([^\"']+)[\"']", html))
        self.assertTrue(
            used, "availability.html no longer hard-codes an exception_type"
        )
        valid = set(ExceptionType.values)
        self.assertTrue(
            used <= valid,
            f"availability.html sends exception_type {used - valid} not in {valid}",
        )

    def test_api_accepts_the_exception_type_the_page_sends(self):
        self._teacher_with_profile()
        resp = self.client.post(
            "/api/v1/teachers/profile/schedule-exceptions/",
            {
                "date": "2026-09-15",
                "reason": "Travel",
                "exception_type": "temporary_unavailable",
                "timezone": "Asia/Kolkata",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["data"]["exception_type"], "temporary_unavailable")
