"""
"Connect to Admin" support tickets: filing (student/teacher), the admin
queue ("Bugs Reported"), assignment (Super Admin only), and resolution
(assigned Admin or Super Admin).

Run: python manage.py test apps.support --settings=config.settings.test
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_named_admin, make_user
from apps.support.models import SupportTicket
from apps.trust.models import ManualReviewItem, ManualReviewKind

TICKETS_URL = "/api/v1/support/tickets/"
QUEUE_URL = "/api/v1/admin/support-tickets/"


def _photo(name="shot.png"):
    buf = io.BytesIO()
    Image.new("RGB", (48, 48), "green").save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


class FilingTicketsTests(APITestCase):
    def test_student_can_file_a_ticket(self):
        login(self.client, make_user(role=UserRole.STUDENT))
        r = self.client.post(
            TICKETS_URL,
            {"subject": "Can't unlock a lead", "description": "It just spins forever."},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(SupportTicket.objects.count(), 1)
        ticket = SupportTicket.objects.get()
        self.assertEqual(ticket.status, "open")
        self.assertTrue(
            ManualReviewItem.objects.filter(
                kind=ManualReviewKind.SUPPORT_TICKET, subject_user=ticket.reporter
            ).exists()
        )

    def test_teacher_can_file_a_ticket_with_attachments_and_a_call_request(self):
        login(self.client, make_user(role=UserRole.TEACHER))
        r = self.client.post(
            TICKETS_URL,
            {
                "subject": "Payout page is broken",
                "description": "Wallet balance shows negative after a payout.",
                "contact_preference": "video_call",
                "attachments": [_photo("a.png"), _photo("b.png")],
            },
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.content)
        ticket = SupportTicket.objects.get()
        self.assertEqual(ticket.contact_preference, "video_call")
        self.assertEqual(ticket.attachments.count(), 2)
        review = ManualReviewItem.objects.get(kind=ManualReviewKind.SUPPORT_TICKET)
        self.assertEqual(review.priority, 2)  # a call request bumps priority

    def test_too_many_attachments_is_400(self):
        login(self.client, make_user(role=UserRole.STUDENT))
        r = self.client.post(
            TICKETS_URL,
            {
                "subject": "x",
                "description": "y",
                "attachments": [_photo(f"{i}.png") for i in range(6)],
            },
            format="multipart",
        )
        self.assertEqual(r.status_code, 400, r.content)

    def test_missing_subject_is_400(self):
        login(self.client, make_user(role=UserRole.TEACHER))
        r = self.client.post(TICKETS_URL, {"description": "y"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_bad_screenshot_is_rejected(self):
        login(self.client, make_user(role=UserRole.STUDENT))
        bad = SimpleUploadedFile(
            "x.png", b"<html>not an image</html>", content_type="image/png"
        )
        r = self.client.post(
            TICKETS_URL,
            {"subject": "x", "description": "y", "attachments": [bad]},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400, r.content)

    def test_plain_admin_cannot_file_a_ticket(self):
        # Super Admin is deliberately excluded here: it's allowed on every
        # route by the platform-wide is_allowed() short-circuit (see
        # apps/accounts/api_permissions.py), same as everywhere else in the
        # app - this endpoint isn't special-cased against that invariant.
        c = self.client_class()
        login(c, make_user(role=UserRole.ADMIN))
        r = c.post(TICKETS_URL, {"subject": "x", "description": "y"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_reporter_sees_only_their_own_tickets(self):
        s1 = make_user(role=UserRole.STUDENT, email="s1@x.test")
        s2 = make_user(role=UserRole.STUDENT, email="s2@x.test")
        login(self.client, s1)
        self.client.post(TICKETS_URL, {"subject": "a", "description": "b"}, format="json")
        c2 = self.client_class()
        login(c2, s2)
        self.assertEqual(len(c2.get(TICKETS_URL).json()["data"]), 0)
        self.assertEqual(len(self.client.get(TICKETS_URL).json()["data"]), 1)


class QueueAndAssignmentTests(APITestCase):
    def setUp(self):
        self.reporter = make_user(role=UserRole.TEACHER)
        login(self.client, self.reporter)
        self.client.post(
            TICKETS_URL,
            {"subject": "Bug", "description": "Details here."},
            format="json",
        )
        self.ticket = SupportTicket.objects.get()
        self.assign_url = f"/api/v1/admin/support-tickets/{self.ticket.id}/assign/"
        self.resolve_url = f"/api/v1/admin/support-tickets/{self.ticket.id}/resolve/"

    def test_admin_and_superadmin_see_the_queue(self):
        for role in (UserRole.ADMIN, UserRole.SUPERADMIN):
            c = self.client_class()
            login(c, make_user(role=role, email=f"see-{role}@x.test"))
            r = c.get(QUEUE_URL)
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(len(r.json()["data"]), 1)

    def test_student_and_teacher_cannot_see_the_queue(self):
        for role in (UserRole.STUDENT, UserRole.TEACHER):
            c = self.client_class()
            login(c, make_user(role=role, email=f"deny-{role}@x.test"))
            self.assertEqual(c.get(QUEUE_URL).status_code, 403)

    def test_plain_admin_cannot_assign(self):
        assignee = make_user(role=UserRole.ADMIN, email="a1@x.test")
        c = self.client_class()
        login(c, make_user(role=UserRole.ADMIN, email="a2@x.test"))
        r = c.post(self.assign_url, {"assigned_admin_ids": [str(assignee.id)]}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_superadmin_assigns_multiple_admins(self):
        a1 = make_user(role=UserRole.ADMIN, email="m1@x.test")
        a2 = make_user(role=UserRole.ADMIN, email="m2@x.test")
        c = self.client_class()
        login(c, make_user(role=UserRole.SUPERADMIN))
        r = c.post(
            self.assign_url,
            {"assigned_admin_ids": [str(a1.id), str(a2.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "assigned")
        self.assertEqual(set(self.ticket.assigned_admins.all()), {a1, a2})

    def test_invalid_assignee_is_400(self):
        student = make_user(role=UserRole.STUDENT)
        c = self.client_class()
        login(c, make_user(role=UserRole.SUPERADMIN))
        r = c.post(self.assign_url, {"assigned_admin_ids": [str(student.id)]}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_assigned_admin_can_resolve_but_others_cannot(self):
        # admin_support:resolve is Support-department only (apps.accounts.
        # api_permissions.DEPARTMENT_ROUTE_SCOPE) on top of the assignment
        # check below - both admins need the department so `other`'s 403
        # is actually testing "not assigned", not "wrong department".
        assignee = make_named_admin(department="Support", email="assignee@x.test")
        # Distinct name: make_named_admin defaults to "Raju Das" for every
        # call, and two admins in the same department would otherwise both
        # generate account_name "RajuDas@Support" and collide.
        other = make_named_admin(
            department="Support",
            first_name="Other",
            last_name="Admin",
            email="other@x.test",
        )
        sa = self.client_class()
        login(sa, make_user(role=UserRole.SUPERADMIN))
        sa.post(self.assign_url, {"assigned_admin_ids": [str(assignee.id)]}, format="json")

        c_other = self.client_class()
        login(c_other, other)
        self.assertEqual(
            c_other.post(self.resolve_url, {"resolution": "nope"}, format="json").status_code,
            403,
        )

        c_assignee = self.client_class()
        login(c_assignee, assignee)
        r = c_assignee.post(
            self.resolve_url, {"resolution": "Fixed it."}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "resolved")
        self.assertEqual(self.ticket.resolution, "Fixed it.")
        self.assertFalse(self.ticket.review_item.is_open)

    def test_superadmin_can_always_resolve(self):
        c = self.client_class()
        login(c, make_user(role=UserRole.SUPERADMIN))
        r = c.post(self.resolve_url, {"dismiss": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "closed")

    def test_resolved_tickets_excluded_by_default_but_included_with_all(self):
        c = self.client_class()
        login(c, make_user(role=UserRole.SUPERADMIN))
        c.post(self.resolve_url, {"dismiss": True}, format="json")
        self.assertEqual(len(c.get(QUEUE_URL).json()["data"]), 0)
        self.assertEqual(len(c.get(QUEUE_URL, {"status": "all"}).json()["data"]), 1)

    def test_reporter_sees_resolution_on_their_own_ticket(self):
        c = self.client_class()
        login(c, make_user(role=UserRole.SUPERADMIN))
        c.post(self.resolve_url, {"resolution": "All good now."}, format="json")

        rows = self.client.get(TICKETS_URL).json()["data"]
        self.assertEqual(rows[0]["status"], "resolved")
        self.assertEqual(rows[0]["resolution"], "All good now.")
