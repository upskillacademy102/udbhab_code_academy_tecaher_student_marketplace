"""
Phase LP-3: SubjectMatchingService/LanguageMatchingService.match_by_text's
`viewer` parameter - the free-text resolution path used by search, the
eligible-teacher matcher and student-requirement free-text subject/language
entry. A global row always matches; a partner-scoped row only matches for
that partner's own viewer.

Run: python manage.py test apps.matching.tests.test_learning_partner_matching \
     --settings=config.settings.test
"""

from django.test import TestCase

from apps.accounts.tests.helpers import make_learning_partner_admin, make_user
from apps.languages.models import Language
from apps.matching.services.language_matching_service import LanguageMatchingService
from apps.matching.services.subject_matching_service import SubjectMatchingService
from apps.subjects.models import Subject


class SubjectMatchByTextViewerScopingTests(TestCase):
    def setUp(self):
        self.lp_a = make_learning_partner_admin("MatchPartnerA")
        self.lp_b = make_learning_partner_admin("MatchPartnerB")
        self.global_subject = Subject.objects.create(name="Global Match Subject")
        self.scoped_subject = Subject.objects.create(
            name="Scoped Match Subject", learning_partner=self.lp_a
        )
        self.student_a = make_user(learning_partner=self.lp_a)
        self.student_b = make_user(learning_partner=self.lp_b)
        self.student_none = make_user()

    def test_global_subject_matches_for_any_viewer(self):
        for viewer in (None, self.student_a, self.student_b, self.student_none):
            result = SubjectMatchingService.match_by_text(
                self.global_subject.name, viewer=viewer
            )
            self.assertTrue(result.is_eligible)
            self.assertEqual(result.matched_subject.id, self.global_subject.id)

    def test_scoped_subject_matches_only_for_its_own_partners_viewer(self):
        result = SubjectMatchingService.match_by_text(
            self.scoped_subject.name, viewer=self.student_a
        )
        self.assertTrue(result.is_eligible)
        self.assertEqual(result.matched_subject.id, self.scoped_subject.id)

    def test_scoped_subject_invisible_to_another_partners_viewer(self):
        # A fuzzy-tier match against some OTHER (global) subject is fine and
        # not what this guards - the one thing that must never happen is
        # this specific partner-scoped row being the match.
        result = SubjectMatchingService.match_by_text(
            self.scoped_subject.name, viewer=self.student_b
        )
        self.assertNotEqual(
            getattr(result.matched_subject, "id", None), self.scoped_subject.id
        )

    def test_scoped_subject_invisible_to_a_partnerless_viewer(self):
        result = SubjectMatchingService.match_by_text(
            self.scoped_subject.name, viewer=self.student_none
        )
        self.assertNotEqual(
            getattr(result.matched_subject, "id", None), self.scoped_subject.id
        )

    def test_scoped_subject_invisible_with_no_viewer_at_all(self):
        result = SubjectMatchingService.match_by_text(self.scoped_subject.name)
        self.assertNotEqual(
            getattr(result.matched_subject, "id", None), self.scoped_subject.id
        )


class LanguageMatchByTextViewerScopingTests(TestCase):
    def setUp(self):
        self.lp_a = make_learning_partner_admin("MatchLangPartnerA")
        self.lp_b = make_learning_partner_admin("MatchLangPartnerB")
        self.global_language = Language.objects.create(name="Global Match Language", code="gml")
        self.scoped_language = Language.objects.create(
            name="Scoped Match Language", code="sml", learning_partner=self.lp_a
        )
        self.student_a = make_user(learning_partner=self.lp_a)
        self.student_b = make_user(learning_partner=self.lp_b)

    def test_global_language_matches_for_any_viewer(self):
        result = LanguageMatchingService.match_by_text(self.global_language.name, viewer=self.student_b)
        self.assertTrue(result.is_eligible)
        self.assertEqual(result.matched_subject.id, self.global_language.id)

    def test_scoped_language_matches_only_for_its_own_partners_viewer(self):
        result = LanguageMatchingService.match_by_text(self.scoped_language.name, viewer=self.student_a)
        self.assertTrue(result.is_eligible)
        self.assertEqual(result.matched_subject.id, self.scoped_language.id)

    def test_scoped_language_invisible_to_another_partners_viewer(self):
        result = LanguageMatchingService.match_by_text(self.scoped_language.name, viewer=self.student_b)
        self.assertNotEqual(
            getattr(result.matched_subject, "id", None), self.scoped_language.id
        )
