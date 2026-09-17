"""
Student security: Student A must never read or act on Student B's requirements /
preferences / profile, nor reach teacher/admin surfaces, nor self-escalate.
(2026-08-31 security audit - all currently PASS; these lock the guarantees in.)

Run: python manage.py test apps.student_requirement.tests.test_student_security \
     --settings=config.settings.test
"""

import uuid

from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.languages.models import Language
from apps.student_requirement.models import StudentRequirement
from apps.subjects.models import Subject

REQS = "/api/v1/student-requirements/"


class StudentIsolationSecurityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Subject.objects.get_or_create(name="Mathematics")
        Subject.objects.get_or_create(name="Physics")
        Language.objects.get_or_create(name="English", defaults={"code": "en"})

    def setUp(self):
        self.a = make_user(role=UserRole.STUDENT)
        self.b = make_user(role=UserRole.STUDENT)
        login(self.client, self.b)
        resp = self.client.post(
            REQS,
            {
                "subject": "Mathematics",
                "preferred_languages": ["English"],
                "teaching_mode": "online",
                "budget_min": 200,
                "budget_max": 900,
                "class_duration_minutes": 60,
                "description": "B private",
                "schedule_preferences": [
                    {
                        "day_of_week": 1,
                        "start_time": "18:00",
                        "end_time": "19:00",
                        "timezone": "Asia/Kolkata",
                        "flexibility": "flexible",
                    }
                ],
            },
            format="json",
        )
        assert resp.status_code == 202, resp.content
        self.b_req_id = resp.json()["data"]["id"]
        self.client.post(
            f"{REQS}preferences/",
            {
                "requirement_id": self.b_req_id,
                "day_of_week": 3,
                "start_time": "17:00",
                "end_time": "18:00",
                "timezone": "Asia/Kolkata",
                "flexibility": "flexible",
            },
            format="json",
        )
        self.b_pref_id = self.client.get(
            f"{REQS}preferences/", {"requirement_id": self.b_req_id}
        ).json()["data"][0]["id"]
        # switch the client to attacker A
        self.client.post("/api/v1/auth/logout/", {}, format="json")
        login(self.client, self.a)

    # ---- cross-student requirement access -----------------------------
    def test_a_cannot_read_or_mutate_b_requirement(self):
        self.assertEqual(self.client.get(f"{REQS}{self.b_req_id}/").status_code, 404)
        self.assertEqual(
            self.client.patch(
                f"{REQS}{self.b_req_id}/", {"budget_max": 1}, format="json"
            ).status_code,
            404,
        )
        self.assertEqual(self.client.delete(f"{REQS}{self.b_req_id}/").status_code, 404)
        StudentRequirement.objects.get(id=self.b_req_id)  # still exists / unchanged
        self.assertEqual(
            StudentRequirement.objects.get(id=self.b_req_id).budget_max, 900
        )

    def test_a_requirement_list_excludes_b(self):
        self.assertEqual(self.client.get(REQS).json()["data"], [])

    # ---- cross-student preferences / exceptions -----------------------
    def test_a_cannot_touch_b_preferences(self):
        self.assertEqual(
            self.client.get(
                f"{REQS}preferences/", {"requirement_id": self.b_req_id}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                f"{REQS}preferences/",
                {
                    "requirement_id": self.b_req_id,
                    "day_of_week": 5,
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "timezone": "Asia/Kolkata",
                },
                format="json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(f"{REQS}preferences/{self.b_pref_id}/").status_code, 404
        )
        self.assertEqual(
            self.client.patch(
                f"{REQS}preferences/{self.b_pref_id}/",
                {"start_time": "09:00"},
                format="json",
            ).status_code,
            404,
        )

    def test_a_cannot_add_preference_to_b_via_me_mount(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/students/me/preferences/",
                {
                    "requirement_id": self.b_req_id,
                    "day_of_week": 2,
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "timezone": "Asia/Kolkata",
                },
                format="json",
            ).status_code,
            404,
        )

    # ---- people search -----------------------------------------------
    def test_student_cannot_use_people_search(self):
        self.assertEqual(self.client.get("/api/v1/students/").status_code, 403)
        self.assertEqual(
            self.client.get(f"/api/v1/students/{uuid.uuid4()}/").status_code, 403
        )

    # ---- privilege escalation ---------------------------------------
    def test_student_cannot_self_escalate_via_profile(self):
        self.client.post("/api/v1/students/me/", {"bio": "x"}, format="json")
        self.client.patch(
            "/api/v1/students/me/",
            {"role": "admin", "is_staff": True, "is_superuser": True},
            format="json",
        )
        self.a.refresh_from_db()
        self.assertEqual(self.a.role, UserRole.STUDENT)
        self.assertFalse(self.a.is_staff)
        self.assertFalse(self.a.is_superuser)

    # ---- teacher / admin surfaces ----------------------------------
    def test_teacher_and_admin_surfaces_are_forbidden(self):
        forbidden = [
            ("get", "/api/v1/leads/"),
            ("post", "/api/v1/leads/unlock/"),
            ("get", "/api/v1/matching/assignments/"),
            ("get", "/api/v1/wallet/"),
            ("get", "/api/v1/subscriptions/"),
            ("post", "/api/v1/subscriptions/activate/"),
            ("get", "/api/v1/payments/"),
            ("post", "/api/v1/payments/create-order/"),
            ("get", "/api/v1/dashboard/"),
            ("get", "/api/v1/teachers/me/"),
            ("get", "/api/v1/admin/users/"),
            ("get", "/api/v1/ops/health/"),
            ("post", "/api/v1/subjects/"),
        ]
        for method, path in forbidden:
            fn = getattr(self.client, method)
            resp = fn(path, {}, format="json") if method == "post" else fn(path)
            self.assertEqual(
                resp.status_code, 403, f"{method.upper()} {path} -> {resp.status_code}"
            )

    # ---- validation cannot be bypassed ----------------------------
    def test_requirement_validation_holds(self):
        base = {
            "subject": "Mathematics",
            "preferred_languages": ["English"],
            "teaching_mode": "online",
            "class_duration_minutes": 60,
        }
        self.assertEqual(
            self.client.post(
                REQS, {**base, "budget_min": 900, "budget_max": 100}, format="json"
            ).status_code,
            400,
        )
        # Unknown subject/language text is no longer a validation failure -
        # it's auto-created into the taxonomy (see
        # StudentRequirementWriteSerializer.validate_subject /
        # validate_preferred_languages) - so this checks a value that's
        # still genuinely invalid: teaching_mode isn't in the model's
        # choices at all.
        self.assertEqual(
            self.client.post(
                REQS, {**base, "teaching_mode": "hybrid"}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                REQS,
                {
                    "subject": "Mathematics",
                    "preferred_languages": ["English"],
                    "teaching_mode": "offline",
                    "class_duration_minutes": 60,
                },
                format="json",
            ).status_code,
            400,
        )
        # duplicate open requirement (same subject + mode)
        self.client.post(REQS, {**base, "description": "one"}, format="json")
        self.assertEqual(
            self.client.post(
                REQS, {**base, "description": "two"}, format="json"
            ).status_code,
            400,
        )
