"""
Data-quality hardening for the admin location endpoints
`/api/v1/location/{countries,states,cities}/`.

Adds: `validate_place_name` on every `name`; `validate_country_code`
(`^[A-Za-z]{2,3}$`) + DB CHECK format on `Country.code`; control-char check on
`State.code` + `""`→NULL; DB not-blank CHECKs on all names + `State.code`.

Run: python manage.py test apps.location.tests.test_location_validation \
     --settings=config.settings.test
"""

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.location.models import City, Country, State


class LocationValidationTests(APITestCase):
    def setUp(self):
        login(self.client, make_user(role=UserRole.ADMIN))
        self.country = Country.objects.create(name="Testland", code="TST")
        self.state = State.objects.create(country=self.country, name="Test State")

    def _post(self, path, expect, **fields):
        r = self.client.post(path, fields, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    # ---- country -------------------------------------------------
    def test_country_valid_and_code_normalised(self):
        r = self._post("/api/v1/location/countries/", 201, name="Freedonia", code="fd")
        self.assertEqual(Country.objects.get(id=r.json()["data"]["id"]).code, "FD")

    def test_country_junk_rejected(self):
        self._post("/api/v1/location/countries/", 400, name="12345", code="XY")
        self._post("/api/v1/location/countries/", 400, name="  ", code="XZ")
        self._post(
            "/api/v1/location/countries/", 400, name="Okland", code="X1"
        )  # digit
        self._post(
            "/api/v1/location/countries/", 400, name="Okland2", code="ABCD"
        )  # too long

    def test_country_code_db_check(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Country.objects.create(name="Badcode", code="!!")

    # ---- state --------------------------------------------------
    def test_state_valid_names_and_blank_code_to_null(self):
        self._post(
            "/api/v1/location/states/",
            201,
            country=str(self.country.id),
            name="St. Mary's Province",
        )
        r = self._post(
            "/api/v1/location/states/",
            201,
            country=str(self.country.id),
            name="Coded Province",
            code="   ",
        )
        self.assertIsNone(State.objects.get(id=r.json()["data"]["id"]).code)

    def test_state_junk_name_rejected(self):
        self._post(
            "/api/v1/location/states/", 400, country=str(self.country.id), name="!!!"
        )

    # ---- city ---------------------------------------------------
    def test_city_valid_and_junk(self):
        self._post(
            "/api/v1/location/cities/",
            201,
            state=str(self.state.id),
            name="Stratford-upon-Avon",
        )
        self._post(
            "/api/v1/location/cities/", 400, state=str(self.state.id), name="99999"
        )
        self._post(
            "/api/v1/location/cities/", 400, state=str(self.state.id), name="bad<>"
        )

    def test_city_name_db_check(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            City.objects.create(state=self.state, name="   ")
