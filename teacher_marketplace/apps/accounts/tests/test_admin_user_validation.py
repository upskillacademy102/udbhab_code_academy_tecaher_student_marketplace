"""
Data-quality hardening for the super-admin user-management endpoints
`POST /api/v1/admin/users/` and `PATCH /api/v1/admin/users/{id}/`.

The `User` model already enforces unique email + unique mobile + name/mobile
format, but the admin create/update serializers are plain `Serializer`s so those
model validators never ran: an admin could create a user with mobile "abc" or
name "John123", and PATCHing a colliding mobile 500'd on `IntegrityError`.

Fix: `validate_name` + `validate_mobile_number` on the serializer fields, name
trimming, and a mobile-uniqueness check on update (excluding the target).

Run: python manage.py test apps.accounts.tests.test_admin_user_validation \
     --settings=config.settings.test
"""

from rest_framework.test import APITestCase

from apps.accounts.models import User, UserRole
from apps.accounts.tests.helpers import login, make_user

CREATE = "/api/v1/admin/users/"


class AdminUserCreateValidationTests(APITestCase):
    def setUp(self):
        login(self.client, make_user(role=UserRole.SUPERADMIN))
        self.base = {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "mobile": "919812345678",
            "role": "teacher",
            "password": "Str0ng!Pass1",
        }

    def _post(self, expect, **over):
        r = self.client.post(CREATE, {**self.base, **over}, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_valid(self):
        self._post(201)

    def test_name_and_mobile_format(self):
        self._post(400, email="a@x.test", mobile="919000000001", first_name="John123")
        self._post(400, email="b@x.test", mobile="919000000002", last_name="  ")
        self._post(400, email="c@x.test", mobile="not-a-number")
        self._post(400, email="d@x.test", mobile="12345")

    def test_name_is_trimmed(self):
        self._post(
            201, email="grace@x.test", mobile="919000000009", first_name="  Grace  "
        )
        self.assertEqual(User.objects.get(email="grace@x.test").first_name, "Grace")

    def test_weak_password_and_bad_role(self):
        self._post(400, email="e@x.test", mobile="919000000003", password="weak")
        self._post(400, email="f@x.test", mobile="919000000004", role="wizard")

    def test_duplicate_email_or_mobile(self):
        self._post(201)
        self._post(
            400, email="ADA@example.com", mobile="919000000005"
        )  # dup email (ci)
        self._post(400, email="ada2@example.com", mobile="919812345678")  # dup mobile


class AdminUserUpdateValidationTests(APITestCase):
    def setUp(self):
        login(self.client, make_user(role=UserRole.SUPERADMIN))
        self.target = make_user(
            role=UserRole.STUDENT, email="t@x.test", mobile="919700000000"
        )
        self.other = make_user(
            role=UserRole.STUDENT, email="o@x.test", mobile="919700000001"
        )
        self.url = f"/api/v1/admin/users/{self.target.id}/"

    def _patch(self, expect, **fields):
        r = self.client.patch(self.url, fields, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r

    def test_name_and_mobile_format(self):
        self._patch(400, first_name="Bad9")
        self._patch(400, mobile="xyz")
        self._patch(200, first_name="  Grace  ")
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "Grace")

    def test_duplicate_mobile_is_400_not_500(self):
        self._patch(400, mobile=self.other.mobile)

    def test_own_mobile_unchanged_is_fine(self):
        self._patch(200, mobile=self.target.mobile)
