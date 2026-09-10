"""
Student "Find Teachers" browse - sort controls.

Bug: results were only ever sorted by rating; `?ordering=experience` was
silently ignored (experience wasn't an allowed sort field) and the UI had
no sort control at all, so a student could never see teachers ordered by
experience even though every card shows it.

Run:  python manage.py test apps.search --settings=config.settings.test
"""

from decimal import Decimal

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.subjects.models import Subject
from apps.teacher_profile.models import TeacherProfile, TeachingMode, VerificationStatus
from apps.teachers.models import Teacher


class TeacherSearchOrderingTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.subject = Subject.objects.create(name="Guitar")
        # name, experience, rating, hourly_rate
        cls.specs = [
            ("Anita", 15, "4.20", 800),
            ("Bibek", 10, "4.90", 400),
            ("Chandan", 5, "4.50", 1200),
            ("Deepa", 2, "4.70", None),  # no rate set
            ("Esha", None, "4.10", 600),  # no experience set
        ]
        for name, exp, rating, rate in cls.specs:
            u = make_user(
                role=UserRole.TEACHER, email=f"{name.lower()}@g.test", first_name=name
            )
            t = Teacher.objects.create(user=u, experience_years=exp)
            p = TeacherProfile.objects.create(
                teacher=t,
                teaching_mode=TeachingMode.BOTH,
                rating=Decimal(rating),
                hourly_rate=rate,
                verification_status=VerificationStatus.VERIFIED,
            )
            p.subjects.set([cls.subject])

    def _names(self, resp):
        return [
            r["teacher"]["user"]["full_name"].split()[0] for r in resp.json()["data"]
        ]

    def setUp(self):
        login(self.client, make_user(role=UserRole.STUDENT))

    def _get(self, **params):
        params["subject"] = "Guitar"
        return self.client.get("/api/v1/search/teachers/", params)

    def test_default_sort_is_rating_desc(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._names(r), ["Bibek", "Deepa", "Chandan", "Anita", "Esha"])

    def test_default_sort_breaks_rating_ties_by_experience_desc(self):
        """
        Regression (2026-08-31 audit): the browse default was
        ``-rating, -created_at`` so when ratings tie - which they almost
        always do until reviews ship - teachers came back in arbitrary
        creation order and looked "not sorted by experience". Experience
        is now the tiebreak between rating and the created_at determinism
        anchor (Section 16 priority list).
        """
        subject = Subject.objects.create(name="Drums")
        # identical rating -> experience must decide the order
        for name, exp in [("Tara", 3), ("Uma", 9), ("Vik", 1), ("Wren", None)]:
            u = make_user(
                role=UserRole.TEACHER, email=f"{name.lower()}@d.test", first_name=name
            )
            t = Teacher.objects.create(user=u, experience_years=exp)
            p = TeacherProfile.objects.create(
                teacher=t,
                teaching_mode=TeachingMode.BOTH,
                rating=Decimal("4.00"),
                verification_status=VerificationStatus.VERIFIED,
            )
            p.subjects.set([subject])

        r = self.client.get("/api/v1/search/teachers/", {"subject": "Drums"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._names(r), ["Uma", "Tara", "Vik", "Wren"])  # 9,3,1,NULL

    def test_sort_by_experience_desc(self):
        r = self._get(ordering="-experience")
        self.assertEqual(r.status_code, 200)
        # 15, 10, 5, 2, then the NULL-experience teacher last
        self.assertEqual(self._names(r), ["Anita", "Bibek", "Chandan", "Deepa", "Esha"])

    def test_sort_by_experience_asc_still_puts_nulls_last(self):
        r = self._get(ordering="experience")
        self.assertEqual(self._names(r)[:4], ["Deepa", "Chandan", "Bibek", "Anita"])
        self.assertEqual(self._names(r)[-1], "Esha")  # NULL experience never floats up

    def test_sort_by_price_low_to_high_nulls_last(self):
        r = self._get(ordering="price")
        self.assertEqual(self._names(r)[:3], ["Bibek", "Esha", "Anita"])
        self.assertEqual(self._names(r)[-1], "Deepa")  # NULL rate last

    def test_price_alias_and_hourly_rate_alias_are_equivalent(self):
        self.assertEqual(
            self._names(self._get(ordering="-price")),
            self._names(self._get(ordering="-hourly_rate")),
        )

    def test_unknown_ordering_value_falls_back_to_default(self):
        r = self._get(ordering="banana")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._names(r), self._names(self._get()))
