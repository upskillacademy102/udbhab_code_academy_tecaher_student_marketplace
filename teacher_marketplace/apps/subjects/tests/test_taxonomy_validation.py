"""
Data-quality hardening for the admin reference-taxonomy endpoints
`/api/v1/subjects/` and `/api/v1/languages/`.

Adds: `validate_taxonomy_name` on subject/language `name`; `validate_language_code`
+ DB CHECK format on language `code`; subject `description` capped at 1000 chars
(`varchar`); control-char check on subject `icon`; `""`/whitespace normalised to
NULL with DB not-blank CHECK constraints.

Run: python manage.py test apps.subjects.tests.test_taxonomy_validation \
     --settings=config.settings.test
"""

from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.languages.models import Language
from apps.subjects.models import Subject


class SubjectValidationTests(APITestCase):
    def setUp(self):
        login(self.client, make_user(role=UserRole.ADMIN))

    def _post(self, expect=201, **fields):
        r = self.client.post("/api/v1/subjects/", fields, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_valid_names(self):
        for n in (
            "Astronomy",
            "C++",
            "Class 9 & 10",
            "Data Science / ML",
            "English (Spoken)",
        ):
            self._post(name=n)

    def test_junk_names_rejected(self):
        for n in ("12345", "!!! @@@", "bad <name>", "ok\x00nope", "   "):
            self._post(400, name=n)

    def test_description_capped_and_normalised(self):
        self._post(400, name="Physics X", description="d" * 1001)
        r = self._post(name="Physics Y", description="   ")
        self.assertIsNone(Subject.objects.get(id=r.json()["data"]["id"]).description)

    def test_db_check_blocks_blank_name(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Subject.objects.create(name="   ", slug="blank-name")


class LanguageValidationTests(APITestCase):
    def setUp(self):
        login(self.client, make_user(role=UserRole.ADMIN))

    def _post(self, expect=201, **fields):
        r = self.client.post("/api/v1/languages/", fields, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_valid(self):
        self._post(name="Elvish", code="elv")
        r = self._post(name="Brazilian Portuguese", code="PT-BR")  # normalised
        self.assertEqual(Language.objects.get(id=r.json()["data"]["id"]).code, "pt-br")

    def test_bad_codes_rejected(self):
        for c in ("!!!", "1", "en glish", "toolongcode", "-x"):
            self._post(400, name=f"Lang {c}", code=c)

    def test_bad_name_rejected(self):
        self._post(400, name="99999", code="nn")

    def test_db_check_enforces_code_format(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Language.objects.create(name="Klingon", code="!!!")
