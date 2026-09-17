"""
Data-quality hardening for the admin matching-engine endpoints
`/api/v1/matching/{config,subject-aliases,language-aliases,pincode-locations}/`.

MatchingConfig: thresholds <= 100, minutes 1..1440, radii 1..5000 (+ initial <=
max), hours 1..720, `subscription_priority_order` = <= 20 unique non-empty
strings - one `matching_config_sane_ranges` DB CHECK.
Aliases: `alias_text` stripped, not blank (+ DB CHECK), no control chars.
Pincode: latitude -90..90, longitude -180..180; `pincode` not blank (+ DB CHECK);
`city`/`state`/`country` -> `validate_place_name`.

Run: python manage.py test apps.matching.tests.test_admin_config_validation \
     --settings=config.settings.test
"""

from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.languages.models import Language
from apps.matching.models import MatchingConfig, PincodeLocation, SubjectAlias
from apps.subjects.models import Subject

GOOD_CFG = {
    "subject_match_threshold": 70,
    "language_match_threshold": 70,
    "time_match_threshold_minutes": 30,
    "initial_location_radius_km": 5,
    "location_radius_increment_km": 5,
    "max_location_radius_km": 50,
    "offline_response_window_hours": 24,
    "online_tier_window_hours": 8,
    "lead_visibility_window_hours": 24,
    "is_active": True,
}


class MatchingConfigValidationTests(APITestCase):
    def setUp(self):
        login(self.client, make_user(role=UserRole.ADMIN))

    def _post(self, expect=201, **override):
        r = self.client.post(
            "/api/v1/matching/config/", {**GOOD_CFG, **override}, format="json"
        )
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_valid(self):
        self._post(subscription_priority_order=["Elite", "Professional", "Free"])

    def test_bounds(self):
        self._post(400, subject_match_threshold=150)
        self._post(400, time_match_threshold_minutes=99999)
        self._post(400, max_location_radius_km=99999)
        self._post(400, initial_location_radius_km=80, max_location_radius_km=50)
        self._post(400, offline_response_window_hours=5000)
        self._post(400, online_tier_window_hours=5000)
        self._post(400, lead_visibility_window_hours=5000)

    def test_priority_order(self):
        self._post(400, subscription_priority_order=["Elite", 123])
        self._post(400, subscription_priority_order=["Elite", "elite"])
        self._post(400, subscription_priority_order=["  "])
        self._post(400, subscription_priority_order=["x"] * 21)

    def test_db_check(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MatchingConfig.objects.create(
                subject_match_threshold=70,
                language_match_threshold=70,
                time_match_threshold_minutes=1,
                initial_location_radius_km=999,
                location_radius_increment_km=3,
                max_location_radius_km=10,  # initial > max
                offline_response_window_hours=24,
                online_tier_window_hours=8,
                lead_visibility_window_hours=24,
            )


class AliasValidationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.subject = Subject.objects.create(name="Physics X")
        cls.language = Language.objects.create(name="Testish", code="tst")

    def setUp(self):
        login(self.client, make_user(role=UserRole.ADMIN))

    def test_subject_alias_hygiene(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/matching/subject-aliases/",
                {"subject": str(self.subject.id), "alias_text": "  phys  "},
                format="json",
            ).status_code,
            201,
        )
        self.assertEqual(SubjectAlias.objects.get().alias_text, "phys")
        for bad in ("   ", "x\x00y"):
            self.assertEqual(
                self.client.post(
                    "/api/v1/matching/subject-aliases/",
                    {"subject": str(self.subject.id), "alias_text": bad},
                    format="json",
                ).status_code,
                400,
                bad,
            )

    def test_db_check_blocks_blank_alias(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SubjectAlias.objects.create(subject=self.subject, alias_text="   ")


class PincodeValidationTests(APITestCase):
    def setUp(self):
        login(self.client, make_user(role=UserRole.ADMIN))

    def _post(self, expect, **fields):
        body = {"pincode": "700001", "latitude": 22.5, "longitude": 88.3, **fields}
        r = self.client.post("/api/v1/matching/pincode-locations/", body, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_valid(self):
        self._post(
            201, pincode="560001", city="Bengaluru", state="Karnataka", country="India"
        )

    def test_coordinate_and_text_bounds(self):
        self._post(400, pincode="111111", latitude=200)
        self._post(400, pincode="222222", longitude=400)
        self._post(400, pincode="   ")
        self._post(400, pincode="333333", city="12345")

    def test_db_check_blocks_blank_pincode(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PincodeLocation.objects.create(
                pincode="  ", location=Point(88.0, 22.0, srid=4326)
            )
