"""
Learning Partner dashboard API.

  GET /api/v1/lp/dashboard/               overview: org name + counts
  GET /api/v1/lp/students/                students who picked this partner
  GET /api/v1/lp/students/{id}/           detail (own students only)
  GET /api/v1/lp/teachers/                teachers who picked this partner
  GET /api/v1/lp/teachers/{id}/           detail (own teachers only)
  GET /api/v1/lp/taxonomy-requests/       this partner's own subject/language requests
  POST /api/v1/lp/taxonomy-requests/      submit a new one (reviewed by Super Admin)
  GET  /api/v1/lp/fake-lead-reports/      own students with an open fake-lead review item
  POST /api/v1/lp/fake-lead-reports/{student_id}/endorse/
                                           endorse an EXISTING report - cannot originate one
  GET  /api/v1/lp/students-lead-quality/  own students, aggregated genuine/unreachable/fake
                                           (?student_id= for that student's individual ratings)
  GET  /api/v1/lp/teacher-lead-reviews/   lead-quality ratings on own students, by teacher
  GET  /api/v1/lp/audit/                  audit rows targeting this partner's own referred users

Every view is scoped by `.filter(learning_partner=request.user)` (or the
equivalent single-row lookup) - a Learning Partner can never see another
partner's people, or the platform's full user base, by construction: there
is no query path here that doesn't include that filter.

Route names (lp:dashboard, lp:student-list, ...) are granted to `_ADMIN` in
apps.accounts.api_permissions - that only lets ANY admin past the central
role gate. The real "is this specifically a Learning Partner admin, not a
plain one" check is LearningPartnerAPIView.initial() below, which runs
after (not instead of) that central gate, so nothing here can accidentally
bypass the app-wide permission registry.
"""

from __future__ import annotations

from django.db.models import Q
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.accounts.admin_api import (
    AdminUserSerializer,
    LearningPartnerTaxonomyRequestSerializer,
)
from apps.accounts.models import User, UserRole
from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.trust.models import LearningPartnerTaxonomyRequest, TaxonomyRequestStatus


class LearningPartnerAPIView(APIView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.is_learning_partner_admin:
            raise PermissionDenied("This area is for Learning Partner accounts only.")


class _Pagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class LPDashboardView(LearningPartnerAPIView):
    def get(self, request):
        me = request.user
        referred = User.objects.filter(learning_partner=me)
        return APIResponse.success(
            data={
                "organization_name": me.first_name,
                "students_count": referred.filter(role=UserRole.STUDENT).count(),
                "teachers_count": referred.filter(role=UserRole.TEACHER).count(),
            }
        )


class _ReferredUserListView(LearningPartnerAPIView):
    role: str

    def get(self, request):
        qs = User.objects.filter(
            role=self.role, learning_partner=request.user
        ).order_by("-created_at")
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )
        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        data = AdminUserSerializer(page, many=True).data
        return APIResponse.paginated(
            data=data,
            pagination_meta={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
        )


class _ReferredUserDetailView(LearningPartnerAPIView):
    role: str

    def get(self, request, id):
        user = User.objects.filter(
            id=id, role=self.role, learning_partner=request.user
        ).first()
        if user is None:
            # Deliberately identical to "doesn't exist" - an LP must never
            # learn that a given id belongs to someone else's student/
            # teacher (or a platform user with no partner at all).
            raise ResourceNotFoundException(detail="Not found.")
        return APIResponse.success(data=AdminUserSerializer(user).data)


class LPStudentListView(_ReferredUserListView):
    role = UserRole.STUDENT


class LPStudentDetailView(_ReferredUserDetailView):
    role = UserRole.STUDENT


class LPTeacherListView(_ReferredUserListView):
    role = UserRole.TEACHER


class LPTeacherDetailView(_ReferredUserDetailView):
    role = UserRole.TEACHER


class LPTaxonomyRequestListCreateView(LearningPartnerAPIView):
    """
    A Learning Partner has no direct write access to Subject/Language
    (apps.accounts.api_permissions keeps those Super-Admin-only) - this is
    their only path to one that doesn't exist yet. Approving
    (apps.accounts.admin_api.TaxonomyRequestDecisionView) creates the real
    row scoped to `request.user` alone - never platform-wide.
    """

    def get(self, request):
        qs = LearningPartnerTaxonomyRequest.objects.filter(
            learning_partner=request.user
        ).order_by("-created_at")
        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return APIResponse.success(
            data=LearningPartnerTaxonomyRequestSerializer(qs, many=True).data
        )

    def post(self, request):
        serializer = LearningPartnerTaxonomyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kind = serializer.validated_data["kind"]
        name = serializer.validated_data["name"]

        already_pending = LearningPartnerTaxonomyRequest.objects.filter(
            learning_partner=request.user,
            kind=kind,
            name__iexact=name,
            status=TaxonomyRequestStatus.PENDING,
        ).exists()
        if already_pending:
            raise ValidationException(
                detail=f"You already have a pending request for '{name}'."
            )

        req = LearningPartnerTaxonomyRequest.objects.create(
            learning_partner=request.user,
            kind=kind,
            name=name,
            note=serializer.validated_data.get("note", ""),
        )
        return APIResponse.created(
            data=LearningPartnerTaxonomyRequestSerializer(req).data,
            message="Sent to the Super Admin for review.",
        )


def _sanction_payload(sanction):
    """Mirrors apps.ops.views._sanction_payload exactly - kept as its own
    tiny copy rather than importing a private helper from another app."""
    if sanction is None:
        return None
    return {
        "id": str(sanction.id),
        "kind": sanction.kind,
        "source": sanction.source,
        "is_automatic": sanction.is_automatic,
        "reason": sanction.reason,
        "at": sanction.created_at.isoformat(),
    }


class LPFakeLeadReportsView(LearningPartnerAPIView):
    """
    Mirrors apps.ops.views.OpsFakeLeadReportsView exactly, scoped to
    students who identified THIS partner at signup - a Learning Partner
    never sees another partner's (or the platform's full) fake-lead queue.
    Each row also says whether this partner has already endorsed it, so the
    frontend can disable the Endorse button once used (one endorsement per
    partner per student, enforced at the DB level too).
    """

    def get(self, request):
        from apps.trust.models import (
            AccountSanction,
            FakeLeadEndorsement,
            ManualReviewItem,
            ManualReviewKind,
            ManualReviewStatus,
        )

        try:
            limit = min(int(request.query_params.get("limit", 25)), 100)
        except (TypeError, ValueError):
            limit = 25

        items = (
            ManualReviewItem.objects.filter(
                kind=ManualReviewKind.FAKE_LEAD_REPORT,
                status__in=[ManualReviewStatus.OPEN, ManualReviewStatus.IN_REVIEW],
                subject_user__learning_partner=request.user,
            )
            .select_related("subject_user")
            .order_by("priority", "-updated_at")[:limit]
        )
        student_ids = [it.subject_user_id for it in items if it.subject_user_id]
        sanctions = {
            s.user_id: s
            for s in AccountSanction.objects.filter(active=True, user_id__in=student_ids)
        }
        endorsed_ids = set(
            FakeLeadEndorsement.objects.filter(
                learning_partner=request.user, student_id__in=student_ids
            ).values_list("student_id", flat=True)
        )

        results = []
        for it in items:
            p = it.payload or {}
            user = it.subject_user
            sanction = sanctions.get(it.subject_user_id)
            results.append(
                {
                    "review_item_id": str(it.id),
                    "student_id": str(it.subject_user_id) if user else None,
                    "student_email": p.get("student_email") or (user.email if user else ""),
                    "student_name": p.get("student_name")
                    or (user.get_full_name() if user else ""),
                    "account_active": user.is_active if user else None,
                    "distinct_teachers_7d": p.get("distinct_teachers_7d", 0),
                    "distinct_teachers_30d": p.get("distinct_teachers_30d", 0),
                    "distinct_teachers_all": p.get("distinct_teachers_all", 0),
                    "total_reports": p.get("total_reports", 0),
                    "latest_report": p.get("latest_report"),
                    "auto_banned": bool(p.get("auto_banned")),
                    "sanction": _sanction_payload(sanction),
                    "priority": it.priority,
                    "updated_at": it.updated_at.isoformat(),
                    "already_endorsed": it.subject_user_id in endorsed_ids,
                }
            )
        return APIResponse.success(data={"results": results, "count": len(results)})


class LPEndorseFakeReportView(LearningPartnerAPIView):
    """
    Endorse an EXISTING fake-lead report on one of this partner's own
    students - a Learning Partner can never originate one from nothing
    (there must already be an open FAKE_LEAD_REPORT review item, which only
    a real teacher's "fake" rating can create). One endorsement per
    (student, partner) - the unique constraint on FakeLeadEndorsement is
    the hard backstop; the get_or_create below just turns a would-be
    IntegrityError into a clean 400.
    """

    def post(self, request, student_id):
        from apps.trust.models import (
            FakeLeadEndorsement,
            ManualReviewItem,
            ManualReviewKind,
            ManualReviewStatus,
        )
        from apps.trust.services.lead_quality_service import LeadQualityService

        student = User.objects.filter(
            id=student_id, role=UserRole.STUDENT, learning_partner=request.user
        ).first()
        if student is None:
            raise ResourceNotFoundException(detail="Not found.")

        has_open_report = ManualReviewItem.objects.filter(
            kind=ManualReviewKind.FAKE_LEAD_REPORT,
            subject_user=student,
            status__in=[ManualReviewStatus.OPEN, ManualReviewStatus.IN_REVIEW],
        ).exists()
        if not has_open_report:
            raise ValidationException(
                detail="This student has no open fake-lead report to endorse."
            )

        if FakeLeadEndorsement.objects.filter(
            student=student, learning_partner=request.user
        ).exists():
            raise ValidationException(
                detail="You've already endorsed this student's fake-lead report."
            )

        note = (request.data.get("note") or "")[:500]
        FakeLeadEndorsement.objects.create(
            student=student, learning_partner=request.user, note=note
        )
        LeadQualityService.reassess_fake_reports_after_endorsement(student)

        from apps.ops.models import AuditCategory
        from apps.ops.services import AuditService

        AuditService.record(
            request=request,
            category=AuditCategory.OPS,
            action="lp.fake_lead_endorsed",
            target=student,
            message=f"{request.user.first_name} endorsed the fake-lead report on {student.email}",
        )
        return APIResponse.created(
            data={"student_id": str(student.id)},
            message="Endorsement recorded.",
        )


class LPStudentLeadQualityView(LearningPartnerAPIView):
    """
    Mirrors apps.ops.views.OpsStudentLeadQualityView, scoped to this
    partner's own referred students (never another partner's, never a
    platform user with no partner) - see that view's docstring.
    """

    def get(self, request):
        from django.db.models import Count

        from apps.trust.models import AccountSanction, LeadQualityRating, LeadQualityVerdict

        student_id = request.query_params.get("student_id")

        if student_id:
            student = User.objects.filter(
                id=student_id, role=UserRole.STUDENT, learning_partner=request.user
            ).first()
            if student is None:
                raise ResourceNotFoundException(detail="Not found.")
            ratings = (
                LeadQualityRating.objects.filter(student=student)
                .select_related("teacher__user", "lead")
                .order_by("-created_at")[:200]
            )
            return APIResponse.success(
                data={
                    "results": [
                        {
                            "id": str(r.id),
                            "lead_id": str(r.lead_id),
                            "teacher_id": str(r.teacher_id),
                            "teacher_name": r.teacher.user.get_full_name(),
                            "teacher_email": r.teacher.user.email,
                            "verdict": r.verdict,
                            "note": r.note,
                            "clawed_back": r.clawed_back,
                            "created_at": r.created_at.isoformat(),
                        }
                        for r in ratings
                    ],
                    "count": len(ratings),
                }
            )

        rows = list(
            LeadQualityRating.objects.filter(student__learning_partner=request.user)
            .values("student_id")
            .annotate(
                total=Count("id"),
                genuine=Count("id", filter=Q(verdict=LeadQualityVerdict.GENUINE)),
                unreachable=Count("id", filter=Q(verdict=LeadQualityVerdict.UNREACHABLE)),
                fake=Count("id", filter=Q(verdict=LeadQualityVerdict.FAKE)),
            )
            .order_by("-fake", "-total")[:200]
        )
        student_ids = [row["student_id"] for row in rows]
        students = {u.id: u for u in User.objects.filter(id__in=student_ids)}
        sanctions = {
            s.user_id: s
            for s in AccountSanction.objects.filter(active=True, user_id__in=student_ids)
        }

        results = []
        for row in rows:
            user = students.get(row["student_id"])
            results.append(
                {
                    "student_id": str(row["student_id"]),
                    "student_email": user.email if user else "",
                    "student_name": user.get_full_name() if user else "",
                    "account_active": user.is_active if user else None,
                    "total_ratings": row["total"],
                    "genuine": row["genuine"],
                    "unreachable": row["unreachable"],
                    "fake": row["fake"],
                    "sanction": _sanction_payload(sanctions.get(row["student_id"])),
                }
            )
        return APIResponse.success(data={"results": results, "count": len(results)})


class LPTeacherLeadReviewsView(LearningPartnerAPIView):
    """
    Mirrors apps.ops.views.OpsTeacherLeadReviewsView, but scoped by STUDENT
    (student__learning_partner=request.user) rather than by teacher - every
    screen in this app is "about my own referred students", and a rating
    here is fundamentally about one of those students' leads, whichever
    (possibly unrelated-to-this-partner) teacher happened to unlock it.
    """

    def get(self, request):
        from apps.matching.models import LeadAssignment
        from apps.trust.models import LeadQualityRating

        p = request.query_params
        qs = LeadQualityRating.objects.filter(
            student__learning_partner=request.user
        ).select_related("teacher__user", "student", "lead").order_by("-created_at")
        if p.get("teacher_id"):
            qs = qs.filter(teacher_id=p["teacher_id"])
        if p.get("verdict"):
            qs = qs.filter(verdict=p["verdict"])
        ratings = list(qs[:200])

        lead_ids = [r.lead_id for r in ratings]
        teacher_ids = [r.teacher_id for r in ratings]
        is_direct_by_pair = {
            (a.lead_id, a.teacher_id): a.is_direct
            for a in LeadAssignment.objects.filter(
                lead_id__in=lead_ids, teacher_id__in=teacher_ids
            )
        }

        results = [
            {
                "id": str(r.id),
                "teacher_id": str(r.teacher_id),
                "teacher_name": r.teacher.user.get_full_name(),
                "teacher_email": r.teacher.user.email,
                "student_id": str(r.student_id),
                "student_name": r.student.get_full_name(),
                "lead_id": str(r.lead_id),
                "verdict": r.verdict,
                "note": r.note,
                "is_direct_offer": is_direct_by_pair.get((r.lead_id, r.teacher_id), False),
                "created_at": r.created_at.isoformat(),
            }
            for r in ratings
        ]
        return APIResponse.success(data={"results": results, "count": len(results)})


class LPAuditView(LearningPartnerAPIView):
    """
    Audit rows whose target is one of this partner's own referred students/
    teachers - e.g. a ban/sanction, a report, a taxonomy approval. AuditLog.
    target_id is a plain stringified id (not an FK), so the scoping is an
    explicit id list rather than a join.
    """

    def get(self, request):
        from apps.ops.models import AuditLog
        from apps.ops.serializers import AuditLogSerializer

        referred_ids = [
            str(u_id)
            for u_id in User.objects.filter(learning_partner=request.user).values_list(
                "id", flat=True
            )
        ]
        qs = AuditLog.objects.filter(target_id__in=referred_ids).order_by("-created_at")

        p = request.query_params
        if p.get("category"):
            qs = qs.filter(category=p["category"])
        if p.get("action"):
            qs = qs.filter(action=p["action"])

        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        data = AuditLogSerializer(page, many=True).data
        return APIResponse.paginated(
            data=data,
            pagination_meta={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
        )
