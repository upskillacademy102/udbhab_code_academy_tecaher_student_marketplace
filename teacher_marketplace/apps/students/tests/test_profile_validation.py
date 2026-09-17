"""
Data-quality hardening for the student profile endpoint (`/api/v1/students/me/`).

The optional text fields (city / state / country / grade_or_year /
preferred_subjects / bio) used to accept anything up to their max_length -
digits-only cities, injection strings, 500-char "subjects", blank strings, etc.
They are now validated at the model layer (propagated to the serializer) plus a
DB CHECK constraint that forbids whitespace-only values.

Run: python manage.py test apps.students.tests.test_profile_validation \
     --settings=config.settings.test
"""

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.students.models import Student

ME = "/api/v1/students/me/"


class StudentProfileValidationTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.STUDENT)
        login(self.client, self.user)
        self.client.post(ME, {"bio": "hi"}, format="json")  # ensure profile exists

    def _patch(self, **fields):
        return self.client.patch(ME, fields, format="json")

    # ---- valid input still works --------------------------------------
    def test_realistic_profile_saves(self):
        resp = self._patch(
            city="Kolkata",
            state="West Bengal",
            country="India",
            grade_or_year="Grade 10",
            education_level="high_school",
            preferred_subjects="Maths, Physics, Chemistry",
            bio="Looking for JEE preparation help.",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_place_names_with_legitimate_punctuation_pass(self):
        for city in (
            "St. John's",
            "Sector-21, Gurugram",
            "Al Ain",
            "Stratford-upon-Avon",
        ):
            self.assertEqual(self._patch(city=city).status_code, 200, city)

    def test_whitespace_is_trimmed(self):
        self._patch(city="  Pune  ", grade_or_year="  2nd Year B.Sc  ")
        s = Student.objects.get(user=self.user)
        self.assertEqual(s.city, "Pune")
        self.assertEqual(s.grade_or_year, "2nd Year B.Sc")

    # ---- junk is rejected -------------------------------------------
    def test_junk_place_names_are_rejected(self):
        for bad in ("12345", "!!!@@@", "asdf<script>", "   .  "):
            self.assertEqual(self._patch(city=bad).status_code, 400, bad)

    def test_control_characters_and_angle_brackets_rejected(self):
        self.assertEqual(self._patch(grade_or_year="line1\nline2\x00").status_code, 400)
        self.assertEqual(
            self._patch(preferred_subjects="Maths<>Physics").status_code, 400
        )

    def test_length_caps_enforced(self):
        self.assertEqual(self._patch(country="x" * 150).status_code, 400)
        self.assertEqual(self._patch(bio="y" * 1001).status_code, 400)

    def test_invalid_education_level_choice_rejected(self):
        self.assertEqual(self._patch(education_level="phd_wizardry").status_code, 400)

    # ---- preferred_subjects normalisation -------------------------
    def test_preferred_subjects_dedupes_and_caps(self):
        r = self._patch(preferred_subjects="Maths, maths, MATHS, Physics")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            Student.objects.get(user=self.user).preferred_subjects, "Maths, Physics"
        )

    # ---- detailed address (address_line1/2 + pincode) ------------
    def test_address_fields_save_and_resolve_pincode(self):
        from unittest.mock import patch as _patch_mock

        from django.contrib.gis.geos import Point

        from apps.matching.models import PincodeLocation

        location = PincodeLocation.objects.create(
            pincode="700001", location=Point(88.3639, 22.5726, srid=4326), city="Kolkata"
        )
        with _patch_mock(
            "apps.matching.services.geocoding_service."
            "PincodeGeocodingService.get_or_geocode",
            return_value=location,
        ):
            resp = self._patch(
                address_line1="12 Park Street",
                address_line2="Near the lake",
                city="Kolkata",
                pincode="700001",
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        s = Student.objects.get(user=self.user)
        self.assertEqual(s.pincode_location, location)

    def test_bad_pincode_format_rejected(self):
        self.assertEqual(self._patch(pincode="ABCDEF").status_code, 400)
        self.assertEqual(self._patch(pincode="12345").status_code, 400)

    def test_geocoding_outage_does_not_block_saving_the_address(self):
        from unittest.mock import patch as _patch_mock

        from apps.matching.services.geocoding_service import GeocodingError

        with _patch_mock(
            "apps.matching.services.geocoding_service."
            "PincodeGeocodingService.get_or_geocode",
            side_effect=GeocodingError(
                detail="Geocoding service is currently unavailable. Please try again shortly."
            ),
        ):
            resp = self._patch(
                address_line1="12 Park Street", city="Kolkata", pincode="700001"
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        s = Student.objects.get(user=self.user)
        self.assertEqual(s.address_line1, "12 Park Street")
        self.assertIsNone(s.pincode_location)

    def test_stale_pincode_location_is_cleared_when_a_changed_pincode_fails_to_geocode(self):
        from unittest.mock import patch as _patch_mock

        from django.contrib.gis.geos import Point

        from apps.matching.models import PincodeLocation
        from apps.matching.services.geocoding_service import GeocodingError

        location_a = PincodeLocation.objects.create(
            pincode="700001", location=Point(88.3639, 22.5726, srid=4326), city="Kolkata"
        )
        with _patch_mock(
            "apps.matching.services.geocoding_service."
            "PincodeGeocodingService.get_or_geocode",
            return_value=location_a,
        ):
            self._patch(address_line1="12 Park Street", city="Kolkata", pincode="700001")
        s = Student.objects.get(user=self.user)
        self.assertEqual(s.pincode_location, location_a)

        with _patch_mock(
            "apps.matching.services.geocoding_service."
            "PincodeGeocodingService.get_or_geocode",
            side_effect=GeocodingError(detail="down"),
        ):
            self._patch(address_line1="45 New Road", city="Howrah", pincode="711101")
        s.refresh_from_db()
        self.assertEqual(s.pincode, "711101")
        self.assertIsNone(s.pincode_location)

    def test_address_is_optional(self):
        # Unlike the teacher side, nothing on Student requires this.
        self.assertEqual(self._patch(bio="just a bio").status_code, 200)

        self.assertEqual(
            self._patch(
                preferred_subjects=", ".join(f"Subj{i}" for i in range(20))
            ).status_code,
            400,
        )
        self.assertEqual(self._patch(preferred_subjects="z" * 70).status_code, 400)

    # ---- blank strings never reach the DB -------------------------
    def test_whitespace_only_optional_field_becomes_null(self):
        self.assertEqual(self._patch(city="   ").status_code, 200)
        self.assertIsNone(Student.objects.get(user=self.user).city)

    def test_db_constraint_blocks_a_blank_string_written_directly(self):
        from django.db import IntegrityError, transaction

        s = Student.objects.get(user=self.user)
        s.city = "   "
        with self.assertRaises(IntegrityError), transaction.atomic():
            s.save(update_fields=["city"])
