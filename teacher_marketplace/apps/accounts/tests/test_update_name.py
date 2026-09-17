"""
`PATCH /api/v1/auth/me/` - lets a signed-in user (student or teacher)
change their own first/last name. This is the one piece of `User` an
account holder may write directly through the "me" endpoint - the rest
of `UserSerializer` stays read-only.

Run: python manage.py test apps.accounts.tests.test_update_name \
     --settings=config.settings.test
"""

from rest_framework.test import APITestCase

from apps.accounts.models import User, UserRole
from apps.accounts.tests.helpers import login, make_user

ME = "/api/v1/auth/me/"


class UpdateNameTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.TEACHER)
        login(self.client, self.user)

    def test_updates_first_and_last_name(self):
        resp = self.client.patch(
            ME, {"first_name": "Bruce", "last_name": "Wayne"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        u = User.objects.get(pk=self.user.pk)
        self.assertEqual(u.first_name, "Bruce")
        self.assertEqual(u.last_name, "Wayne")
        self.assertEqual(resp.data["data"]["user"]["full_name"], "Bruce Wayne")

    def test_partial_update_of_just_one_field(self):
        resp = self.client.patch(ME, {"first_name": "Selina"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        u = User.objects.get(pk=self.user.pk)
        self.assertEqual(u.first_name, "Selina")
        self.assertEqual(u.last_name, "User")  # unchanged

    def test_digits_and_symbols_rejected(self):
        for bad in ("Br7ce", "<script>", "Wayne123", ""):
            resp = self.client.patch(ME, {"first_name": bad}, format="json")
            self.assertEqual(resp.status_code, 400, bad)

    def test_student_can_also_update_their_name(self):
        student = make_user(role=UserRole.STUDENT)
        login(self.client, student)
        resp = self.client.patch(ME, {"first_name": "Diana"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_anonymous_cannot_update(self):
        self.client.logout()
        self.client.credentials()
        resp = self.client.patch(ME, {"first_name": "Nobody"}, format="json")
        self.assertEqual(resp.status_code, 401)
