"""
VerificationService - the teacher verification checklist, progress score,
and the "Fully verified" badge.

Ten checklist items, split in two:

  * FLOOR (auto-derived, weight 60):  profile_basics, subjects_set,
    availability_set, email_verified, mobile_verified. When all five are
    met the teacher clears the *floor* - the minimum to receive any leads
    once ``TRUST_TEACHER_FLOOR_FOR_LEADS`` is on - and their marketplace
    ``verification_status`` is auto-upgraded PENDING -> VERIFIED.
    ``profile_basics`` itself requires a profile photo plus bio,
    experience, and qualification level - a teacher without a photo can
    never clear the floor.

  * REVIEWED (submitted by the teacher, decided by a provider or an
    admin, weight 40):  gov_id (20), selfie_liveness (10), address_proof
    (5), video_interview (5).  bank_penny_drop is seeded at weight 0
    (reserved for a future payouts feature).

``verification_score`` = verified weight / total active weight  (0.000 - 1.000),
cached on the user's ``TrustProfile``. Score == 1.000 -> ``is_fully_verified``.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.trust.models import (
    OnboardingCallRequest,
    TeacherVerificationEvidence,
    TeacherVerificationItem,
    TeacherVerificationItemStatus,
    TeacherVerificationKey,
    VerificationEvidencePose,
)
from apps.trust.services.trust_service import TrustService

logger = logging.getLogger("apps.trust.verification")

K = TeacherVerificationKey
S = TeacherVerificationItemStatus

#: (key, weight, is_auto)
ITEM_SPEC: list[tuple[str, int, bool]] = [
    (K.PROFILE_BASICS, 15, True),
    (K.SUBJECTS_SET, 10, True),
    (K.AVAILABILITY_SET, 10, True),
    (K.EMAIL_VERIFIED, 10, True),
    (K.MOBILE_VERIFIED, 15, True),
    (K.GOV_ID, 20, False),
    (K.SELFIE_LIVENESS, 10, False),
    (K.ADDRESS_PROOF, 5, False),
    (K.VIDEO_INTERVIEW, 5, False),
    (K.BANK_PENNY_DROP, 0, False),
]
_SPEC_BY_KEY = {k: (w, a) for (k, w, a) in ITEM_SPEC}

#: For each reviewed key that takes an uploaded photo, the multipart field
#: name(s) the submit view accepts, mapped to the evidence "pose" they're
#: stored under. video_interview and bank_penny_drop take no files.
EP = VerificationEvidencePose
_EVIDENCE_FIELD_POSES: dict[str, dict[str, str]] = {
    K.GOV_ID: {"front": EP.DOCUMENT_FRONT, "back": EP.DOCUMENT_BACK},
    K.ADDRESS_PROOF: {"document": EP.DOCUMENT},
    K.SELFIE_LIVENESS: {
        "center": EP.SELFIE_CENTER,
        "left": EP.SELFIE_LEFT,
        "right": EP.SELFIE_RIGHT,
        "up": EP.SELFIE_UP,
        "down": EP.SELFIE_DOWN,
    },
}
FLOOR_KEYS = frozenset(
    {
        K.PROFILE_BASICS,
        K.SUBJECTS_SET,
        K.AVAILABILITY_SET,
        K.EMAIL_VERIFIED,
        K.MOBILE_VERIFIED,
    }
)

#: Two ways to prove the same thing (you're a real person). A teacher only
#: needs to pass ONE of these - completing either earns the pair's combined
#: weight; the other item's own status is never faked, it just stops being
#: required (see recompute()'s earned-weight calc).
IDENTITY_CHECK_KEYS = frozenset({K.SELFIE_LIVENESS, K.VIDEO_INTERVIEW})


def recompute_for_user(user) -> None:
    """
    Safe best-effort recompute for a teacher user - call it from the profile
    / availability save paths so the cached score + badge track the checklist
    without waiting for the 6-hourly sweep. Never raises.
    """
    teacher = getattr(user, "teacher_profile", None)
    if teacher is None:
        return
    try:
        VerificationService.recompute(teacher)
    except Exception:  # noqa: BLE001
        logger.exception("recompute_for_user failed for %s", getattr(user, "id", "?"))


class VerificationService:
    # ----- checklist rows --------------------------------------------
    @staticmethod
    def ensure_items(teacher) -> None:
        by_key = {i.key: i for i in teacher.verification_items.all()}
        to_create, to_update = [], []
        for key, weight, is_auto in ITEM_SPEC:
            item = by_key.get(key)
            if item is None:
                to_create.append(
                    TeacherVerificationItem(
                        teacher=teacher, key=key, weight=weight, is_auto=is_auto
                    )
                )
            elif item.weight != weight or item.is_auto != is_auto:
                item.weight, item.is_auto = weight, is_auto
                to_update.append(item)
        if to_create:
            TeacherVerificationItem.objects.bulk_create(
                to_create, ignore_conflicts=True
            )
        if to_update:
            TeacherVerificationItem.objects.bulk_update(
                to_update, ["weight", "is_auto"]
            )

    @staticmethod
    def _auto_met(teacher, key: str) -> bool:
        user = teacher.user
        if key == K.EMAIL_VERIFIED:
            return bool(user.is_email_verified)
        if key == K.MOBILE_VERIFIED:
            return bool(user.is_mobile_verified)
        if key == K.PROFILE_BASICS:
            return bool(
                teacher.profile_photo
                and (teacher.bio or "").strip()
                and teacher.experience_years is not None
                and (teacher.qualification_level or "").strip()
            )
        mp = getattr(teacher, "marketplace_profile", None)
        if mp is None:
            return False
        if key == K.SUBJECTS_SET:
            return mp.subjects.exists()
        if key == K.AVAILABILITY_SET:
            return mp.weekly_availability.filter(is_active=True).exists()
        return False

    # ----- recompute -------------------------------------------------
    @staticmethod
    @transaction.atomic
    def recompute(teacher):
        """Refresh the auto items, the cached score/badge, and (upgrade-only)
        the marketplace verification_status. Returns the TrustProfile."""
        VerificationService.ensure_items(teacher)
        items = list(teacher.verification_items.all())

        floor_met = True
        for item in items:
            if item.is_auto:
                target = (
                    S.VERIFIED
                    if VerificationService._auto_met(teacher, item.key)
                    else S.PENDING
                )
                if item.status != target:
                    item.status = target
                    item.save(update_fields=["status", "updated_at"])
            if item.key in FLOOR_KEYS and item.status != S.VERIFIED:
                floor_met = False

        active = [i for i in items if i.weight > 0]
        total = sum(i.weight for i in active) or 1
        # Selfie/liveness and the video call are either/or: passing either
        # one earns their combined weight instead of requiring both.
        identity_group = [i for i in active if i.key in IDENTITY_CHECK_KEYS]
        identity_earned = (
            sum(i.weight for i in identity_group)
            if any(i.status == S.VERIFIED for i in identity_group)
            else 0
        )
        earned = (
            sum(
                i.weight
                for i in active
                if i.status == S.VERIFIED and i.key not in IDENTITY_CHECK_KEYS
            )
            + identity_earned
        )
        score = (Decimal(earned) / Decimal(total)).quantize(Decimal("0.001"))

        profile = TrustService.get_or_create_profile(teacher.user)
        profile.verification_score = score
        profile.is_fully_verified = score >= Decimal("1.000")
        profile.verification_recomputed_at = timezone.now()
        profile.save(
            update_fields=[
                "verification_score",
                "is_fully_verified",
                "verification_recomputed_at",
                "updated_at",
            ]
        )

        VerificationService._maybe_upgrade_status(teacher, floor_met)
        return profile

    @staticmethod
    def _maybe_upgrade_status(teacher, floor_met: bool) -> None:
        from apps.teacher_profile.models import VerificationStatus

        mp = getattr(teacher, "marketplace_profile", None)
        if mp is None:
            return
        # Only ever PENDING -> VERIFIED. An admin REJECT stands; an admin
        # VERIFIED stands. Downgrades are an admin action only.
        if floor_met and mp.verification_status == VerificationStatus.PENDING:
            mp.verification_status = VerificationStatus.VERIFIED
            mp.save(update_fields=["verification_status", "updated_at"])
            logger.info(
                "verification: %s auto-verified (floor met)", teacher.user.email
            )

    # ----- snapshot for the API ----------------------------------
    @staticmethod
    def snapshot(teacher) -> dict:
        VerificationService.recompute(teacher)
        items = list(teacher.verification_items.all())
        by_key = {i.key: i for i in items}
        rows = []
        for key, weight, is_auto in ITEM_SPEC:
            item = by_key[key]
            row = {
                "key": key,
                "label": K(key).label,
                "status": item.status,
                "weight": weight,
                "is_auto": is_auto,
                "notes": item.notes,
                "evidence": [ev.file.url for ev in item.evidence_files.all()],
            }
            if key == K.VIDEO_INTERVIEW:
                cr = getattr(item, "call_request", None)
                row["call"] = (
                    {
                        "scheduled_at": cr.scheduled_at.isoformat()
                        if cr.scheduled_at
                        else None,
                        "assigned_admin": (
                            cr.assigned_admin.get_full_name()
                            or cr.assigned_admin.email
                        )
                        if cr.assigned_admin
                        else None,
                    }
                    if cr
                    else None
                )
            rows.append(row)
        profile = TrustService.get_or_create_profile(teacher.user)
        floor_met = all(by_key[k].status == S.VERIFIED for k in FLOOR_KEYS)
        return {
            "verification_score": str(profile.verification_score),
            "progress_percent": int(round(float(profile.verification_score) * 100)),
            "is_fully_verified": profile.is_fully_verified,
            "floor_met": floor_met,
            "items": rows,
        }

    # ----- reviewed-item verdicts ---------------------------------
    REVIEWABLE_KEYS = frozenset(
        {
            K.GOV_ID,
            K.SELFIE_LIVENESS,
            K.ADDRESS_PROOF,
            K.VIDEO_INTERVIEW,
            K.BANK_PENNY_DROP,
        }
    )

    @staticmethod
    @transaction.atomic
    def set_reviewed_item(
        teacher,
        key: str,
        *,
        status: str,
        by=None,
        notes: str = "",
        evidence_ref: str = "",
        provider_ref: str = "",
    ):
        if key not in VerificationService.REVIEWABLE_KEYS:
            from apps.core.exceptions.custom_exceptions import ValidationException

            raise ValidationException(
                detail=f"'{key}' is not a reviewable verification item."
            )
        VerificationService.ensure_items(teacher)
        item = teacher.verification_items.get(key=key)
        item.status = status
        if by is not None:
            item.reviewed_by = by
            item.reviewed_at = timezone.now()
        if notes:
            item.notes = notes
        if evidence_ref:
            item.evidence_ref = evidence_ref
        if provider_ref:
            item.provider_ref = provider_ref
        item.save()

        # Evidence-retention trail (Phase 9d): every write that attaches or
        # acts on verification evidence is audit-logged. We record the
        # *reference*, never the document content.
        if evidence_ref or by is not None:
            try:
                from apps.ops.models import AuditCategory
                from apps.ops.services import AuditService

                AuditService.record(
                    action=(
                        "verification_evidence_reviewed"
                        if by is not None
                        else "verification_evidence_submitted"
                    ),
                    category=AuditCategory.SECURITY,
                    actor=by or teacher.user,
                    target=teacher,
                    message=f"{key} -> {status}",
                    verification_key=key,
                    evidence_ref=(evidence_ref or item.evidence_ref or "")[:120],
                )
            except Exception:  # noqa: BLE001
                pass

        # A final admin verdict clears any linked review-queue item.
        if (
            by is not None
            and item.review_item_id
            and status in (S.VERIFIED, S.REJECTED)
        ):
            if item.review_item.is_open:
                TrustService.resolve_review_item(
                    item.review_item, by=by, resolution=f"{status}: {notes}".strip(": ")
                )

        VerificationService.recompute(teacher)
        return item

    @staticmethod
    def _store_evidence(item, key: str, files: dict) -> dict:
        """
        Persist uploaded evidence photos for a reviewed item, replacing any
        evidence from a previous submission (a resubmission shouldn't leave
        old ID scans lying around indefinitely). Returns
        ``{field_name: stored_file_path}`` for whichever fields were
        actually supplied - callers fall back to a plain text ref (or
        nothing, for video_interview) when a field is missing.
        """
        field_poses = _EVIDENCE_FIELD_POSES.get(key, {})
        present = {name: f for name, f in (files or {}).items() if name in field_poses and f}
        if not present:
            return {}
        item.evidence_files.all().delete()
        stored = {}
        for name, f in present.items():
            ev = TeacherVerificationEvidence.objects.create(
                item=item, pose=field_poses[name], file=f
            )
            stored[name] = ev.file.name
        return stored

    @staticmethod
    def _request_video_interview(teacher, item):
        """
        Teacher asks for their onboarding call - opens a manual-review item
        for ops to schedule it. Idempotent: once requested (or already
        decided by an admin), a repeat click just returns the current state
        instead of erroring or opening a second review item.
        """
        from apps.trust.models import ManualReviewKind

        if item.status != S.PENDING:
            return item

        item = VerificationService.set_reviewed_item(
            teacher,
            K.VIDEO_INTERVIEW,
            status=S.SUBMITTED,
            notes="Call requested by teacher.",
        )
        review = TrustService.open_review_item(
            kind=ManualReviewKind.TEACHER_VERIFICATION,
            summary=f"{teacher.user.email} requested an onboarding video call",
            subject_user=teacher.user,
            payload={"key": K.VIDEO_INTERVIEW, "teacher_id": str(teacher.id)},
            dedupe_key=f"tv:{teacher.id}:{K.VIDEO_INTERVIEW}",
            priority=3,
        )
        TeacherVerificationItem.objects.filter(pk=item.pk).update(review_item=review)
        item.review_item = review
        OnboardingCallRequest.objects.get_or_create(item=item)
        return item

    @staticmethod
    @transaction.atomic
    def submit_reviewed_item(teacher, key: str, *, payload: dict, files: dict | None = None):
        """
        Teacher submits a reviewed item. Routes to the matching provider:
        an automated pass -> VERIFIED, "needs a human" -> SUBMITTED + a
        ManualReviewItem, a hard fail -> REJECTED.

        ``files`` (optional) is a dict of uploaded photos keyed by field
        name ("front"/"back" for gov_id, "document" for address_proof, or
        "center"/"left"/"right"/"up"/"down" for selfie_liveness) - the web
        submit view always supplies these; when omitted (e.g. a direct
        service call, as in tests) behaviour is unchanged from before file
        uploads existed: the caller's ``payload`` document_ref/selfie_ref is
        used as-is. video_interview takes no files at all.
        """
        from apps.core.exceptions.custom_exceptions import ValidationException
        from apps.trust.models import ManualReviewKind
        from apps.trust.providers import ProviderResult, get_provider

        if key not in VerificationService.REVIEWABLE_KEYS:
            raise ValidationException(
                detail=f"'{key}' is not a verification item you can submit."
            )

        payload = payload or {}
        VerificationService.ensure_items(teacher)
        item = teacher.verification_items.get(key=key)

        if key == K.VIDEO_INTERVIEW:
            return VerificationService._request_video_interview(teacher, item)

        stored = VerificationService._store_evidence(item, key, files)

        if key == K.GOV_ID:
            document_ref = stored.get("front") or payload.get("document_ref", "")
            result = get_provider("id").verify(
                full_name=payload.get("full_name", ""),
                date_of_birth=payload.get("date_of_birth"),
                document_type=payload.get("document_type", ""),
                document_ref=document_ref,
            )
            evidence = document_ref
        elif key == K.SELFIE_LIVENESS:
            selfie_ref = stored.get("center") or payload.get("selfie_ref", "")
            result = get_provider("liveness").check(selfie_ref=selfie_ref)
            evidence = selfie_ref
        elif key == K.ADDRESS_PROOF:
            result = ProviderResult.manual("Address proof submitted for review.")
            evidence = stored.get("document") or payload.get("document_ref", "")
        else:  # bank_penny_drop
            raise ValidationException(detail="Bank verification isn't available yet.")

        if result.ok:
            return VerificationService.set_reviewed_item(
                teacher,
                key,
                status=S.VERIFIED,
                evidence_ref=evidence,
                provider_ref=result.reference,
                notes=result.detail,
            )
        if result.needs_manual_review:
            item = VerificationService.set_reviewed_item(
                teacher,
                key,
                status=S.SUBMITTED,
                evidence_ref=evidence,
                provider_ref=result.reference,
                notes=result.detail,
            )
            review = TrustService.open_review_item(
                kind=ManualReviewKind.TEACHER_VERIFICATION,
                summary=f"{teacher.user.email}: '{K(key).label}' needs manual review",
                subject_user=teacher.user,
                payload={"key": key, "teacher_id": str(teacher.id)},
                dedupe_key=f"tv:{teacher.id}:{key}",
                priority=3,
            )
            TeacherVerificationItem.objects.filter(pk=item.pk).update(
                review_item=review
            )
            item.review_item = review
            return item
        return VerificationService.set_reviewed_item(
            teacher, key, status=S.REJECTED, notes=result.detail
        )

    # ----- the lead / search floor (queryset predicate) --------
    @staticmethod
    def floor_predicate_q(prefix: str = ""):
        """
        A ``Q`` over ``TeacherProfile`` (optionally via ``prefix``) matching
        the auto-floor: verified email + mobile and a completed basic
        profile. Subjects / availability are already enforced by the
        matching pipeline (subject filter + time-overlap eligibility).
        """
        from django.db.models import Q

        p = prefix
        return (
            Q(**{f"{p}teacher__user__is_email_verified": True})
            & Q(**{f"{p}teacher__user__is_mobile_verified": True})
            & Q(**{f"{p}teacher__experience_years__isnull": False})
            & Q(**{f"{p}teacher__bio__gt": ""})
            & Q(**{f"{p}teacher__qualification_level__gt": ""})
            & Q(**{f"{p}teacher__profile_photo__gt": ""})
        )
