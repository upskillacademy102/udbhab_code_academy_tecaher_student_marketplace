"""
Support-department admin's "Bug Calls" queue - the admin_support:list
queryset narrowed to call-request tickets only, and the self-accept
endpoint (admin_support:accept).

Run: python manage.py test apps.support.tests.test_bug_calls \
     --settings=config.settings.test
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_named_admin, make_user
from apps.support.models import ContactPreference, SupportTicket

OK = status.HTTP_200_OK
FORBIDDEN = status.HTTP_403_FORBIDDEN
BAD_REQUEST = status.HTTP_400_BAD_REQUEST

QUEUE_URL = "/api/v1/admin/support-tickets/"


def _support_client(test):
    admin = make_named_admin(department="Support")
    c = test.client_class()
    login(c, admin)
    return admin, c


def _ticket(contact_preference=ContactPreference.NONE):
    reporter = make_user(role=UserRole.STUDENT)
    return SupportTicket.objects.create(
        reporter=reporter,
        subject="Something's broken",
        description="Details.",
        contact_preference=contact_preference,
    )


class SupportQueueScopingTests(APITestCase):
    def test_support_admin_sees_only_call_request_tickets(self):
        video = _ticket(ContactPreference.VIDEO_CALL)
        phone = _ticket(ContactPreference.PHONE_CALL)
        _ticket(ContactPreference.NONE)  # no call requested - excluded

        _, c = _support_client(self)
        r = c.get(QUEUE_URL, {"status": "all"})
        self.assertEqual(r.status_code, OK, r.content)
        ids = {row["id"] for row in r.data["data"]}
        self.assertEqual(ids, {str(video.id), str(phone.id)})

    def test_other_admin_still_sees_every_ticket(self):
        _ticket(ContactPreference.NONE)
        _ticket(ContactPreference.VIDEO_CALL)

        admin = make_named_admin(department="Verification")
        c = self.client_class()
        login(c, admin)
        r = c.get(QUEUE_URL, {"status": "all"})
        self.assertEqual(r.status_code, OK, r.content)
        self.assertEqual(len(r.data["data"]), 2)

    def test_departmentless_admin_still_sees_every_ticket(self):
        _ticket(ContactPreference.NONE)
        _ticket(ContactPreference.PHONE_CALL)

        c = self.client_class()
        login(c, make_user(role=UserRole.ADMIN))
        r = c.get(QUEUE_URL, {"status": "all"})
        self.assertEqual(r.status_code, OK, r.content)
        self.assertEqual(len(r.data["data"]), 2)


class SupportSelfAcceptTests(APITestCase):
    def test_support_admin_can_accept_a_call_request_ticket(self):
        ticket = _ticket(ContactPreference.VIDEO_CALL)
        admin, c = _support_client(self)
        r = c.post(f"{QUEUE_URL}{ticket.id}/accept/", {}, format="json")
        self.assertEqual(r.status_code, OK, r.content)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "assigned")
        self.assertIn(admin, ticket.assigned_admins.all())

    def test_cannot_accept_a_ticket_with_no_call_requested(self):
        ticket = _ticket(ContactPreference.NONE)
        _, c = _support_client(self)
        r = c.post(f"{QUEUE_URL}{ticket.id}/accept/", {}, format="json")
        self.assertEqual(r.status_code, BAD_REQUEST, r.content)

    def test_other_department_admin_cannot_accept(self):
        ticket = _ticket(ContactPreference.PHONE_CALL)
        admin = make_named_admin(department="Finance")
        c = self.client_class()
        login(c, admin)
        r = c.post(f"{QUEUE_URL}{ticket.id}/accept/", {}, format="json")
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_departmentless_admin_cannot_accept(self):
        ticket = _ticket(ContactPreference.PHONE_CALL)
        c = self.client_class()
        login(c, make_user(role=UserRole.ADMIN))
        r = c.post(f"{QUEUE_URL}{ticket.id}/accept/", {}, format="json")
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_superadmin_can_accept(self):
        ticket = _ticket(ContactPreference.VIDEO_CALL)
        sa = make_user(role=UserRole.SUPERADMIN)
        c = self.client_class()
        login(c, sa)
        r = c.post(f"{QUEUE_URL}{ticket.id}/accept/", {}, format="json")
        self.assertEqual(r.status_code, OK, r.content)

    def test_accepted_support_admin_can_then_resolve(self):
        ticket = _ticket(ContactPreference.PHONE_CALL)
        _, c = _support_client(self)
        c.post(f"{QUEUE_URL}{ticket.id}/accept/", {}, format="json")
        r = c.post(f"{QUEUE_URL}{ticket.id}/resolve/", {"resolution": "Called, sorted."}, format="json")
        self.assertEqual(r.status_code, OK, r.content)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")


class ReporterMobileFieldTests(APITestCase):
    def test_reporter_mobile_visible_to_support_admin(self):
        ticket = _ticket(ContactPreference.PHONE_CALL)
        _, c = _support_client(self)
        r = c.get(QUEUE_URL, {"status": "all"})
        self.assertEqual(r.status_code, OK, r.content)
        row = next(x for x in r.data["data"] if x["id"] == str(ticket.id))
        self.assertEqual(row["reporter_mobile"], ticket.reporter.mobile)
