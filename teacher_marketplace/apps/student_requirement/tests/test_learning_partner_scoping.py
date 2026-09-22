"""
Phase LP-3: posting a requirement resolves free-text subject/language
through the viewer-aware SubjectMatchingService/LanguageMatchingService
(validate_subject/_resolve_language in apps/student_requirement/serializers.py).
A student linked to a Learning Partner can post using that partner's own
scoped subject/language by name; an unrelated student typing the identical
name never resolves to it - the auto-create fallback still always creates
a new, platform-wide row, exactly as it did before Learning Partner scoping
existed, never a partner-scoped one.

Run: python manage.py test apps.student_requirement.tests.test_learning_partner_scoping \
     --settings=config.settings.test
"""

from rest_framework.test import APITestCase

from apps.accounts.tests.helpers import login, make_learning_partner_admin, make_user
from apps.languages.models import Language
from apps.student_requirement.models import StudentRequirement
from apps.subjects.models import Subject

REQS = "/api/v1/student-requirements/"


class RequirementSubjectScopingTests(APITestCase):
    def setUp(self):
        self.lp = make_learning_partner_admin("ReqPartner")
        self.scoped_subject = Subject.objects.create(
            name="Req Partner Robotics", learning_partner=self.lp
        )

    def _post(self, user, **extra):
        StudentRequirement.objects.filter(student=user).delete()
        login(self.client, user)
        body = {
            "subject": "Req Partner Robotics",
            "no_language_preference": True,
            "teaching_mode": "online",
            "class_duration_minutes": 60,
            **extra,
        }
        return self.client.post(REQS, body, format="json")

    def test_linked_student_resolves_to_the_partners_own_subject(self):
        student = make_user(learning_partner=self.lp)
        r = self._post(student)
        self.assertEqual(r.status_code, 202, r.content)
        req = StudentRequirement.objects.get(student=student)
        self.assertEqual(req.subject_id, self.scoped_subject.id)

    def test_unrelated_student_never_resolves_to_the_partners_subject(self):
        student = make_user()
        r = self._post(student)
        self.assertEqual(r.status_code, 202, r.content)
        req = StudentRequirement.objects.get(student=student)
        self.assertNotEqual(req.subject_id, self.scoped_subject.id)
        # Falls through to the pre-existing auto-create escape hatch - a
        # NEW, platform-wide subject, never the partner-scoped one.
        self.assertIsNone(req.subject.learning_partner_id)
        self.assertEqual(req.subject.name, "Req Partner Robotics")

    def test_subject_count_reflects_one_new_global_row_created(self):
        before = Subject.objects.filter(name="Req Partner Robotics").count()
        self.assertEqual(before, 1)  # just the partner-scoped one
        self._post(make_user())
        after = Subject.objects.filter(name="Req Partner Robotics").count()
        self.assertEqual(after, 2)  # + the newly auto-created global one


class RequirementLanguageScopingTests(APITestCase):
    def setUp(self):
        self.lp = make_learning_partner_admin("ReqLangPartner")
        self.scoped_language = Language.objects.create(
            name="Req Partner Konkani", code="rpkk", learning_partner=self.lp
        )

    def _post(self, user, **extra):
        StudentRequirement.objects.filter(student=user).delete()
        login(self.client, user)
        body = {
            "subject": "General Study Help",
            "preferred_languages": ["Req Partner Konkani"],
            "teaching_mode": "online",
            "class_duration_minutes": 60,
            **extra,
        }
        return self.client.post(REQS, body, format="json")

    def test_linked_student_resolves_to_the_partners_own_language(self):
        student = make_user(learning_partner=self.lp)
        r = self._post(student)
        self.assertEqual(r.status_code, 202, r.content)
        req = StudentRequirement.objects.get(student=student)
        # preferred_languages is the StudentRequirementLanguage through-model
        # related manager (ranked list), not Language rows directly.
        self.assertEqual(
            set(req.preferred_languages.values_list("language_id", flat=True)),
            {self.scoped_language.id},
        )

    def test_unrelated_student_gets_a_new_global_language_instead(self):
        student = make_user()
        r = self._post(student)
        self.assertEqual(r.status_code, 202, r.content)
        req = StudentRequirement.objects.get(student=student)
        created = req.preferred_languages.first().language
        self.assertNotEqual(created.id, self.scoped_language.id)
        self.assertIsNone(created.learning_partner_id)
