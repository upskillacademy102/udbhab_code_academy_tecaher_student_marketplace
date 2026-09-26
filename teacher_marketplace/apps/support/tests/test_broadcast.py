"""
"Circulate a message" - apps.support.broadcast_service / broadcast_views.

Run: python manage.py test apps.support.tests.test_broadcast \
     --settings=config.settings.test
"""

from django.core import mail
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_named_admin, make_user
from apps.support.broadcast_service import BroadcastService
from apps.support.models import BroadcastMessage, BroadcastRecipient

OK = status.HTTP_200_OK
CREATED = status.HTTP_201_CREATED
FORBIDDEN = status.HTTP_403_FORBIDDEN
BAD_REQUEST = status.HTTP_400_BAD_REQUEST

URL = "/api/v1/admin/broadcast-messages/"


def _support_client(test):
    admin = make_named_admin(department="Support")
    c = test.client_class()
    login(c, admin)
    return admin, c


class BroadcastServiceTests(APITestCase):
    def test_send_via_email_creates_recipients_and_sends(self):
        admin, _ = _support_client(self)
        student = make_user(role=UserRole.STUDENT, email="stu1@example.com")
        message = BroadcastService.send(
            admin,
            subject="Heads up",
            body="Please update your profile.",
            via_email=True,
            via_sms=False,
            recipients=[student],
        )
        self.assertEqual(message.recipient_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [student.email])
        self.assertEqual(mail.outbox[0].subject, "Heads up")
        row = BroadcastRecipient.objects.get(message=message, user=student)
        self.assertTrue(row.email_sent)
        self.assertFalse(row.sms_sent)

    def test_send_via_sms_uses_console_provider_in_tests(self):
        admin, _ = _support_client(self)
        student = make_user(role=UserRole.STUDENT, email="stu2@example.com")
        message = BroadcastService.send(
            admin,
            subject="Reminder",
            body="Your session is tomorrow.",
            via_email=False,
            via_sms=True,
            recipients=[student],
        )
        row = BroadcastRecipient.objects.get(message=message, user=student)
        self.assertTrue(row.sms_sent)
        self.assertFalse(row.email_sent)
        self.assertEqual(len(mail.outbox), 0)

    def test_send_via_both_channels(self):
        admin, _ = _support_client(self)
        student = make_user(role=UserRole.STUDENT, email="stu3@example.com")
        message = BroadcastService.send(
            admin,
            subject="Both",
            body="Both channels.",
            via_email=True,
            via_sms=True,
            recipients=[student],
        )
        row = BroadcastRecipient.objects.get(message=message, user=student)
        self.assertTrue(row.email_sent)
        self.assertTrue(row.sms_sent)
        self.assertEqual(len(mail.outbox), 1)

    def test_recipient_without_mobile_is_skipped_for_sms_not_errored(self):
        admin, _ = _support_client(self)
        student = make_user(role=UserRole.STUDENT, email="stu4@example.com", mobile="")
        message = BroadcastService.send(
            admin, subject="X", body="Y", via_email=False, via_sms=True, recipients=[student]
        )
        row = BroadcastRecipient.objects.get(message=message, user=student)
        self.assertFalse(row.sms_sent)
        self.assertEqual(row.sms_error, "")


class BroadcastViewPermissionTests(APITestCase):
    def test_support_admin_can_send(self):
        _, c = _support_client(self)
        student = make_user(role=UserRole.STUDENT, email="rec1@example.com")
        r = c.post(
            URL,
            {
                "subject": "Hi",
                "body": "Hello there.",
                "via_email": True,
                "via_sms": False,
                "recipient_ids": [str(student.id)],
            },
            format="json",
        )
        self.assertEqual(r.status_code, CREATED, r.content)
        self.assertEqual(r.data["data"]["recipient_count"], 1)

    def test_support_admin_can_list_history(self):
        _, c = _support_client(self)
        r = c.get(URL)
        self.assertEqual(r.status_code, OK, r.content)

    def test_other_department_admin_cannot_send(self):
        admin = make_named_admin(department="Finance")
        c = self.client_class()
        login(c, admin)
        student = make_user(role=UserRole.STUDENT, email="rec2@example.com")
        r = c.post(
            URL,
            {
                "subject": "Hi",
                "body": "Hello there.",
                "via_email": True,
                "recipient_ids": [str(student.id)],
            },
            format="json",
        )
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_departmentless_admin_cannot_send(self):
        c = self.client_class()
        login(c, make_user(role=UserRole.ADMIN))
        student = make_user(role=UserRole.STUDENT, email="rec3@example.com")
        r = c.post(
            URL,
            {"subject": "Hi", "body": "Hello.", "via_email": True, "recipient_ids": [str(student.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_student_cannot_send(self):
        c = self.client_class()
        login(c, make_user(role=UserRole.STUDENT))
        r = c.post(
            URL,
            {"subject": "Hi", "body": "Hello.", "via_email": True, "recipient_ids": []},
            format="json",
        )
        self.assertEqual(r.status_code, FORBIDDEN)

    def test_superadmin_can_send(self):
        sa = make_user(role=UserRole.SUPERADMIN)
        c = self.client_class()
        login(c, sa)
        student = make_user(role=UserRole.STUDENT, email="rec4@example.com")
        r = c.post(
            URL,
            {"subject": "Hi", "body": "Hello.", "via_email": True, "recipient_ids": [str(student.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, CREATED, r.content)


class BroadcastViewValidationTests(APITestCase):
    def test_no_channel_selected_is_rejected(self):
        _, c = _support_client(self)
        student = make_user(role=UserRole.STUDENT, email="val1@example.com")
        r = c.post(
            URL,
            {"subject": "Hi", "body": "Hello.", "recipient_ids": [str(student.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, BAD_REQUEST, r.content)

    def test_no_recipients_is_rejected(self):
        _, c = _support_client(self)
        r = c.post(
            URL,
            {"subject": "Hi", "body": "Hello.", "via_email": True, "recipient_ids": []},
            format="json",
        )
        self.assertEqual(r.status_code, BAD_REQUEST, r.content)

    def test_admin_recipient_id_is_rejected(self):
        # A Support admin can only message student/teacher/learning_partner
        # accounts - not another admin, even if they somehow got the id.
        _, c = _support_client(self)
        other_admin = make_named_admin(department="Finance", email="other-admin@x.test")
        r = c.post(
            URL,
            {
                "subject": "Hi",
                "body": "Hello.",
                "via_email": True,
                "recipient_ids": [str(other_admin.id)],
            },
            format="json",
        )
        self.assertEqual(r.status_code, BAD_REQUEST, r.content)
        self.assertEqual(BroadcastMessage.objects.count(), 0)

    def test_inactive_recipient_is_rejected(self):
        _, c = _support_client(self)
        student = make_user(role=UserRole.STUDENT, email="inactive@example.com", is_active=False)
        r = c.post(
            URL,
            {
                "subject": "Hi",
                "body": "Hello.",
                "via_email": True,
                "recipient_ids": [str(student.id)],
            },
            format="json",
        )
        self.assertEqual(r.status_code, BAD_REQUEST, r.content)
