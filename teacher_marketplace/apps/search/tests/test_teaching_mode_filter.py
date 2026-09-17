"""
Student "Find Teachers" browse - ?teaching_mode= filter.

"How you'd like to learn" is two independently-toggleable checkboxes
(Online / In person), sent as a comma-separated ?teaching_mode= value, not
one 3-way choice:

  - ONE mode checked   -> that mode OR a BOTH-mode teacher (a teacher who
    covers both clearly covers just one of them too).
  - BOTH modes checked -> ONLY a BOTH-mode teacher - a teacher who only
    does Online (or only Offline) does not satisfy a student who checked
    both boxes.
  - neither checked (param absent) -> no filter, show everyone.

Earlier bug this supersedes: a plain exact `teaching_mode = value` match
used to hide every BOTH-mode teacher from a single-mode search entirely.

Run:  python manage.py test apps.search --settings=config.settings.test
"""

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.subjects.models import Subject
from apps.teacher_profile.models import TeacherProfile, TeachingMode, VerificationStatus
from apps.teachers.models import Teacher


class TeachingModeFilterTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.subject = Subject.objects.create(name="AI")

        def make(name, mode):
            u = make_user(
                role=UserRole.TEACHER, email=f"{name.lower()}@g.test", first_name=name
            )
            t = Teacher.objects.create(user=u)
            p = TeacherProfile.objects.create(
                teacher=t,
                teaching_mode=mode,
                verification_status=VerificationStatus.VERIFIED,
            )
            p.subjects.set([cls.subject])
            return p

        cls.online_only = make("OnlineOnly", TeachingMode.ONLINE)
        cls.offline_only = make("OfflineOnly", TeachingMode.OFFLINE)
        cls.both = make("Both", TeachingMode.BOTH)

    def setUp(self):
        login(self.client, make_user(role=UserRole.STUDENT))

    def _names(self, mode=None):
        params = {"subject": "AI"}
        if mode is not None:
            params["teaching_mode"] = mode
        resp = self.client.get("/api/v1/search/teachers/", params)
        self.assertEqual(resp.status_code, 200, resp.content)
        return {
            r["teacher"]["user"]["full_name"].split()[0] for r in resp.json()["data"]
        }

    def test_online_only_checkbox_includes_online_and_both_not_offline(self):
        self.assertEqual(self._names("online"), {"OnlineOnly", "Both"})

    def test_in_person_only_checkbox_includes_offline_and_both_not_online(self):
        self.assertEqual(self._names("offline"), {"OfflineOnly", "Both"})

    def test_both_checkboxes_include_only_the_both_mode_teacher(self):
        self.assertEqual(self._names("online,offline"), {"Both"})

    def test_neither_checkbox_includes_everyone(self):
        self.assertEqual(
            self._names(None), {"OnlineOnly", "OfflineOnly", "Both"}
        )
