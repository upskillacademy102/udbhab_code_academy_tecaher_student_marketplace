"""
Phase 8a / 8b - content-leakage scan + profile moderation hold.

Run: python manage.py test apps.trust.tests.test_content_scan --settings=config.settings.test
"""

from django.test import TestCase, override_settings

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user
from apps.lead_engine.tests.test_lead_pipeline import PipelineFixtureMixin
from apps.teacher_profile.models import ModerationStatus, TeacherProfile
from apps.trust.models import (
    ContentFlag,
    ContentFlagStatus,
    ManualReviewItem,
    ManualReviewKind,
    RiskSignal,
    RiskSignalKind,
)
from apps.trust.services.content_scan_service import ContentScanService

CLEAN = "Experienced maths tutor for grades 6-12, CBSE and ICSE."
DIRTY = "Best rates! WhatsApp me on 9876543210 or pay via gpay to me@okhdfcbank"


class ScanServiceTests(TestCase):
    def test_scan_text_detects_and_passes(self):
        clean, cats, _m = ContentScanService.scan_text(CLEAN)
        self.assertTrue(clean)
        clean, cats, matches = ContentScanService.scan_text(DIRTY)
        self.assertFalse(clean)
        self.assertIn("phone_number", cats)
        self.assertTrue(matches)

    def test_scan_noop_when_flag_off(self):
        self.assertEqual(
            ContentScanService.flag_text(user=None, surface="x", text=DIRTY), []
        )
        self.assertFalse(ContentFlag.objects.exists())


class TeacherProfileModerationTests(PipelineFixtureMixin, TestCase):
    def _profile(self, *, headline):
        prof = self.make_teacher("Mira", plan=self.free_plan)
        prof.headline = headline
        prof.save(update_fields=["headline"])
        return prof

    @override_settings(TRUST_ENABLE_CONTACT_LEAKAGE_SCAN=True)
    def test_dirty_headline_holds_profile(self):
        prof = self._profile(headline=DIRTY)
        ContentScanService.scan_teacher_profile(prof)
        prof.refresh_from_db()
        self.assertEqual(prof.moderation_status, ModerationStatus.HELD)
        self.assertTrue(
            ContentFlag.objects.filter(
                subject_user=prof.teacher.user, status=ContentFlagStatus.OPEN
            ).exists()
        )
        self.assertTrue(
            ManualReviewItem.objects.filter(kind=ManualReviewKind.CONTENT_FLAG).exists()
        )
        self.assertTrue(
            RiskSignal.objects.filter(
                user=prof.teacher.user, kind=RiskSignalKind.CONTENT_LEAKAGE
            ).exists()
        )

    @override_settings(TRUST_ENABLE_CONTACT_LEAKAGE_SCAN=True)
    def test_fixing_content_self_heals(self):
        prof = self._profile(headline=DIRTY)
        ContentScanService.scan_teacher_profile(prof)
        prof.refresh_from_db()
        self.assertEqual(prof.moderation_status, ModerationStatus.HELD)

        prof.headline = CLEAN
        prof.save(update_fields=["headline"])
        ContentScanService.scan_teacher_profile(prof)
        prof.refresh_from_db()
        self.assertEqual(prof.moderation_status, ModerationStatus.CLEAR)
        self.assertFalse(
            ContentFlag.objects.filter(
                subject_user=prof.teacher.user, status=ContentFlagStatus.OPEN
            ).exists()
        )

    def test_noop_when_flag_off(self):
        prof = self._profile(headline=DIRTY)
        ContentScanService.scan_teacher_profile(prof)
        prof.refresh_from_db()
        self.assertEqual(prof.moderation_status, ModerationStatus.CLEAR)
        self.assertFalse(ContentFlag.objects.exists())


class HeldProfileHiddenTests(PipelineFixtureMixin, TestCase):
    def test_held_profile_excluded_from_lead_candidates_when_flag_on(self):
        from apps.lead_engine.services.lead_generation_service import (
            find_candidate_teacher_profiles,
        )

        held = self.make_teacher("Held", plan=self.free_plan)
        ok = self.make_teacher("Okay", plan=self.free_plan)
        req = self.make_requirement()

        with override_settings(TRUST_ENABLE_CONTACT_LEAKAGE_SCAN=True):
            TeacherProfile.objects.filter(pk=held.pk).update(
                moderation_status=ModerationStatus.HELD
            )
            ids = set(find_candidate_teacher_profiles(req).values_list("id", flat=True))
            self.assertIn(ok.id, ids)
            self.assertNotIn(held.id, ids)

    def test_held_profile_visible_when_flag_off(self):
        from apps.lead_engine.services.lead_generation_service import (
            find_candidate_teacher_profiles,
        )

        held = self.make_teacher("Held2", plan=self.free_plan)
        TeacherProfile.objects.filter(pk=held.pk).update(
            moderation_status=ModerationStatus.HELD
        )
        req = self.make_requirement()
        ids = set(find_candidate_teacher_profiles(req).values_list("id", flat=True))
        self.assertIn(held.id, ids)  # flag OFF -> no hiding


class ProfileEditIntegrationTests(PipelineFixtureMixin, TestCase):
    @override_settings(TRUST_ENABLE_CONTACT_LEAKAGE_SCAN=True)
    def test_editing_headline_via_api_triggers_scan(self):
        from rest_framework.test import APIClient

        user = make_user(role=UserRole.TEACHER)
        client = APIClient()
        login(client, user)
        client.post(
            "/api/v1/teachers/me/",
            {"bio": "x" * 40, "experience_years": 5},
            format="json",
        )
        r = client.post(
            "/api/v1/teachers/profile/",
            {"headline": DIRTY, "teaching_mode": "online"},
            format="json",
        )
        self.assertIn(r.status_code, (200, 201), r.content)
        prof = TeacherProfile.objects.get(teacher__user=user)
        self.assertEqual(prof.moderation_status, ModerationStatus.HELD)
