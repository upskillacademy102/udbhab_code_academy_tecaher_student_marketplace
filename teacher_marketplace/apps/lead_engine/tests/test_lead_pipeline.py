"""
End-to-end coverage of the lead-generation -> matching -> ranking ->
distribution pipeline, plus regression tests for the bugs found during the
2026-08-30 audit.

Run:  python manage.py test apps.lead_engine --settings=config.settings.test

The pipeline has TWO layers that run back-to-back from
StudentRequirementListCreateView.create():

  1. generate_leads_for_requirement()  (apps.lead_engine)
       SOFT match. Candidate = VERIFIED + teaches subject (+ language if the
       student named one). Each candidate is scored 0-100 by MatchingService
       (10 weighted components, time = 30%, premium = 2%). Candidates at or
       above settings.MINIMUM_LEAD_MATCH_SCORE (40) get a Lead + LeadMatchScore
       row, ordered by RankingService (match_score desc, then time, rating,
       profile age). A Lead does NOT require a time overlap.

  2. LeadDistributionService.distribute_lead()  (apps.matching)
       HARD gate. EligibilityService requires subject AND language AND a real
       time overlap AND (offline/both) location within the expanding radius.
       Eligible teachers are grouped by subscription tier
       (settings.SUBSCRIPTION_PRIORITY_ORDER = Elite > Professional > Free);
       only the top non-empty tier is offered a LeadAssignment in stage 1. On
       reject/expiry of an entire stage the next tier is offered.
"""

from datetime import time, timedelta
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.languages.models import Language
from apps.lead_engine.models import Lead, LeadStatus
from apps.lead_engine.services import generate_leads_for_requirement
from apps.location.models import City, Country, State
from apps.matching.models import (
    AssignmentStatus,
    LeadAssignment,
    PincodeLocation,
    SubjectAlias,
)
from apps.matching.services.lead_distribution_service import LeadDistributionService
from apps.student_requirement.models import (
    RequirementStatus,
    StudentRequirement,
    StudentRequirementLanguage,
    StudentSchedulePreference,
)
from apps.subjects.models import Subject
from apps.subscriptions.models import (
    SubscriptionPlan,
    SubscriptionStatus,
    TeacherSubscription,
)
from apps.teacher_profile.models import (
    TeacherProfile,
    TeacherWeeklyAvailability,
    TeachingMode,
    VerificationStatus,
)
from apps.teachers.models import Teacher

IST = "Asia/Kolkata"


class PipelineFixtureMixin:
    """Reference data + a teacher factory shared by every test class below."""

    @classmethod
    def setUpTestData(cls):
        cls.country = Country.objects.create(name="India", code="IN")
        cls.state = State.objects.create(country=cls.country, name="West Bengal")
        cls.kolkata = City.objects.create(state=cls.state, name="Kolkata")
        cls.howrah = City.objects.create(state=cls.state, name="Howrah")

        cls.math = Subject.objects.create(name="Mathematics")
        cls.physics = Subject.objects.create(name="Physics")
        cls.english = Language.objects.create(name="English", code="en")
        cls.hindi = Language.objects.create(name="Hindi", code="hi")

        # Plans are created by subscriptions.0002_seed_default_plans, which
        # runs against the test database too - assert that here so a broken
        # seed migration fails loudly rather than as a mysterious 400 later.
        cls.free_plan = SubscriptionPlan.objects.get(name="Free")
        cls.pro_plan = SubscriptionPlan.objects.get(name="Professional")
        cls.elite_plan = SubscriptionPlan.objects.get(name="Elite")

        # Pincodes ~2 km (near), ~10 km (mid) and ~40 km (far) from the student.
        cls.pin_student = PincodeLocation.objects.create(
            pincode="700001",
            location=Point(88.3639, 22.5726, srid=4326),
            city="Kolkata",
        )
        cls.pin_near = PincodeLocation.objects.create(
            pincode="700020",
            location=Point(88.3800, 22.5550, srid=4326),
            city="Kolkata",
        )
        cls.pin_mid = PincodeLocation.objects.create(
            pincode="700030",
            location=Point(88.4639, 22.5726, srid=4326),
            city="Kolkata",
        )
        cls.pin_far = PincodeLocation.objects.create(
            pincode="713101",
            location=Point(87.8500, 23.2300, srid=4326),
            city="Asansol",
        )

    def make_teacher(
        self,
        name,
        *,
        subjects=None,
        languages=None,
        mode=TeachingMode.BOTH,
        availability=((1, time(17, 0), time(21, 0), IST),),
        rating="4.50",
        experience=5,
        plan=None,
        cities=None,
        pincode=None,
        verified=True,
        active=True,
        tokens=0,
    ):
        user = make_user(
            role=UserRole.TEACHER,
            email=f"{name.lower()}@teacher.test",
            first_name=name,
            last_name="T",
            is_active=active,
        )
        teacher = Teacher.objects.create(
            user=user,
            experience_years=experience,
            profile_photo="teachers/profile_photos/test.jpg",
        )
        if pincode is not None:
            teacher.pincode_location = pincode
            teacher.save(update_fields=["pincode_location"])
        profile = TeacherProfile.objects.create(
            teacher=teacher,
            teaching_mode=mode,
            rating=Decimal(rating),
            verification_status=(
                VerificationStatus.VERIFIED if verified else VerificationStatus.PENDING
            ),
        )
        profile.subjects.set(subjects or [self.math])
        profile.languages.set(languages or [self.english])
        profile.cities.set(cities or [])
        for day, start, end, tz in availability:
            TeacherWeeklyAvailability.objects.create(
                teacher_profile=profile,
                day_of_week=day,
                start_time=start,
                end_time=end,
                timezone=tz,
                is_active=True,
            )
        if plan is not None:
            now = timezone.now()
            TeacherSubscription.objects.create(
                teacher=teacher,
                plan=plan,
                status=SubscriptionStatus.ACTIVE,
                start_date=now,
                end_date=now + timedelta(days=30),
            )
        if tokens:
            from apps.wallet.services import WalletService

            # credit() reads an existing row (it never creates one), so the
            # wallet has to exist before seeding a balance.
            WalletService.get_or_create_wallet(teacher)
            WalletService.credit(
                teacher=teacher, amount=tokens, description="test seed"
            )
        if not active:
            user.is_active = False
            user.save(update_fields=["is_active"])
        return profile

    def make_requirement(
        self,
        student=None,
        *,
        subject=None,
        languages=None,
        no_language_preference=False,
        mode=TeachingMode.ONLINE,
        city=None,
        pincode=None,
        duration=60,
        preferences=((1, time(18, 0), time(19, 0), IST, "flexible"),),
    ):
        student = student or make_user(role=UserRole.STUDENT)
        req = StudentRequirement.objects.create(
            student=student,
            subject=subject or self.math,
            teaching_mode=mode,
            city=city,
            pincode_location=pincode,
            class_duration_minutes=duration,
            no_language_preference=no_language_preference,
        )
        if not no_language_preference:
            for rank, language in enumerate(languages or [self.english], start=1):
                StudentRequirementLanguage.objects.create(
                    student_requirement=req, language=language, rank=rank
                )
        for day, start, end, tz, flex in preferences:
            StudentSchedulePreference.objects.create(
                student_requirement=req,
                day_of_week=day,
                start_time=start,
                end_time=end,
                timezone=tz,
                flexibility=flex,
            )
        return req

    @staticmethod
    def run_pipeline(requirement):
        leads = generate_leads_for_requirement(requirement)
        assignments = []
        for lead in leads:
            assignments += LeadDistributionService.distribute_lead(lead)
        return leads, assignments

    def post_requirement(self, payload):
        """
        POST a requirement through the real API and run the
        transaction.on_commit callback (which enqueues the Celery
        distribution task - eager in tests) before returning, so
        assertions on Lead/LeadAssignment see the finished state.
        """
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                "/api/v1/student-requirements/", payload, format="json"
            )


# ======================================================================
# BUG REGRESSION TESTS
# ======================================================================
class FreePlanSeededRegressionTest(PipelineFixtureMixin, APITestCase):
    """
    BUG A: get_effective_plan() raised 'No Free plan is configured' because
    nothing seeded SubscriptionPlan rows, turning every requirement POST that
    matched a verified teacher into an HTTP 400.
    """

    def test_free_plan_exists_after_migrations(self):
        self.assertTrue(SubscriptionPlan.objects.filter(name__iexact="Free").exists())

    def test_lead_generation_runs_without_a_subscription(self):
        self.make_teacher("Anita")  # verified, no subscription row at all
        req = self.make_requirement()
        leads, _ = self.run_pipeline(req)
        self.assertEqual(len(leads), 1)  # would have raised before the fix


class SchedulePreferenceDistributionRegressionTest(PipelineFixtureMixin, APITestCase):
    """
    BUG B: structured schedule preferences could not be supplied when creating
    a requirement through the API, so at distribution time student_slots was
    always [] -> EligibilityService rejected every teacher on 'no_time_overlap'
    -> zero LeadAssignment rows were ever created via the primary flow.
    """

    def test_requirement_api_accepts_inline_schedule_preferences(self):
        profile = self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)

        resp = self.post_requirement(
            {
                "subject": "Mathematics",
                "preferred_languages": ["English"],
                "teaching_mode": "online",
                "class_duration_minutes": 60,
                "schedule_preferences": [
                    {
                        "day_of_week": 1,
                        "start_time": "18:00",
                        "end_time": "19:00",
                        "timezone": IST,
                        "flexibility": "flexible",
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        self.assertEqual(resp.json()["distribution_status"], "queued")
        req = StudentRequirement.objects.get(student=student)
        self.assertEqual(req.schedule_preferences.count(), 1)
        req.refresh_from_db()
        self.assertEqual(req.lead_distribution_status, "completed")

        # The hard-gated tiered distribution actually fired.
        assignments = LeadAssignment.objects.filter(lead__student_requirement=req)
        self.assertEqual(assignments.count(), 1)
        self.assertEqual(assignments.first().teacher_id, profile.teacher_id)

    def test_updating_requirement_replaces_schedule_preferences(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        self.post_requirement(
            {
                "subject": "Mathematics",
                "preferred_languages": ["English"],
                "teaching_mode": "online",
                "schedule_preferences": [
                    {
                        "day_of_week": 1,
                        "start_time": "18:00",
                        "end_time": "19:00",
                        "timezone": IST,
                    }
                ],
            },
        )
        req = StudentRequirement.objects.get(student=student)
        # Re-submit the SAME window on PATCH - must not trip the unique constraint.
        patch = self.client.patch(
            f"/api/v1/student-requirements/{req.id}/",
            {
                "schedule_preferences": [
                    {
                        "day_of_week": 1,
                        "start_time": "18:00",
                        "end_time": "19:00",
                        "timezone": IST,
                    },
                    {
                        "day_of_week": 3,
                        "start_time": "17:00",
                        "end_time": "18:00",
                        "timezone": IST,
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(patch.status_code, 200, patch.content)
        self.assertEqual(req.schedule_preferences.count(), 2)

    def test_requirement_without_preferences_still_generates_soft_leads(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        resp = self.post_requirement(
            {
                "subject": "Mathematics",
                "preferred_languages": ["English"],
                "teaching_mode": "online",
            },
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        req = StudentRequirement.objects.get(student=student)
        self.assertEqual(Lead.objects.filter(student_requirement=req).count(), 1)
        # ...but no hard-gated assignment, because no time window was expressed.
        self.assertEqual(
            LeadAssignment.objects.filter(lead__student_requirement=req).count(), 0
        )


class OfflineCityGeocodeRegressionTest(PipelineFixtureMixin, APITestCase):
    """
    BUG (2026-08-31 audit): POSTing a requirement with teaching_mode
    offline/both and a city NAME (not a pincode) 500'd.

      1. geocoding_service.get_or_geocode_city built its query string with
         ``", ".join([city.name, city.state, city.country])`` - but
         ``city.state`` / ``city.country`` are State / Country *instances*,
         so the join raised ``TypeError: expected str instance, State found``.
      2. Once (1) was fixed, the synthetic centroid key ``f"CITY:{city.id}"``
         (~41 chars) overflowed ``PincodeLocation.pincode`` which was
         ``varchar(10)`` -> ``DataError: value too long``.

    Either way the student got an opaque 500 on a core-flow action.
    """

    def _post_offline(self):
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        return student, self.post_requirement(
            {
                "subject": "Mathematics",
                "preferred_languages": ["English"],
                "teaching_mode": "offline",
                "city": "Kolkata",
                "schedule_preferences": [
                    {
                        "day_of_week": 1,
                        "start_time": "18:00",
                        "end_time": "19:00",
                        "timezone": IST,
                    }
                ],
            },
        )

    def test_offline_requirement_with_city_name_geocodes_and_succeeds(self):
        from unittest.mock import patch as _patch

        self.make_teacher("Anita", plan=self.elite_plan)
        with _patch(
            "apps.matching.services.geocoding_service."
            "PincodeGeocodingService._geocode_place_nominatim",
            return_value=(22.5726, 88.3639),
        ):
            student, resp = self._post_offline()

        self.assertEqual(resp.status_code, 202, resp.content)
        req = StudentRequirement.objects.get(student=student)
        self.assertIsNotNone(req.city_id)
        # The synthetic centroid row that used to overflow varchar(10).
        centroid = PincodeLocation.objects.get(pincode=f"CITY:{req.city_id}")
        self.assertEqual(centroid.state, "West Bengal")
        self.assertEqual(centroid.country, "India")

    def test_offline_requirement_survives_geocoder_outage(self):
        from unittest.mock import patch as _patch

        from apps.matching.services.geocoding_service import GeocodingError

        self.make_teacher("Anita", plan=self.elite_plan)
        with _patch(
            "apps.matching.services.geocoding_service."
            "PincodeGeocodingService._geocode_place_nominatim",
            side_effect=GeocodingError(detail="down"),
        ):
            student, resp = self._post_offline()

        # Geocoding is best-effort: a provider outage must NOT 500 the student.
        self.assertEqual(resp.status_code, 202, resp.content)
        req = StudentRequirement.objects.get(student=student)
        self.assertIsNotNone(req.city_id)

    def test_city_centroid_geocode_is_deferred_out_of_the_request(self):
        """
        The requirement POST resolves the City synchronously (fast DB match)
        but must NOT make the outbound city-centroid geocode call - that runs
        in process_requirement_leads so a slow geocoder can't delay the POST.
        """
        from unittest.mock import patch as _patch

        self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)

        with _patch(
            "apps.matching.services.geocoding_service."
            "PincodeGeocodingService.get_or_geocode_city"
        ) as geocode:
            # No captureOnCommitCallbacks: the async task never runs here.
            resp = self.client.post(
                "/api/v1/student-requirements/",
                {
                    "subject": "Mathematics",
                    "preferred_languages": ["English"],
                    "teaching_mode": "offline",
                    "city": "Kolkata",
                    "schedule_preferences": [
                        {
                            "day_of_week": 1,
                            "start_time": "18:00",
                            "end_time": "19:00",
                            "timezone": IST,
                        }
                    ],
                },
                format="json",
            )

        self.assertEqual(resp.status_code, 202, resp.content)
        geocode.assert_not_called()
        req = StudentRequirement.objects.get(student=student)
        self.assertIsNotNone(req.city_id)  # City resolved synchronously
        self.assertIsNone(req.pincode_location_id)  # centroid deferred to the task


class EligibleSearchRegressionTest(PipelineFixtureMixin, APITestCase):
    """The eligibility-gated teacher search shares EligibilityService with
    distribution, so Bug D (match_by_id TypeError) 500'd it too."""

    def test_search_returns_ranked_eligible_teachers(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        self.make_teacher(
            "Farid", availability=((6, time(9, 0), time(11, 0), IST),)
        )  # no overlap
        login(self.client, make_user(role=UserRole.STUDENT))
        resp = self.client.get(
            "/api/v1/matching/search/teachers/",
            {
                "subject": "Mathematics",
                "language": "English",
                "day": 1,
                "start_time": "18:00",
                "end_time": "19:00",
                "teaching_mode": "online",
                "timezone": IST,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        names = [row["teacher_name"] for row in resp.json()["data"]]
        self.assertIn("Anita T", names)
        self.assertNotIn("Farid T", names)


class RequirementStatusRegressionTest(PipelineFixtureMixin, APITestCase):
    """BUG C: RequirementStatus.MATCHED was documented as 'set by lead_engine'
    but never actually set."""

    def test_status_advances_to_matched_when_a_lead_is_generated(self):
        self.make_teacher("Anita")
        req = self.make_requirement()
        self.assertEqual(req.status, RequirementStatus.OPEN)
        self.run_pipeline(req)
        req.refresh_from_db()
        self.assertEqual(req.status, RequirementStatus.MATCHED)

    def test_status_unchanged_when_no_lead_is_generated(self):
        self.make_teacher("Deepa", subjects=[self.physics])  # wrong subject
        req = self.make_requirement()
        self.run_pipeline(req)
        req.refresh_from_db()
        self.assertEqual(req.status, RequirementStatus.OPEN)


# ======================================================================
# MATCHING / ELIGIBILITY EDGE CASES
# ======================================================================
class MatchingEdgeCaseTests(PipelineFixtureMixin, APITestCase):

    def test_exact_subject_matches(self):
        self.make_teacher("Anita")
        leads, _ = self.run_pipeline(self.make_requirement())
        self.assertEqual(len(leads), 1)

    def test_subject_alias_resolves_via_api(self):
        SubjectAlias.objects.create(subject=self.math, alias_text="maths")
        self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        resp = self.post_requirement(
            {
                "subject": "maths",
                "preferred_languages": ["English"],
                "teaching_mode": "online",
                "schedule_preferences": [
                    {
                        "day_of_week": 1,
                        "start_time": "18:00",
                        "end_time": "19:00",
                        "timezone": IST,
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        req = StudentRequirement.objects.get(student=student)
        self.assertEqual(req.subject_id, self.math.id)

    def test_wrong_subject_excluded_entirely(self):
        self.make_teacher("Deepa", subjects=[self.physics])
        leads, assignments = self.run_pipeline(self.make_requirement())
        self.assertEqual(leads, [])
        self.assertEqual(assignments, [])

    def test_wrong_language_excluded_from_candidates(self):
        self.make_teacher("Esha", languages=[self.hindi])
        leads, _ = self.run_pipeline(self.make_requirement(languages=[self.english]))
        self.assertEqual(leads, [])

    def test_no_language_preference_matches_any_language(self):
        self.make_teacher("Esha", languages=[self.hindi])
        req = self.make_requirement(no_language_preference=True)
        leads, assignments = self.run_pipeline(req)
        self.assertEqual(len(leads), 1)

    def test_lower_ranked_language_match_scores_below_top_choice(self):
        # Esha only speaks Hindi (the student's rank-2 choice); Farid speaks
        # both. Esha should score lower than Farid on the language
        # component specifically, per MatchingService._LANGUAGE_RANK_SCORES.
        self.make_teacher("Esha", languages=[self.hindi])
        self.make_teacher("Farid", languages=[self.english, self.hindi])
        req = self.make_requirement(languages=[self.english, self.hindi])
        leads, _ = self.run_pipeline(req)
        scores = {
            lead.teacher_profile.teacher.user.first_name: lead.match_score.language_score
            for lead in leads
        }
        self.assertEqual(scores["Farid"], 100)
        self.assertEqual(scores["Esha"], 80)

    def test_any_listed_language_passes_the_hard_eligibility_gate(self):
        # Esha speaks only the student's SECOND choice - still eligible for
        # an actual offer (LeadAssignment), not just a soft Lead: rank
        # affects relative score, not the pass/fail gate.
        self.make_teacher("Esha", languages=[self.hindi])
        req = self.make_requirement(languages=[self.english, self.hindi])
        leads, assignments = self.run_pipeline(req)
        self.assertEqual(len(leads), 1)
        self.assertEqual(len(assignments), 1)
        self.assertEqual(len(assignments), 1)

    def test_time_overlap_required_for_distribution_not_for_soft_lead(self):
        # Saturday-only teacher vs a Monday-evening requirement.
        self.make_teacher("Farid", availability=((6, time(9, 0), time(11, 0), IST),))
        leads, assignments = self.run_pipeline(self.make_requirement())
        self.assertEqual(len(leads), 1)  # soft lead still created
        self.assertEqual(assignments, [])  # but not eligible for an offer
        self.assertEqual(leads[0].match_score.time_score, 0)

    def test_partial_time_overlap_is_eligible(self):
        # Teacher free 18:30-19:30, student wants 18:00-19:00 -> 30 min overlap.
        self.make_teacher("Anita", availability=((1, time(18, 30), time(19, 30), IST),))
        _, assignments = self.run_pipeline(self.make_requirement())
        self.assertEqual(len(assignments), 1)

    def test_boundary_touching_windows_do_not_overlap(self):
        # Teacher free 19:00-21:00, student wants 18:00-19:00 -> touch at 19:00.
        self.make_teacher("Anita", availability=((1, time(19, 0), time(21, 0), IST),))
        _, assignments = self.run_pipeline(self.make_requirement())
        self.assertEqual(assignments, [])

    def test_online_requirement_ignores_location(self):
        self.make_teacher("Anita", mode=TeachingMode.ONLINE, cities=[], pincode=None)
        _, assignments = self.run_pipeline(
            self.make_requirement(mode=TeachingMode.ONLINE)
        )
        self.assertEqual(len(assignments), 1)

    def test_offline_only_teacher_excluded_from_online_requirement(self):
        # Teaching-mode compatibility used to be checked nowhere as a hard
        # gate in EligibilityService (only ever soft-scored in the Lead
        # pipeline) - a strictly offline teacher, who has explicitly said
        # they never teach online, could still be marked eligible for and
        # offered a purely online lead.
        self.make_teacher("Imran", mode=TeachingMode.OFFLINE, cities=[], pincode=None)
        leads, assignments = self.run_pipeline(
            self.make_requirement(mode=TeachingMode.ONLINE)
        )
        self.assertEqual(leads, [])
        self.assertEqual(assignments, [])

    def test_online_only_teacher_excluded_from_offline_requirement(self):
        self.make_teacher("Zara", mode=TeachingMode.ONLINE, cities=[], pincode=None)
        leads, assignments = self.run_pipeline(
            self.make_requirement(mode=TeachingMode.OFFLINE, city=self.kolkata)
        )
        self.assertEqual(leads, [])
        self.assertEqual(assignments, [])

    def test_pending_verification_excluded(self):
        self.make_teacher("Gita", verified=False)
        leads, _ = self.run_pipeline(self.make_requirement())
        self.assertEqual(leads, [])

    def test_inactive_teacher_user_excluded_from_distribution(self):
        # Profile still VERIFIED but the underlying account is disabled.
        self.make_teacher("Hari", active=False)
        leads, assignments = self.run_pipeline(self.make_requirement())
        self.assertEqual(assignments, [])


# ======================================================================
# LOCATION EXPANSION
# ======================================================================
class LocationExpansionTests(PipelineFixtureMixin, APITestCase):

    def _offline_requirement(self):
        return self.make_requirement(
            mode=TeachingMode.OFFLINE, city=self.kolkata, pincode=self.pin_student
        )

    def test_nearby_offline_teacher_is_eligible(self):
        self.make_teacher(
            "Anita",
            mode=TeachingMode.OFFLINE,
            cities=[self.kolkata],
            pincode=self.pin_near,
        )
        _, assignments = self.run_pipeline(self._offline_requirement())
        self.assertEqual(len(assignments), 1)

    def test_far_offline_teacher_is_ineligible(self):
        # A ~40km-away teacher must be excluded even from the soft Lead
        # (visible in the teacher's "Leads" and payable via
        # /leads/unlock/) - not just from the real LeadAssignment offer.
        # Before this was a hard gate, real distance only fed a 10%-
        # weighted score that a strong subject/time/language match easily
        # outweighed, so a teacher 40km away for an in-person lesson still
        # showed up as a lead the student had no realistic way to use.
        self.make_teacher(
            "Bibek",
            mode=TeachingMode.OFFLINE,
            cities=[self.kolkata],
            pincode=self.pin_far,
        )
        leads, assignments = self.run_pipeline(self._offline_requirement())
        self.assertEqual(leads, [])  # outside 20 km max radius - no soft lead either
        self.assertEqual(assignments, [])  # outside 20 km max radius

    def test_teacher_not_serving_the_city_and_without_pincode_is_excluded(self):
        # No pincode on either side falls back to the "does this teacher
        # serve that city" signal - but that fallback must be a real gate
        # now too, not the old soft 40-point partial credit that
        # MINIMUM_LEAD_MATCH_SCORE (40) let straight through regardless.
        self.make_teacher(
            "Farha", mode=TeachingMode.OFFLINE, cities=[self.howrah], pincode=None,
        )
        leads, assignments = self.run_pipeline(self._offline_requirement())
        self.assertEqual(leads, [])
        self.assertEqual(assignments, [])

    def test_missing_teacher_pincode_degrades_gracefully(self):
        self.make_teacher(
            "Chandan", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=None
        )
        # Must not raise, must not offer (location cannot be evaluated).
        leads, assignments = self.run_pipeline(self._offline_requirement())
        self.assertEqual(assignments, [])

    def test_requirement_with_only_a_pincode_excludes_an_unpincoded_teacher(self):
        # Regression: a requirement created from a raw pincode (no City
        # row at all, city_id is None - see LocationResolutionService)
        # combined with a candidate teacher who has neither a
        # pincode_location nor a served-city entry must be EXCLUDED, not
        # default-included just because there was no `city_id` to check
        # against. This is the exact real-world shape that let a ~44km
        # mismatch through: a teacher whose pincode_location had gone
        # stale (cleared/missing after a failed re-geocode) still matched
        # an offline requirement that itself had only a pincode, no city.
        self.make_teacher(
            "Wafa", mode=TeachingMode.OFFLINE, cities=[], pincode=None,
        )
        req = self.make_requirement(
            mode=TeachingMode.OFFLINE, city=None, pincode=self.pin_student
        )
        leads, assignments = self.run_pipeline(req)
        self.assertEqual(leads, [])
        self.assertEqual(assignments, [])

    def test_requirement_with_only_a_pincode_still_finds_a_nearby_teacher(self):
        self.make_teacher(
            "Yusuf", mode=TeachingMode.OFFLINE, cities=[], pincode=self.pin_near,
        )
        req = self.make_requirement(
            mode=TeachingMode.OFFLINE, city=None, pincode=self.pin_student
        )
        leads, assignments = self.run_pipeline(req)
        self.assertEqual(len(assignments), 1)

    def test_missing_student_pincode_degrades_gracefully(self):
        self.make_teacher(
            "Anita",
            mode=TeachingMode.OFFLINE,
            cities=[self.kolkata],
            pincode=self.pin_near,
        )
        req = self.make_requirement(
            mode=TeachingMode.OFFLINE, city=self.kolkata, pincode=None
        )
        leads, assignments = self.run_pipeline(req)  # no exception, no infinite loop
        self.assertEqual(assignments, [])


# ======================================================================
# NEAREST-FIRST SEQUENTIAL OFFERING (OFFLINE/BOTH ONLY)
# ======================================================================
class OfflineNearestFirstSequencingTests(PipelineFixtureMixin, APITestCase):
    """
    "Always the student near the teacher should receive the lead, and if
    they reject or the allocated time passes then only the further
    teachers should get the leads" - for an in-person lesson, distance is
    real and matters; for an online one it doesn't. So within a
    subscription tier: OFFLINE/BOTH offers the single nearest untried
    teacher at a time (cascading on reject/expiry before moving to the
    next tier); ONLINE keeps the pre-existing simultaneous fan-out
    (covered by RankingAndDistributionTests / test_online_requirement_
    ignores_location) since there is no distance to sequence by.
    """

    def _offline_requirement(self):
        return self.make_requirement(
            mode=TeachingMode.OFFLINE, city=self.kolkata, pincode=self.pin_student
        )

    def test_only_the_nearest_same_tier_teacher_is_offered_first(self):
        near = self.make_teacher(
            "Near", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_near,
        )
        self.make_teacher(
            "Mid", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_mid,
        )
        leads, assignments = self.run_pipeline(self._offline_requirement())
        self.assertEqual(len(leads), 2)  # both are still real soft-lead candidates
        self.assertEqual(len(assignments), 1)  # only the nearer one is actually offered
        self.assertEqual(assignments[0].teacher_id, near.teacher_id)

    def test_farther_teacher_offered_only_after_nearer_one_rejects(self):
        near = self.make_teacher(
            "Near", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_near,
        )
        mid = self.make_teacher(
            "Mid", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_mid,
        )
        _, assignments = self.run_pipeline(self._offline_requirement())
        self.assertEqual(assignments[0].teacher_id, near.teacher_id)
        self.assertEqual(assignments[0].assignment_stage, 1)

        LeadDistributionService.reject_assignment(assignments[0])

        lead = assignments[0].lead
        next_stage = LeadAssignment.objects.filter(lead=lead, assignment_stage=2)
        self.assertEqual(next_stage.count(), 1)
        self.assertEqual(next_stage.first().teacher_id, mid.teacher_id)
        # Still the SAME subscription tier - this is a within-tier
        # cascade, not a tier advance.
        self.assertEqual(
            next_stage.first().subscription_tier, assignments[0].subscription_tier
        )

    def test_farther_teacher_offered_only_after_nearer_one_expires(self):
        near = self.make_teacher(
            "Near", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_near,
        )
        mid = self.make_teacher(
            "Mid", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_mid,
        )
        _, assignments = self.run_pipeline(self._offline_requirement())
        self.assertEqual(assignments[0].teacher_id, near.teacher_id)

        LeadDistributionService.expire_assignment(assignments[0])

        lead = assignments[0].lead
        next_stage = LeadAssignment.objects.filter(lead=lead, assignment_stage=2)
        self.assertEqual(next_stage.count(), 1)
        self.assertEqual(next_stage.first().teacher_id, mid.teacher_id)

    def test_a_nearer_free_teacher_still_goes_before_a_farther_elite_one(self):
        # Offline/both ignores subscription tier entirely - pure distance,
        # no exceptions. Subscription only matters for ONLINE ordering.
        far_but_elite = self.make_teacher(
            "Elite", mode=TeachingMode.OFFLINE, cities=[self.kolkata],
            pincode=self.pin_mid, plan=self.elite_plan,
        )
        free_near = self.make_teacher(
            "FreeNear", mode=TeachingMode.OFFLINE, cities=[self.kolkata],
            pincode=self.pin_near, plan=None,
        )
        _, assignments = self.run_pipeline(self._offline_requirement())
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].teacher_id, free_near.teacher_id)
        self.assertEqual(assignments[0].subscription_tier, "Free")

        # Confirmed by cascade: if the near Free teacher rejects, the
        # farther Elite teacher is offered next - tier never jumps the
        # queue, it just becomes the next-nearest untried candidate.
        LeadDistributionService.reject_assignment(assignments[0])
        lead = assignments[0].lead
        next_stage = LeadAssignment.objects.filter(lead=lead, assignment_stage=2)
        self.assertEqual(next_stage.count(), 1)
        self.assertEqual(next_stage.first().teacher_id, far_but_elite.teacher_id)

    def test_tied_distance_offline_teachers_are_offered_simultaneously_regardless_of_plan(self):
        # Ties at the exact same distance go out together, no matter plan.
        elite = self.make_teacher(
            "TiedElite", mode=TeachingMode.OFFLINE, cities=[self.kolkata],
            pincode=self.pin_near, plan=self.elite_plan,
        )
        free = self.make_teacher(
            "TiedFree", mode=TeachingMode.OFFLINE, cities=[self.kolkata],
            pincode=self.pin_near, plan=None,
        )
        _, assignments = self.run_pipeline(self._offline_requirement())
        self.assertEqual(len(assignments), 2)
        self.assertEqual(
            {a.teacher_id for a in assignments}, {elite.teacher_id, free.teacher_id}
        )
        self.assertEqual(assignments[0].assigned_at, assignments[1].assigned_at)

    def test_unlocking_offline_lead_cancels_the_tied_sibling(self):
        # Offline is exclusive (unlike online): whichever tied teacher
        # unlocks first via the real API takes it, and the other's open
        # assignment is cancelled - regardless of which of the two
        # happens to be the "canonical" Lead every assignment is
        # actually anchored to (see visibility_service's docstring).
        req = self._offline_requirement()
        elite = self.make_teacher(
            "TiedElite", mode=TeachingMode.OFFLINE, cities=[self.kolkata],
            pincode=self.pin_near, plan=self.elite_plan,
        )
        free = self.make_teacher(
            "TiedFree", mode=TeachingMode.OFFLINE, cities=[self.kolkata],
            pincode=self.pin_near, plan=None,
        )
        leads, assignments = self.run_pipeline(req)
        self.assertEqual(len(assignments), 2)

        elite_lead = Lead.objects.get(teacher_profile=elite, student_requirement=req)
        login(self.client, elite.teacher.user)
        resp = self.client.post(
            "/api/v1/leads/unlock/", {"lead_id": str(elite_lead.id)}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        elite_assignment = LeadAssignment.objects.get(lead=leads[0], teacher=elite.teacher)
        free_assignment = LeadAssignment.objects.get(lead=leads[0], teacher=free.teacher)
        self.assertEqual(elite_assignment.status, AssignmentStatus.ACCEPTED)
        self.assertEqual(free_assignment.status, AssignmentStatus.CANCELLED)

        # Free's own lead is consequently no longer visible/unlockable.
        self.client.post("/api/v1/auth/logout/", {}, format="json")
        login(self.client, free.teacher.user)
        free_lead = Lead.objects.get(teacher_profile=free, student_requirement=req)
        self.assertEqual(
            self.client.get(f"/api/v1/leads/{free_lead.id}/").status_code, 404
        )

    def test_online_requirement_still_offers_the_whole_tier_at_once(self):
        # Sanity check that the offline-only sequencing change did not
        # touch online-mode behaviour.
        self.make_teacher("Anita", plan=self.elite_plan, rating="4.9")
        self.make_teacher("Amit", plan=self.elite_plan, rating="4.1")
        _, assignments = self.run_pipeline(self.make_requirement())  # default: online
        self.assertEqual(len(assignments), 2)


class LeadRejectionTests(PipelineFixtureMixin, APITestCase):
    """
    POST /leads/{id}/reject/ - a permanent, per-teacher decline of a lead
    they have not unlocked yet. Distinct from (but triggers) a
    LeadAssignment reject: it also marks the Lead itself REJECTED so
    leads_visible_to() never surfaces it to this teacher again, and it
    releases the open assignment turn immediately rather than waiting out
    the response window.
    """

    def _as(self, profile):
        login(self.client, profile.teacher.user)

    def _offline_requirement(self):
        return self.make_requirement(
            mode=TeachingMode.OFFLINE, city=self.kolkata, pincode=self.pin_student
        )

    def test_reject_releases_cascade_immediately(self):
        near = self.make_teacher(
            "Near", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_near,
        )
        mid = self.make_teacher(
            "Mid", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_mid,
        )
        req = self._offline_requirement()
        _, assignments = self.run_pipeline(req)
        near_lead = Lead.objects.get(teacher_profile=near, student_requirement=req)

        self._as(near)
        resp = self.client.post(f"/api/v1/leads/{near_lead.id}/reject/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)

        near_lead.refresh_from_db()
        self.assertEqual(near_lead.status, LeadStatus.REJECTED)
        self.assertIsNotNone(near_lead.rejected_at)

        # No 24h wait needed - the next-nearest teacher is offered right away.
        next_stage = LeadAssignment.objects.filter(
            lead=assignments[0].lead, assignment_stage=2
        )
        self.assertEqual(next_stage.count(), 1)
        self.assertEqual(next_stage.first().teacher_id, mid.teacher_id)

    def test_rejected_lead_disappears_from_teachers_own_list_permanently(self):
        near = self.make_teacher(
            "Near", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_near,
        )
        req = self._offline_requirement()
        self.run_pipeline(req)
        near_lead = Lead.objects.get(teacher_profile=near, student_requirement=req)

        self._as(near)
        self.client.post(f"/api/v1/leads/{near_lead.id}/reject/", {}, format="json")

        self.assertEqual(self.client.get("/api/v1/leads/").json()["data"], [])
        self.assertEqual(
            self.client.get(f"/api/v1/leads/{near_lead.id}/").status_code, 404
        )

    def test_cannot_reject_after_unlocking(self):
        near = self.make_teacher(
            "Near", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_near,
        )
        req = self._offline_requirement()
        self.run_pipeline(req)
        near_lead = Lead.objects.get(teacher_profile=near, student_requirement=req)

        self._as(near)
        unlock_resp = self.client.post(
            "/api/v1/leads/unlock/", {"lead_id": str(near_lead.id)}, format="json"
        )
        self.assertEqual(unlock_resp.status_code, 200, unlock_resp.content)

        resp = self.client.post(f"/api/v1/leads/{near_lead.id}/reject/", {}, format="json")
        self.assertEqual(resp.status_code, 400)
        near_lead.refresh_from_db()
        self.assertNotEqual(near_lead.status, LeadStatus.REJECTED)

    def test_cannot_reject_the_same_lead_twice(self):
        near = self.make_teacher(
            "Near", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_near,
        )
        req = self._offline_requirement()
        self.run_pipeline(req)
        near_lead = Lead.objects.get(teacher_profile=near, student_requirement=req)

        self._as(near)
        first = self.client.post(f"/api/v1/leads/{near_lead.id}/reject/", {}, format="json")
        self.assertEqual(first.status_code, 200)
        second = self.client.post(f"/api/v1/leads/{near_lead.id}/reject/", {}, format="json")
        self.assertEqual(second.status_code, 404)

    def test_cannot_reject_another_teachers_lead(self):
        near = self.make_teacher(
            "Near", mode=TeachingMode.OFFLINE, cities=[self.kolkata], pincode=self.pin_near,
        )
        other = self.make_teacher("Other", mode=TeachingMode.OFFLINE, cities=[self.kolkata])
        req = self._offline_requirement()
        self.run_pipeline(req)
        near_lead = Lead.objects.get(teacher_profile=near, student_requirement=req)

        self._as(other)
        resp = self.client.post(f"/api/v1/leads/{near_lead.id}/reject/", {}, format="json")
        self.assertEqual(resp.status_code, 404)
        near_lead.refresh_from_db()
        self.assertNotEqual(near_lead.status, LeadStatus.REJECTED)


# ======================================================================
# RANKING & TIERED DISTRIBUTION
# ======================================================================
class RankingAndDistributionTests(PipelineFixtureMixin, APITestCase):

    def _three_tier_setup(self):
        self.elite = self.make_teacher(
            "Anita", rating="4.20", experience=10, plan=self.elite_plan
        )
        self.pro = self.make_teacher(
            "Bibek", rating="4.60", experience=6, plan=self.pro_plan
        )
        self.free = self.make_teacher("Chandan", rating="4.90", experience=8, plan=None)
        return self.make_requirement()

    def test_stage_one_offers_only_the_top_tier(self):
        req = self._three_tier_setup()
        _, assignments = self.run_pipeline(req)
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].teacher_id, self.elite.teacher_id)
        self.assertEqual(assignments[0].subscription_tier, "Elite")

    def test_online_reject_does_not_cascade(self):
        # Unlike offline, an online rejection just stops for that one
        # teacher - it never triggers the next tier by itself. Only the
        # time-based reveal (below) does that.
        req = self._three_tier_setup()
        _, assignments = self.run_pipeline(req)
        LeadDistributionService.reject_assignment(assignments[0])

        lead = assignments[0].lead
        self.assertEqual(
            LeadAssignment.objects.filter(lead=lead, assignment_stage=2).count(), 0
        )

    def test_online_tier_reveal_is_time_based_not_resolution_gated(self):
        # The next tier is revealed on a fixed clock EVEN IF stage 1 is
        # still untouched (ASSIGNED, neither unlocked nor rejected) -
        # online is shared/pooled, not exclusive.
        req = self._three_tier_setup()
        _, assignments = self.run_pipeline(req)
        lead = assignments[0].lead

        revealed = LeadDistributionService.reveal_next_online_stage(lead, force=True)
        self.assertEqual(len(revealed), 1)
        self.assertEqual(revealed[0].teacher_id, self.pro.teacher_id)
        # Stage 1's assignment is untouched - still open, not rejected.
        assignments[0].refresh_from_db()
        self.assertEqual(assignments[0].status, AssignmentStatus.ASSIGNED)

        revealed_again = LeadDistributionService.reveal_next_online_stage(
            lead, force=True
        )
        self.assertEqual(len(revealed_again), 1)
        self.assertEqual(revealed_again[0].teacher_id, self.free.teacher_id)

        # Nothing left to reveal - a further call is a clean no-op.
        self.assertEqual(
            LeadDistributionService.reveal_next_online_stage(lead, force=True), []
        )

    def test_shared_unlock_and_counter_across_tiers(self):
        # Online is shared/pooled: Elite unlocking must not stop Free from
        # later unlocking the SAME lead too, and both should see an
        # accurate "N teachers unlocked" count. NOTE: the "canonical" lead
        # distribute_lead() is anchored to is whichever candidate ranks
        # top by MATCH SCORE (rating/experience/etc.), not necessarily the
        # top-TIER teacher - so this test deliberately looks up each
        # teacher's OWN Lead row rather than assuming assignments[0].lead
        # belongs to any particular one of them.
        req = self._three_tier_setup()
        _, assignments = self.run_pipeline(req)
        lead = assignments[0].lead
        LeadDistributionService.reveal_next_online_stage(lead, force=True)
        LeadDistributionService.reveal_next_online_stage(lead, force=True)

        elite_lead = Lead.objects.get(teacher_profile=self.elite, student_requirement=req)
        login(self.client, self.elite.teacher.user)
        r1 = self.client.post(
            "/api/v1/leads/unlock/", {"lead_id": str(elite_lead.id)}, format="json"
        )
        self.assertEqual(r1.status_code, 200, r1.content)

        elite_assignment = LeadAssignment.objects.get(
            lead=lead, teacher=self.elite.teacher
        )
        self.assertEqual(elite_assignment.status, AssignmentStatus.ACCEPTED)

        free_lead = Lead.objects.get(
            teacher_profile=self.free, student_requirement=req
        )
        # Switch the client to Free - the single-active-session rule 409s
        # a login attempt while Elite's cookie is still presented.
        self.client.post("/api/v1/auth/logout/", {}, format="json")
        login(self.client, self.free.teacher.user)
        r2 = self.client.post(
            "/api/v1/leads/unlock/", {"lead_id": str(free_lead.id)}, format="json"
        )
        self.assertEqual(r2.status_code, 200, r2.content)

        # Free's own assignment is untouched by Elite's unlock (no cancel).
        free_assignment = LeadAssignment.objects.get(
            lead=lead, teacher=self.free.teacher
        )
        self.assertEqual(free_assignment.status, AssignmentStatus.ACCEPTED)

        detail = self.client.get(f"/api/v1/leads/{free_lead.id}/")
        self.assertEqual(detail.json()["data"]["unlocked_count"], 2)

        list_resp = self.client.get("/api/v1/leads/")
        row = next(r for r in list_resp.json()["data"] if r["id"] == str(free_lead.id))
        self.assertEqual(row["unlocked_count"], 2)

    def test_online_tier_reveal_respects_the_configured_window_without_force(self):
        req = self._three_tier_setup()
        _, assignments = self.run_pipeline(req)
        lead = assignments[0].lead

        # Not due yet (default online_tier_window_hours=8, no time has passed).
        self.assertEqual(
            LeadDistributionService.reveal_next_online_stage(lead), []
        )

        assignments[0].refresh_from_db()
        stage1_assigned_at = assignments[0].assigned_at
        LeadAssignment.objects.filter(lead=lead, assignment_stage=1).update(
            assigned_at=stage1_assigned_at - timedelta(hours=9)
        )
        revealed = LeadDistributionService.reveal_next_online_stage(lead)
        self.assertEqual(len(revealed), 1)
        self.assertEqual(revealed[0].teacher_id, self.pro.teacher_id)

    def test_acceptance_cancels_all_other_open_offers(self):
        # Two elite teachers so stage 1 has two simultaneous offers.
        self.make_teacher("Anita", plan=self.elite_plan, rating="4.9")
        self.make_teacher("Amit", plan=self.elite_plan, rating="4.1")
        _, assignments = self.run_pipeline(self.make_requirement())
        self.assertEqual(len(assignments), 2)

        LeadDistributionService.accept_assignment(assignments[0])
        other = LeadAssignment.objects.get(id=assignments[1].id)
        self.assertEqual(other.status, AssignmentStatus.CANCELLED)

    def test_soft_lead_ranking_favours_time_over_premium(self):
        # Free teacher with a real overlap must out-rank an Elite teacher with none.
        self.make_teacher(
            "Chandan", plan=None, availability=((1, time(18, 0), time(20, 0), IST),)
        )
        self.make_teacher(
            "Anita",
            plan=self.elite_plan,
            availability=((6, time(9, 0), time(11, 0), IST),),
        )
        leads, _ = self.run_pipeline(self.make_requirement())
        self.assertEqual(leads[0].teacher_profile.teacher.user.first_name, "Chandan")

    def test_no_duplicate_assignment_for_same_lead_and_teacher(self):
        req = self._three_tier_setup()
        leads, _ = self.run_pipeline(req)
        # Re-running distribution must not create a second offer for Anita.
        LeadDistributionService.distribute_lead(leads[0])
        dupes = LeadAssignment.objects.filter(
            lead=leads[0], teacher=self.elite.teacher
        ).count()
        self.assertEqual(dupes, 1)

    def test_repeated_generation_is_idempotent(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        req = self.make_requirement()
        self.run_pipeline(req)
        second_leads = generate_leads_for_requirement(req)
        self.assertEqual(second_leads, [])
        self.assertEqual(Lead.objects.filter(student_requirement=req).count(), 1)


# ======================================================================
# EMPTY / INVALID INPUT
# ======================================================================
class EmptyAndInvalidInputTests(PipelineFixtureMixin, APITestCase):

    def test_no_teachers_at_all_is_a_clean_empty_result(self):
        req = self.make_requirement()
        leads, assignments = self.run_pipeline(req)
        self.assertEqual((leads, assignments), ([], []))

    def test_unknown_subject_text_is_auto_created_not_rejected(self):
        # Subject text that matches nothing existing (exact/alias/fuzzy) is
        # no longer rejected - it's added to the taxonomy and the
        # requirement proceeds, same as the "Something else" escape on the
        # sign-up/Discover pickers. See StudentRequirementWriteSerializer
        # .validate_subject.
        from apps.subjects.models import Subject

        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        resp = self.client.post(
            "/api/v1/student-requirements/",
            {
                "subject": "Astrophysics of Kryptonian Botany",
                "preferred_languages": ["English"],
                "teaching_mode": "online",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 202)
        self.assertTrue(
            Subject.objects.filter(
                name="Astrophysics of Kryptonian Botany", is_active=True
            ).exists()
        )

    def test_bad_schedule_preference_is_rejected_with_400_not_500(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        resp = self.client.post(
            "/api/v1/student-requirements/",
            {
                "subject": "Mathematics",
                "teaching_mode": "online",
                "schedule_preferences": [
                    {
                        "day_of_week": 1,
                        "start_time": "20:00",
                        "end_time": "18:00",
                        "timezone": IST,
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(StudentRequirement.objects.filter(student=student).exists())


# ======================================================================
# SECURITY
# ======================================================================
class LeadSecurityTests(PipelineFixtureMixin, APITestCase):

    def test_student_cannot_list_teacher_leads(self):
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        resp = self.client.get("/api/v1/leads/")
        self.assertEqual(resp.status_code, 403)

    def test_student_cannot_view_lead_assignments(self):
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        resp = self.client.get("/api/v1/matching/assignments/")
        self.assertEqual(resp.status_code, 403)

    def test_teacher_only_sees_their_own_leads(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        other = self.make_teacher(
            "Bibek", subjects=[self.physics]
        )  # no lead for this req
        req = self.make_requirement()
        self.run_pipeline(req)

        login(self.client, other.teacher.user)
        resp = self.client.get("/api/v1/leads/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["data"]), 0)


class TeacherIsolationSecurityTests(PipelineFixtureMixin, APITestCase):
    """
    Teacher A must never be able to read or act on Teacher B's data, nor bypass
    the lead-unlock / subscription-payment rules. (2026-08-31 security audit -
    all currently PASS; these lock the guarantees in.)
    """

    def setUp(self):
        # A and B both match the same requirement -> each gets their own Lead.
        # A is Elite so A also gets the tiered LeadAssignment.
        self.a = self.make_teacher("Aisha", plan=self.elite_plan, tokens=0)
        self.b = self.make_teacher("Bhavesh", plan=self.elite_plan, tokens=0)
        self.req = self.make_requirement()
        self.leads, self.assignments = self.run_pipeline(self.req)
        self.a_lead = Lead.objects.get(
            teacher_profile=self.a, student_requirement=self.req
        )
        self.b_lead = Lead.objects.get(
            teacher_profile=self.b, student_requirement=self.req
        )

    def _as(self, profile):
        login(self.client, profile.teacher.user)

    # ---- cross-teacher READ ----------------------------------------------
    def test_teacher_cannot_read_another_teachers_lead_by_id(self):
        self._as(self.b)
        self.assertEqual(
            self.client.get(f"/api/v1/leads/{self.a_lead.id}/").status_code, 404
        )
        self.assertEqual(
            self.client.get(f"/api/v1/leads/{self.a_lead.id}/matches/").status_code, 404
        )

    def test_teacher_cannot_use_teacher_discovery_endpoints(self):
        self._as(self.b)
        self.assertEqual(self.client.get("/api/v1/teachers/").status_code, 403)
        self.assertEqual(
            self.client.get(f"/api/v1/teachers/{self.a.teacher_id}/").status_code, 403
        )
        self.assertEqual(self.client.get("/api/v1/search/teachers/").status_code, 403)

    # ---- cross-teacher WRITE / actions ---------------------------------
    def test_teacher_cannot_unlock_another_teachers_lead(self):
        self._as(self.b)
        resp = self.client.post(
            "/api/v1/leads/unlock/", {"lead_id": str(self.a_lead.id)}, format="json"
        )
        self.assertEqual(resp.status_code, 404)
        self.a_lead.refresh_from_db()
        self.assertFalse(self.a_lead.contact_unlocked)

    def test_teacher_cannot_accept_or_reject_another_teachers_assignment(self):
        asg = LeadAssignment.objects.filter(lead__student_requirement=self.req).first()
        self.assertIsNotNone(asg)
        victim, attacker = (
            (self.a, self.b)
            if asg.teacher_id == self.a.teacher_id
            else (self.b, self.a)
        )
        self._as(attacker)
        before = asg.status
        self.assertEqual(
            self.client.post(
                f"/api/v1/matching/assignments/{asg.id}/accept/", {}, format="json"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/matching/assignments/{asg.id}/reject/", {}, format="json"
            ).status_code,
            404,
        )
        asg.refresh_from_db()
        self.assertEqual(asg.status, before)

    def test_teacher_cannot_touch_another_teachers_availability_slot(self):
        slot = self.a.weekly_availability.first()
        self._as(self.b)
        self.assertEqual(
            self.client.delete(
                f"/api/v1/teachers/profile/weekly-availability/{slot.id}/"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/teachers/profile/weekly-availability/{slot.id}/",
                {"is_active": False},
                format="json",
            ).status_code,
            404,
        )
        slot.refresh_from_db()
        self.assertTrue(slot.is_active)

    # ---- privilege escalation on own profile ---------------------------
    def test_teacher_cannot_self_verify_or_self_rate(self):
        self._as(self.b)
        self.b.verification_status = VerificationStatus.PENDING
        self.b.save(update_fields=["verification_status"])
        self.client.post(
            "/api/v1/teachers/profile/",
            {"verification_status": "verified", "rating": "5.00"},
            format="json",
        )
        self.b.refresh_from_db()
        self.assertEqual(self.b.verification_status, VerificationStatus.PENDING)
        self.assertNotEqual(str(self.b.rating), "5.00")

    # ---- unlock-rule bypass ------------------------------------------------
    def _teacher_with_full_quota_plus_one(self, *, plan=None, name="Farida"):
        """A teacher (empty wallet) with exactly (their plan's allowance + 1)
        of their own locked leads - enough to exhaust whatever the plan's
        allowance is currently configured as, then test the boundary right
        after it. Reads the allowance from the plan itself rather than
        hardcoding it, so this doesn't silently go stale the next time a
        plan's allowance changes.

        plan=None means no subscription row at all -> effective Free plan."""
        from apps.subscriptions.models import SubscriptionPlan
        from apps.wallet.services import WalletService

        effective = plan or SubscriptionPlan.objects.get(name="Free")
        quota = effective.free_leads
        # Subject scoped to physics, not this class's default math: self.a/
        # self.b (setUp fixtures) are Elite and also teach math, so they'd
        # always out-rank this teacher's own tier and permanently hold
        # stage 1 - t would generate a soft Lead but never actually be
        # offered it. Keeping this teacher the sole eligible candidate is
        # what lets distribute_lead() hand them stage 1 immediately below.
        t = self.make_teacher(name, subjects=[self.physics], plan=plan)
        WalletService.get_or_create_wallet(t.teacher)  # empty wallet
        for _ in range(quota + 1):
            r = self.make_requirement(
                student=make_user(role=UserRole.STUDENT), subject=self.physics
            )
            for lead in generate_leads_for_requirement(r):
                # Unlocking is gated on actually holding a live
                # LeadAssignment (leads_visible_to) - a real Lead is
                # never unlockable without going through distribution
                # first, so this helper must mirror that instead of
                # leaving these as bare, never-offered soft leads.
                LeadDistributionService.distribute_lead(lead)
        leads = list(Lead.objects.filter(teacher_profile=t).order_by("created_at"))
        return t, leads, quota

    def test_unlock_is_idempotent_and_never_double_charges(self):
        from apps.wallet.services import WalletService

        # Professional, because purchased unlocks are only spendable on a
        # paid plan - a Free teacher is refused however large their balance.
        t, leads, quota = self._teacher_with_full_quota_plus_one(plan=self.pro_plan)
        self._as(t)
        # Spend the whole plan allowance first, then top up so the next lead
        # comes out of the purchased balance.
        for lead in leads[:quota]:
            self.assertEqual(
                self.client.post(
                    "/api/v1/leads/unlock/", {"lead_id": str(lead.id)}, format="json"
                ).status_code,
                200,
            )
        WalletService.credit(teacher=t.teacher, amount=500, description="seed")
        r_paid = self.client.post(
            "/api/v1/leads/unlock/",
            {"lead_id": str(leads[quota].id)},
            format="json",
        )
        self.assertEqual(r_paid.status_code, 200, r_paid.content)
        self.assertFalse(r_paid.json()["data"]["is_free_unlock"])
        # Every lead is worth exactly 1 unlock while the token system is off.
        self.assertEqual(r_paid.json()["data"]["tokens_deducted"], 1)
        bal_after_paid = WalletService.get_balance(t.teacher)
        self.assertEqual(bal_after_paid, 499)

        r_again = self.client.post(
            "/api/v1/leads/unlock/",
            {"lead_id": str(leads[quota].id)},
            format="json",
        )
        self.assertEqual(r_again.status_code, 400)  # already unlocked
        self.assertEqual(
            WalletService.get_balance(t.teacher), bal_after_paid
        )  # NOT charged twice

    def test_unlock_with_no_allowance_and_no_balance_is_a_clean_reject(self):
        t, leads, quota = self._teacher_with_full_quota_plus_one()
        self._as(t)
        # leads[0:quota] consume the whole plan allowance...
        for lead in leads[:quota]:
            self.assertEqual(
                self.client.post(
                    "/api/v1/leads/unlock/", {"lead_id": str(lead.id)}, format="json"
                ).status_code,
                200,
            )
        # ...the next lead has no allowance left and no balance -> clean 400, not 500.
        resp = self.client.post(
            "/api/v1/leads/unlock/",
            {"lead_id": str(leads[quota].id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["error"]["code"], "UNLOCK_ALLOWANCE_EXHAUSTED")
        # The message must tell the teacher the way out, not just refuse.
        self.assertIn("resets", resp.json()["error"]["message"])
        leads[quota].refresh_from_db()
        self.assertFalse(leads[quota].contact_unlocked)

    def test_free_teacher_can_spend_a_purchased_balance(self):
        """
        Extra unlocks are sold to every plan, so a Free teacher who has bought
        capacity can spend it once their allowance runs out. What Free does
        not buy is priority - that stays with the subscription tier.
        """
        from apps.wallet.services import WalletService

        t, leads, quota = self._teacher_with_full_quota_plus_one(name="Topped")
        self._as(t)
        for lead in leads[:quota]:
            self.client.post(
                "/api/v1/leads/unlock/", {"lead_id": str(lead.id)}, format="json"
            )
        WalletService.get_or_create_wallet(t.teacher)
        WalletService.credit(teacher=t.teacher, amount=5, description="bought a pack")

        resp = self.client.post(
            "/api/v1/leads/unlock/",
            {"lead_id": str(leads[quota].id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.json()["data"]["is_free_unlock"])
        self.assertEqual(WalletService.get_balance(t.teacher), 4)

    def test_unlock_nonexistent_lead_is_404_not_500(self):
        self._as(self.b)
        import uuid as _uuid

        resp = self.client.post(
            "/api/v1/leads/unlock/", {"lead_id": str(_uuid.uuid4())}, format="json"
        )
        self.assertEqual(resp.status_code, 404)

    # ---- payment ownership ----------------------------------------------
    def test_teacher_cannot_activate_a_plan_with_another_teachers_payment(self):
        from apps.payments.models import Payment, PaymentStatus, PaymentType

        b_payment = Payment.objects.create(
            teacher=self.b.teacher,
            payment_type=PaymentType.SUBSCRIPTION,
            subscription_plan=self.elite_plan,
            razorpay_order_id="order_isolation_test",
            amount=self.elite_plan.monthly_price,
            status=PaymentStatus.SUCCESS,
        )
        self._as(self.a)
        resp = self.client.post(
            "/api/v1/subscriptions/activate/",
            {"plan_id": str(self.elite_plan.id), "payment_id": str(b_payment.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


# ======================================================================
# MANDATORY END-TO-END SCENARIO (real API flow, DB + business assertions)
# ======================================================================
class MandatoryEndToEndTest(PipelineFixtureMixin, APITestCase):

    def test_full_student_journey(self):
        # --- eligible teachers across three tiers -------------------------
        elite = self.make_teacher(
            "Anita", rating="4.30", experience=12, plan=self.elite_plan
        )
        pro = self.make_teacher(
            "Bibek", rating="4.70", experience=6, plan=self.pro_plan
        )
        free = self.make_teacher("Chandan", rating="4.95", experience=9, plan=None)
        # --- ineligible teachers ---------------------------------------
        self.make_teacher("Deepa", subjects=[self.physics])  # subject
        self.make_teacher("Esha", languages=[self.hindi])  # language
        self.make_teacher(
            "Farid", availability=((6, time(9, 0), time(11, 0), IST),)
        )  # time
        self.make_teacher("Gita", verified=False)  # unverified

        student = make_user(role=UserRole.STUDENT, email="rahul@student.test")
        self.assertEqual(login(self.client, student).status_code, 200)

        resp = self.post_requirement(
            {
                "subject": "Mathematics",
                "preferred_languages": ["English"],
                "teaching_mode": "online",
                "class_duration_minutes": 60,
                "student_class": "Class 10",
                "schedule_preferences": [
                    {
                        "day_of_week": 1,
                        "start_time": "18:00",
                        "end_time": "19:30",
                        "timezone": IST,
                        "flexibility": "flexible",
                    },
                ],
            },
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        req = StudentRequirement.objects.get(student=student)

        # matching -> soft leads for every eligible + time-mismatched teacher
        lead_teacher_names = sorted(
            lead.teacher_profile.teacher.user.first_name
            for lead in Lead.objects.filter(student_requirement=req)
        )
        self.assertEqual(lead_teacher_names, ["Anita", "Bibek", "Chandan", "Farid"])

        # ranking -> best soft match first (all three eligible beat Farid)
        ordered = list(
            Lead.objects.filter(student_requirement=req)
            .select_related("match_score")
            .order_by("-match_score__match_score")
        )
        self.assertEqual(ordered[-1].teacher_profile.teacher.user.first_name, "Farid")

        # distribution -> exactly one stage-1 offer, to the Elite teacher
        assignments = LeadAssignment.objects.filter(lead__student_requirement=req)
        self.assertEqual(assignments.count(), 1)
        offer = assignments.get()
        self.assertEqual(offer.teacher_id, elite.teacher_id)
        self.assertEqual(offer.status, AssignmentStatus.ASSIGNED)

        # ineligible teachers received neither an assignment...
        for profile in (pro, free):
            self.assertFalse(assignments.filter(teacher=profile.teacher).exists())
        # ...nor did the hard-excluded ones ever get a soft lead
        self.assertFalse(
            Lead.objects.filter(
                student_requirement=req,
                teacher_profile__teacher__user__first_name__in=[
                    "Deepa",
                    "Esha",
                    "Gita",
                ],
            ).exists()
        )

        # no duplicates
        self.assertEqual(
            assignments.values("lead", "teacher").distinct().count(),
            assignments.count(),
        )

        # student sees the result: requirement now MATCHED
        detail = self.client.get(f"/api/v1/student-requirements/{req.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["status"], RequirementStatus.MATCHED)

        # teacher side: the elite teacher sees exactly one assignment.
        # Fresh client - the single-active-account rule 409s a second login
        # while the student's cookies are still attached.
        teacher_client = self.client_class()
        self.assertEqual(login(teacher_client, elite.teacher.user).status_code, 200)
        t_resp = teacher_client.get("/api/v1/matching/assignments/")
        self.assertEqual(t_resp.status_code, 200)
        self.assertEqual(len(t_resp.json()["data"]), 1)


# ======================================================================
# CONCURRENCY
# ======================================================================
class ConcurrencyTests(PipelineFixtureMixin, APITestCase):

    def test_double_accept_is_rejected(self):
        self.make_teacher("Anita", plan=self.elite_plan, rating="4.9")
        self.make_teacher("Amit", plan=self.elite_plan, rating="4.1")
        _, assignments = self.run_pipeline(self.make_requirement())
        LeadDistributionService.accept_assignment(assignments[0])
        from apps.core.exceptions.custom_exceptions import ValidationException

        with self.assertRaises(ValidationException):
            LeadDistributionService.accept_assignment(assignments[1])


# ======================================================================
# H.2 - ASYNC (CELERY) LEAD DISTRIBUTION ENGINE
# ======================================================================
from unittest import mock  # noqa: E402

from django.db import connection  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

from apps.lead_engine.tasks import (  # noqa: E402
    process_requirement_leads,
    requeue_stuck_requirement_distributions,
)
from apps.student_requirement.models import LeadDistributionStatus  # noqa: E402


class AsyncDistributionTests(PipelineFixtureMixin, APITestCase):

    def _post(self, student, prefs=True):
        login(self.client, student)
        payload = {
            "subject": "Mathematics",
            "preferred_languages": ["English"],
            "teaching_mode": "online",
            "class_duration_minutes": 60,
        }
        if prefs:
            payload["schedule_preferences"] = [
                {
                    "day_of_week": 1,
                    "start_time": "18:00",
                    "end_time": "19:00",
                    "timezone": IST,
                }
            ]
        return self.post_requirement(payload)

    def test_post_returns_202_and_queues_a_task(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        with mock.patch(
            "apps.student_requirement.views.process_requirement_leads.delay"
        ) as delayed:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(
                    "/api/v1/student-requirements/",
                    {
                        "subject": "Mathematics",
                        "preferred_languages": ["English"],
                        "teaching_mode": "online",
                        "schedule_preferences": [
                            {
                                "day_of_week": 1,
                                "start_time": "18:00",
                                "end_time": "19:00",
                                "timezone": IST,
                            }
                        ],
                    },
                    format="json",
                )
        self.assertEqual(resp.status_code, 202)
        delayed.assert_called_once()
        req = StudentRequirement.objects.get(student=student)
        # delay() was mocked, so the task never ran - status stays QUEUED.
        self.assertEqual(str(delayed.call_args[0][0]), str(req.id))
        self.assertEqual(req.lead_distribution_status, LeadDistributionStatus.QUEUED)

    def test_task_not_queued_when_requirement_validation_fails(self):
        # Unknown subject text is no longer a validation failure (it's
        # auto-created - see test_unknown_subject_text_is_auto_created_not_
        # rejected), so this needs a payload that's still genuinely invalid:
        # subject is required and missing here.
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        with mock.patch(
            "apps.student_requirement.views.process_requirement_leads.delay"
        ) as delayed:
            resp = self.client.post(
                "/api/v1/student-requirements/",
                {"teaching_mode": "online"},
                format="json",
            )
        self.assertEqual(resp.status_code, 400)
        delayed.assert_not_called()

    def test_task_completes_and_sets_status(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        self._post(student)
        req = StudentRequirement.objects.get(student=student)
        self.assertEqual(req.lead_distribution_status, LeadDistributionStatus.COMPLETED)
        self.assertEqual(Lead.objects.filter(student_requirement=req).count(), 1)
        self.assertEqual(
            LeadAssignment.objects.filter(lead__student_requirement=req).count(), 1
        )

    def test_running_the_task_twice_is_idempotent(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        self.make_teacher("Bibek", plan=self.pro_plan)
        student = make_user(role=UserRole.STUDENT)
        self._post(student)
        req = StudentRequirement.objects.get(student=student)

        leads_before = Lead.objects.filter(student_requirement=req).count()
        asg_before = LeadAssignment.objects.filter(
            lead__student_requirement=req
        ).count()

        # Re-run the exact same task body (redelivery / manual retry).
        result = process_requirement_leads.apply(args=[str(req.id)]).get()

        self.assertEqual(
            Lead.objects.filter(student_requirement=req).count(), leads_before
        )
        self.assertEqual(
            LeadAssignment.objects.filter(lead__student_requirement=req).count(),
            asg_before,
        )
        self.assertEqual(result["status"], "already_completed")

    def test_distribution_no_ops_if_another_worker_already_distributed(self):
        # Simulate a redelivery race: worker 1 has already created a stage-1
        # assignment; worker 2 calls distribute_lead for the same requirement.
        a = self.make_teacher("Anita", plan=self.elite_plan)
        self.make_teacher("Bibek", plan=self.pro_plan)
        req = self.make_requirement(student=make_user(role=UserRole.STUDENT))
        generate_leads_for_requirement(req)
        canonical = (
            Lead.objects.filter(student_requirement=req)
            .order_by("-match_score__match_score")
            .first()
        )
        now = timezone.now()
        LeadAssignment.objects.create(
            lead=canonical,
            teacher=a.teacher,
            subscription_tier="Elite",
            assignment_stage=1,
            assigned_at=now,
            expires_at=now + timedelta(hours=24),
            status=AssignmentStatus.ASSIGNED,
        )
        self.assertEqual(LeadDistributionService.distribute_lead(canonical), [])
        self.assertEqual(
            LeadAssignment.objects.filter(lead__student_requirement=req).count(), 1
        )

    def test_task_on_missing_requirement_is_a_noop(self):
        result = process_requirement_leads.apply(
            args=["00000000-0000-0000-0000-000000000000"]
        ).get()
        self.assertEqual(result["status"], "skipped_not_found")

    def test_enqueue_failure_leaves_requirement_queued_not_500(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        with mock.patch(
            "apps.student_requirement.views.process_requirement_leads.delay",
            side_effect=RuntimeError("broker down"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(
                    "/api/v1/student-requirements/",
                    {
                        "subject": "Mathematics",
                        "preferred_languages": ["English"],
                        "teaching_mode": "online",
                        "schedule_preferences": [
                            {
                                "day_of_week": 1,
                                "start_time": "18:00",
                                "end_time": "19:00",
                                "timezone": IST,
                            }
                        ],
                    },
                    format="json",
                )
        self.assertEqual(resp.status_code, 202)
        req = StudentRequirement.objects.get(student=student)
        self.assertEqual(req.lead_distribution_status, LeadDistributionStatus.QUEUED)

    def test_sweeper_requeues_stuck_requirements(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        req = self.make_requirement(student=student)
        StudentRequirement.objects.filter(pk=req.pk).update(
            lead_distribution_status=LeadDistributionStatus.QUEUED
        )
        # Make it look stale.
        old = timezone.now() - timedelta(hours=1)
        StudentRequirement.objects.filter(pk=req.pk).update(updated_at=old)

        result = requeue_stuck_requirement_distributions.apply(args=[15]).get()
        self.assertEqual(result["requeued"], 1)
        req.refresh_from_db()
        # eager task ran -> now completed
        self.assertEqual(req.lead_distribution_status, LeadDistributionStatus.COMPLETED)

    def test_business_error_marks_failed_without_endless_retry(self):
        self.make_teacher("Anita", plan=self.elite_plan)
        student = make_user(role=UserRole.STUDENT)
        req = self.make_requirement(student=student)
        with mock.patch(
            "apps.lead_engine.services.generate_leads_for_requirement",
            side_effect=RuntimeError("boom"),
        ):
            result = process_requirement_leads.apply(args=[str(req.id)]).get()
        self.assertEqual(result["status"], "failed")
        req.refresh_from_db()
        self.assertEqual(req.lead_distribution_status, LeadDistributionStatus.FAILED)

    def test_transient_db_errors_are_configured_for_retry(self):
        from django.db import InterfaceError, OperationalError

        from apps.lead_engine.tasks import TRANSIENT_DB_ERRORS

        self.assertEqual(set(TRANSIENT_DB_ERRORS), {OperationalError, InterfaceError})

    def _distribute_query_count(self, n_teachers):
        req = self.make_requirement(student=make_user(role=UserRole.STUDENT))
        for i in range(n_teachers):
            plan = (
                self.elite_plan
                if i % 3 == 0
                else (self.pro_plan if i % 3 == 1 else None)
            )
            self.make_teacher(f"T{req.pk.hex[:4]}{i}", plan=plan, rating=f"4.{i % 10}")
        generate_leads_for_requirement(req)
        canonical = (
            Lead.objects.filter(student_requirement=req)
            .order_by("-match_score__match_score")
            .first()
        )
        with CaptureQueriesContext(connection) as ctx:
            LeadDistributionService.distribute_lead(canonical)
        return len(ctx.captured_queries)

    def test_distribution_query_count_is_sublinear_in_teacher_count(self):
        # The old code did get_effective_plan() (2 queries) per teacher in
        # both _group_by_tier and the assignment loop. Tripling the teacher
        # count must NOT triple the query count.
        q_small = self._distribute_query_count(3)
        q_large = self._distribute_query_count(9)
        # +6 teachers must add far fewer than 6*2 plan queries.
        self.assertLess(q_large - q_small, 12, f"{q_small} -> {q_large} queries")

    def test_generation_query_count_is_flat_in_teacher_count(self):
        # Regression (2026-08-31 audit): generate_leads_for_requirement did
        # get_or_create + LeadMatchScore.create per matching teacher, each in
        # its own transaction.atomic() - ~5-7 queries PER teacher. A popular
        # subject with 60 verified teachers ran ~500 queries synchronously
        # (POST latency grew from ~90ms to ~400ms). Now bulk_create'd: the
        # query count must be essentially FLAT as the candidate set grows.
        def count(n):
            req = self.make_requirement(student=make_user(role=UserRole.STUDENT))
            for i in range(n):
                self.make_teacher(
                    f"G{req.pk.hex[:4]}{i}", plan=self.pro_plan if i % 2 else None
                )
            with CaptureQueriesContext(connection) as ctx:
                generate_leads_for_requirement(req)
            return len(ctx.captured_queries)

        small, large = count(3), count(15)
        # +12 matching teachers must add only a tiny constant (prefetch
        # cache warmups), nowhere near 12 * per-row inserts.
        self.assertLessEqual(
            large - small, 6, f"{small} -> {large} queries for +12 teachers"
        )

    def test_matching_business_rules_still_hold_through_the_task(self):
        elite = self.make_teacher("Anita", plan=self.elite_plan)
        self.make_teacher("Wrong", subjects=[self.physics])
        self.make_teacher("Late", availability=((6, time(9, 0), time(11, 0), IST),))
        student = make_user(role=UserRole.STUDENT)
        self._post(student)
        req = StudentRequirement.objects.get(student=student)

        offered = LeadAssignment.objects.filter(lead__student_requirement=req)
        self.assertEqual(offered.count(), 1)
        self.assertEqual(offered.first().teacher_id, elite.teacher_id)
        # wrong-subject teacher never even got a soft lead
        self.assertFalse(
            Lead.objects.filter(
                student_requirement=req,
                teacher_profile__teacher__user__first_name="Wrong",
            ).exists()
        )
