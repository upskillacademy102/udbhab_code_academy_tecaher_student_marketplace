"""
Views for the analytics app.

Endpoint (wired up in apps/analytics/urls.py, next file):
    GET /api/v1/dashboard/           -> DashboardView (role-aware:
                                        returns Admin Dashboard data
                                        for Admin/SuperAdmin, Teacher
                                        Dashboard data for Teacher)

Design note: the spec lists ONE endpoint (/api/v1/dashboard/) but
TWO distinct metric sets (Admin Dashboard vs Teacher Dashboard). A
single role-aware view - branching on request.user.role internally
- matches the spec's literal one-endpoint design more closely than
inventing two separate URLs the spec doesn't list. This app has no
models of its own; every metric here is a read-only aggregation
against models owned by other apps.
"""

import logging

from django.db.models import Sum
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.views import APIView

from apps.accounts.models import User, UserRole
from apps.core.exceptions.custom_exceptions import ResourceNotFoundException
from apps.core.responses import APIResponse
from apps.lead_engine.models import Lead
from apps.payments.models import Payment, PaymentStatus, PaymentType
from apps.subscriptions.services import LeadQuotaService, SubscriptionService
from apps.wallet.models import WalletTransaction
from apps.wallet.services import WalletService

logger = logging.getLogger("apps.analytics")


def _get_teacher_or_raise(request):
    teacher = getattr(request.user, "teacher_profile", None)
    if teacher is None:
        raise ResourceNotFoundException(
            detail=(
                "You must create your basic Teacher profile first "
                "(POST /api/v1/teachers/me/) before viewing the dashboard."
            )
        )
    return teacher


def _fake_lead_alerts(limit=8):
    """
    Recent students with an open fake-lead report, for the Super Admin
    dashboard panel. Same shape as GET /api/v1/ops/fake-lead-reports/, kept
    short here since the dashboard shows a preview and links to the queue.
    """
    from apps.trust.models import (
        AccountSanction,
        ManualReviewItem,
        ManualReviewKind,
        ManualReviewStatus,
    )

    items = list(
        ManualReviewItem.objects.filter(
            kind=ManualReviewKind.FAKE_LEAD_REPORT,
            status__in=[ManualReviewStatus.OPEN, ManualReviewStatus.IN_REVIEW],
        )
        .select_related("subject_user")
        .order_by("priority", "-updated_at")[:limit]
    )
    active_sanctions = {
        s.user_id
        for s in AccountSanction.objects.filter(
            active=True,
            user_id__in=[it.subject_user_id for it in items if it.subject_user_id],
        )
    }
    out = []
    for it in items:
        p = it.payload or {}
        user = it.subject_user
        out.append(
            {
                "review_item_id": str(it.id),
                "student_id": str(it.subject_user_id) if user else None,
                "student_email": p.get("student_email")
                or (user.email if user else ""),
                "student_name": p.get("student_name")
                or (user.get_full_name() if user else ""),
                "account_active": user.is_active if user else None,
                "distinct_teachers_7d": p.get("distinct_teachers_7d", 0),
                "distinct_teachers_30d": p.get("distinct_teachers_30d", 0),
                "distinct_teachers_all": p.get("distinct_teachers_all", 0),
                "total_reports": p.get("total_reports", 0),
                "latest_report": p.get("latest_report"),
                "auto_banned": bool(p.get("auto_banned"))
                or it.subject_user_id in active_sanctions,
                "priority": it.priority,
            }
        )
    return out


@extend_schema(
    tags=["Analytics"],
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Role-appropriate dashboard metrics (teacher vs admin/super-admin).",
        )
    },
)
class DashboardView(APIView):
    """
    GET: Returns role-appropriate dashboard metrics.
        - Admin/SuperAdmin -> platform-wide Admin Dashboard metrics.
        - Teacher -> personal Teacher Dashboard metrics.
        - Student -> not applicable (the spec defines no Student
          dashboard). Blocked centrally by RoleBasedAPIPermission
          (route ``analytics:dashboard`` grants only teacher/admin/
          superadmin); the in-method check below is defence in depth.
    """

    @extend_schema(tags=["Analytics"], summary="Get role-appropriate dashboard metrics")
    def get(self, request):
        if request.user.is_admin_role or request.user.is_superadmin_role:
            return self._admin_dashboard(request)
        if request.user.is_teacher:
            return self._teacher_dashboard(request)

        from apps.core.exceptions.custom_exceptions import PermissionDeniedException

        raise PermissionDeniedException(
            detail="No dashboard is available for Student accounts."
        )

    # ------------------------------------------------------------
    # ADMIN DASHBOARD
    # ------------------------------------------------------------
    def _admin_dashboard(self, request):
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

        total_students = User.objects.filter(
            role=UserRole.STUDENT, is_active=True
        ).count()
        total_teachers = User.objects.filter(
            role=UserRole.TEACHER, is_active=True
        ).count()

        premium_teachers = (
            User.objects.filter(role=UserRole.TEACHER, is_active=True)
            .filter(
                teacher_profile__subscriptions__status="active",
            )
            .exclude(teacher_profile__subscriptions__plan__name__iexact="Free")
            .distinct()
            .count()
        )

        successful = Payment.objects.filter(status=PaymentStatus.SUCCESS)
        total_revenue = successful.aggregate(total=Sum("amount"))["total"] or 0

        # Split the two revenue lines: recurring plan revenue is the business,
        # top-up packs are overflow. A top-up line growing faster than the
        # subscription line means the upgrade fence is priced wrong.
        subscription_revenue = (
            successful.filter(payment_type=PaymentType.SUBSCRIPTION).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )
        topup_revenue = (
            successful.filter(payment_type=PaymentType.TOKEN_PURCHASE).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

        # Learning Partner commission split (apps.commissions) - how much
        # of total_revenue the business actually kept vs. what's owed/paid
        # to partners. business_revenue + partner_commission_total should
        # equal total_revenue for every payment that has a Commission row
        # (older rows created before this app existed won't).
        from apps.commissions.models import (
            Commission,
            CommissionStatus,
            LearningPartnerWallet,
        )

        active_commissions = Commission.objects.filter(status=CommissionStatus.ACTIVE)
        business_revenue = (
            active_commissions.aggregate(total=Sum("business_share"))["total"] or 0
        )
        partner_commission_total = (
            active_commissions.aggregate(total=Sum("partner_share"))["total"] or 0
        )
        partner_commission_pending_payout = (
            LearningPartnerWallet.objects.aggregate(total=Sum("balance"))["total"] or 0
        )

        todays_payments = Payment.objects.filter(
            status=PaymentStatus.SUCCESS, created_at__gte=today_start
        ).count()

        todays_leads = Lead.objects.filter(created_at__gte=today_start).count()

        unlocked_leads = Lead.objects.filter(contact_unlocked=True).count()

        wallet_transactions_today = WalletTransaction.objects.filter(
            created_at__gte=today_start
        ).count()

        data = {
            "total_students": total_students,
            "total_teachers": total_teachers,
            "premium_teachers": premium_teachers,
            "revenue": str(total_revenue),
            "subscription_revenue": str(subscription_revenue),
            "topup_revenue": str(topup_revenue),
            "business_revenue": str(business_revenue),
            "partner_commission_total": str(partner_commission_total),
            "partner_commission_pending_payout": str(partner_commission_pending_payout),
            "todays_payments": todays_payments,
            "todays_leads": todays_leads,
            "unlocked_leads": unlocked_leads,
            "wallet_transactions_today": wallet_transactions_today,
        }

        # Super Admin gets the fake-lead alert feed inline so it lands on the
        # dashboard, not just the review queue. Admins don't (the ban/suspend
        # actions it drives are Super Admin only).
        if request.user.is_superadmin_role:
            data["fake_lead_alerts"] = _fake_lead_alerts()

        logger.info("Admin dashboard viewed by %s", request.user.email)

        return APIResponse.success(data=data)

    # ------------------------------------------------------------
    # TEACHER DASHBOARD
    # ------------------------------------------------------------
    def _teacher_dashboard(self, request):
        teacher = _get_teacher_or_raise(request)
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # "Extra unlocks" to the teacher - the never-expiring purchased
        # balance, distinct from the plan allowance that resets each cycle.
        wallet_balance = WalletService.get_balance(teacher)

        quota = LeadQuotaService.get_or_create_current_quota(teacher)
        free_leads_remaining = quota.remaining_free_leads

        marketplace_profile = getattr(teacher, "marketplace_profile", None)
        pending_rating_count = 0
        if marketplace_profile is not None:
            todays_leads = Lead.objects.filter(
                teacher_profile=marketplace_profile, created_at__gte=today_start
            ).count()
            unlocked_leads = Lead.objects.filter(
                teacher_profile=marketplace_profile, contact_unlocked=True
            ).count()
            from apps.trust.models import LeadQualityRating

            rated_ids = LeadQualityRating.objects.filter(teacher=teacher).values_list(
                "lead_id", flat=True
            )
            pending_rating_count = (
                Lead.objects.filter(
                    teacher_profile=marketplace_profile, contact_unlocked=True
                )
                .exclude(id__in=rated_ids)
                .count()
            )
        else:
            todays_leads = 0
            unlocked_leads = 0

        active_subscription = SubscriptionService.get_active_subscription(teacher)
        if active_subscription is not None and active_subscription.is_active_now:
            subscription_status = {
                "plan_name": active_subscription.plan.name,
                "status": active_subscription.status,
                "end_date": active_subscription.end_date,
            }
        else:
            subscription_status = {
                "plan_name": "Free",
                "status": "active",
                "end_date": None,
            }

        data = {
            "wallet_balance": wallet_balance,
            "extra_unlocks": wallet_balance,
            "free_leads_remaining": free_leads_remaining,
            "allowance_total": quota.total_free_leads,
            "allowance_used": quota.used_free_leads,
            "allowance_resets_in_days": quota.days_until_reset,
            "allowance_resets_at": quota.period_end,
            "todays_leads": todays_leads,
            "unlocked_leads": unlocked_leads,
            "pending_rating_count": pending_rating_count,
            "subscription_status": subscription_status,
        }

        logger.info("Teacher dashboard viewed by %s", request.user.email)

        return APIResponse.success(data=data)
