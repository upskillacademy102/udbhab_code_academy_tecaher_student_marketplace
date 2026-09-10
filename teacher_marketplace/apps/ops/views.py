"""
Operations & audit API — Super Admin only.

    GET /api/v1/ops/events/     audit-log feed (filter + paginate)
    GET /api/v1/ops/overview/   platform KPIs + short time series
    GET /api/v1/ops/health/     database / cache / celery / migrations
    GET /api/v1/ops/errors/     tail of the error log (redacted)

Access is enforced centrally: none of these route names appear in
apps.accounts.api_permissions._RULES, so every non-superadmin role is
default-denied; superadmin is allowed by the is_allowed() short-circuit.
"""

import datetime as dt
import logging
import re

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import generics, serializers
from rest_framework.views import APIView

from apps.core.exceptions.custom_exceptions import (
    ResourceNotFoundException,
    ValidationException,
)
from apps.core.responses import APIResponse
from apps.ops.models import AuditLog
from apps.ops.serializers import (
    AccountSanctionSerializer,
    AuditLogSerializer,
    ReviewQueueItemSerializer,
)

logger = logging.getLogger("apps.ops")

_TOKEN_LIKE = re.compile(r"\b(eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)\b")


@extend_schema(tags=["Operations"])
class AuditEventListView(generics.ListAPIView):
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor")
        p = self.request.query_params
        if p.get("category"):
            qs = qs.filter(category=p["category"])
        if p.get("action"):
            qs = qs.filter(action=p["action"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("actor"):
            qs = qs.filter(actor_email__icontains=p["actor"])
        if p.get("search"):
            s = p["search"]
            qs = qs.filter(message__icontains=s) | qs.filter(target_repr__icontains=s)
        if p.get("date_from"):
            qs = qs.filter(created_at__date__gte=p["date_from"])
        if p.get("date_to"):
            qs = qs.filter(created_at__date__lte=p["date_to"])
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            data = self.get_serializer(page, many=True).data
            return APIResponse.paginated(
                data=data,
                pagination_meta={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                },
            )
        return APIResponse.success(data=self.get_serializer(qs, many=True).data)


@extend_schema(
    tags=["Operations"],
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Platform KPIs + short time series.",
        )
    },
)
class OpsOverviewView(APIView):
    def get(self, request):
        from apps.accounts.models import AdminLoginRequest, User, UserRole

        now = timezone.now()
        since_7 = now - dt.timedelta(days=7)
        since_30 = now - dt.timedelta(days=30)

        users = User.objects.all()
        by_role = {r.value: users.filter(role=r.value).count() for r in UserRole}

        data = {
            "generated_at": now.isoformat(),
            "users": {
                "total": users.count(),
                "active": users.filter(is_active=True).count(),
                "inactive": users.filter(is_active=False).count(),
                "by_role": by_role,
                "new_7d": users.filter(created_at__gte=since_7).count(),
                "new_30d": users.filter(created_at__gte=since_30).count(),
            },
            "pending_admin_logins": AdminLoginRequest.objects.filter(
                status="pending", expires_at__gt=now
            ).count(),
            "security_events_7d": AuditLog.objects.filter(
                category__in=["security", "impersonation", "admin_login"],
                created_at__gte=since_7,
            ).count(),
        }

        # Optional domain KPIs — guarded so a missing table never 500s the page.
        try:
            from apps.lead_engine.models import Lead

            data["leads"] = {
                "total": Lead.objects.count(),
                "new_7d": Lead.objects.filter(created_at__gte=since_7).count(),
                "series_7d": _daily_series(Lead.objects, since_7, now),
            }
        except Exception:  # noqa: BLE001
            pass
        try:
            from django.db.models import Sum

            from apps.payments.models import Payment, PaymentStatus

            agg = Payment.objects.filter(status=PaymentStatus.SUCCESS).aggregate(
                t=Sum("amount")
            )
            data["revenue"] = {
                "total": str(agg["t"] or 0),
                "last_30d": str(
                    Payment.objects.filter(
                        status=PaymentStatus.SUCCESS, created_at__gte=since_30
                    ).aggregate(t=Sum("amount"))["t"]
                    or 0
                ),
            }
        except Exception:  # noqa: BLE001
            pass

        return APIResponse.success(data=data)


def _daily_series(manager, start, end):
    from django.db.models.functions import TruncDate

    rows = (
        manager.filter(created_at__gte=start, created_at__lte=end)
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .order_by("d")
    )
    counts = {}
    for r in rows:
        counts[r["d"].isoformat()] = counts.get(r["d"].isoformat(), 0) + 1
    out = []
    day = start.date()
    while day <= end.date():
        out.append({"date": day.isoformat(), "count": counts.get(day.isoformat(), 0)})
        day += dt.timedelta(days=1)
    return out


@extend_schema(
    tags=["Operations"],
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="database / cache / celery / migrations health.",
        )
    },
)
class OpsHealthView(APIView):
    def get(self, request):
        checks = {}

        # Database
        try:
            with connection.cursor() as c:
                c.execute("SELECT 1")
                c.fetchone()
            checks["database"] = {"status": "ok"}
        except Exception as e:  # noqa: BLE001
            checks["database"] = {"status": "down", "detail": str(e)[:120]}

        # Cache
        try:
            cache.set("ops:healthcheck", "1", 10)
            checks["cache"] = {
                "status": "ok" if cache.get("ops:healthcheck") == "1" else "degraded"
            }
        except Exception as e:  # noqa: BLE001
            checks["cache"] = {"status": "down", "detail": str(e)[:120]}

        # Migrations
        try:
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes()
            pending = executor.migration_plan(targets)
            checks["migrations"] = {
                "status": "ok" if not pending else "pending",
                "unapplied": len(pending),
            }
        except Exception as e:  # noqa: BLE001
            checks["migrations"] = {"status": "unknown", "detail": str(e)[:120]}

        # Celery broker (best-effort, must NEVER block the health check).
        # celery_app.control.ping()'s `timeout` only bounds the *reply* wait -
        # not the broker connection, which retries for ~4s when the broker is
        # down. Pre-check raw TCP reachability with a short socket timeout so a
        # down broker fails fast instead of hanging this endpoint.
        checks["celery"] = self._celery_check()

        overall = "ok"
        for v in checks.values():
            if v["status"] == "down":
                overall = "down"
                break
            if v["status"] in ("degraded", "pending"):
                overall = "degraded"

        return APIResponse.success(
            data={
                "overall": overall,
                "checks": checks,
                "time": timezone.now().isoformat(),
            }
        )

    @staticmethod
    def _celery_check() -> dict:
        import socket
        from urllib.parse import urlparse

        broker = getattr(settings, "CELERY_BROKER_URL", "") or ""
        parsed = urlparse(broker)
        host = parsed.hostname or "localhost"
        default_port = 6379 if (parsed.scheme or "").startswith("redis") else 5672
        port = parsed.port or default_port

        try:
            # short timeout; `host` may resolve to both IPv6 + IPv4 loopback,
            # so create_connection can try each - keep the per-address wait tiny.
            with socket.create_connection((host, port), timeout=0.35):
                pass
        except OSError as e:  # broker unreachable - fail fast, do not hang
            return {
                "status": "unreachable",
                "detail": f"{host}:{port} {e.__class__.__name__}",
            }

        try:
            from config.celery import app as celery_app

            replies = celery_app.control.ping(timeout=0.75)
            return {
                "status": "ok" if replies else "no-workers",
                "workers": len(replies or []),
            }
        except Exception as e:  # noqa: BLE001
            return {"status": "unknown", "detail": str(e)[:120]}


@extend_schema(
    tags=["Operations"],
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT, description="Redacted tail of the error log."
        )
    },
)
class OpsErrorsView(APIView):
    def get(self, request):
        try:
            limit = min(int(request.query_params.get("limit", 60)), 300)
        except (TypeError, ValueError):
            limit = 60

        path = settings.BASE_DIR / "logs" / "error.log"
        lines = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()[-limit:]
        except FileNotFoundError:
            lines = []
        except Exception as e:  # noqa: BLE001
            return APIResponse.success(
                data={"available": False, "detail": str(e)[:120], "lines": []}
            )

        redacted = [
            _TOKEN_LIKE.sub("[redacted-token]", ln.rstrip("\n")) for ln in lines
        ]
        return APIResponse.success(
            data={"available": True, "count": len(redacted), "lines": redacted}
        )


# ==========================================================
# REVIEW QUEUE (Phase 9c) - the single place ops works every
# fraud / verification / dispute / anomaly signal.
# ==========================================================
@extend_schema(tags=["Operations"])
class ReviewQueueListView(generics.ListAPIView):
    serializer_class = ReviewQueueItemSerializer

    def get_queryset(self):
        from apps.trust.models import ManualReviewItem

        qs = ManualReviewItem.objects.select_related(
            "subject_user", "subject_user__trust_profile", "assignee"
        )
        p = self.request.query_params
        if p.get("kind"):
            qs = qs.filter(kind=p["kind"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        else:
            qs = qs.filter(status__in=["open", "in_review"])
        if p.get("priority"):
            qs = qs.filter(priority=p["priority"])
        if p.get("assignee") == "me":
            qs = qs.filter(assignee=self.request.user)
        if p.get("search"):
            qs = qs.filter(summary__icontains=p["search"])
        return qs

    def list(self, request, *args, **kwargs):
        from django.db.models import Count

        from apps.trust.models import ManualReviewItem

        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        by_kind = dict(
            ManualReviewItem.objects.filter(status__in=["open", "in_review"])
            .values_list("kind")
            .annotate(n=Count("id"))
        )
        meta = {"open_by_kind": by_kind}
        if page is not None:
            data = self.get_serializer(page, many=True).data
            return APIResponse.paginated(
                data=data,
                pagination_meta={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                    **meta,
                },
            )
        return APIResponse.success(
            data={"results": self.get_serializer(qs, many=True).data, **meta}
        )


def _get_review_item(item_id):
    from apps.trust.models import ManualReviewItem

    item = ManualReviewItem.objects.filter(id=item_id).first()
    if item is None:
        raise ResourceNotFoundException(detail="Review item not found.")
    return item


@extend_schema(
    tags=["Operations"],
    request=inline_serializer(
        name="ReviewQueueResolve",
        fields={
            "dismiss": serializers.BooleanField(required=False),
            "resolution": serializers.CharField(required=False, allow_blank=True),
        },
    ),
    responses={200: OpenApiResponse(description="Item resolved / dismissed.")},
)
class ReviewQueueResolveView(APIView):
    def post(self, request, id):
        from apps.ops.models import AuditCategory
        from apps.ops.services import AuditService
        from apps.trust.services.trust_service import TrustService

        item = _get_review_item(id)
        dismiss = bool(request.data.get("dismiss"))
        resolution = (request.data.get("resolution") or "").strip()[:2000]
        TrustService.resolve_review_item(
            item, by=request.user, resolution=resolution, dismiss=dismiss
        )
        AuditService.record(
            action="review_item_resolved",
            category=AuditCategory.OPS,
            request=request,
            target=item,
            message=f"{'Dismissed' if dismiss else 'Resolved'}: {item.kind}",
        )
        return APIResponse.success(
            data=ReviewQueueItemSerializer(item).data, message="Review item updated."
        )


@extend_schema(
    tags=["Operations"],
    request=inline_serializer(
        name="ReviewQueueAssign",
        fields={"unassign": serializers.BooleanField(required=False)},
    ),
    responses={200: OpenApiResponse(description="Item assignee updated.")},
)
class ReviewQueueAssignView(APIView):
    def post(self, request, id):
        from apps.trust.models import ManualReviewStatus

        item = _get_review_item(id)
        unassign = bool(request.data.get("unassign"))
        item.assignee = None if unassign else request.user
        if not unassign and item.status == ManualReviewStatus.OPEN:
            item.status = ManualReviewStatus.IN_REVIEW
        item.save(update_fields=["assignee", "status", "updated_at"])
        return APIResponse.success(
            data=ReviewQueueItemSerializer(item).data,
            message="Unassigned." if unassign else "Assigned to you.",
        )


# ==========================================================
# FAKE-LEAD REPORTS + ACCOUNT SANCTIONS (Super Admin)
# ==========================================================
@extend_schema(
    tags=["Operations"],
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Students with fake-lead reports + their ban status.",
        )
    },
)
class OpsFakeLeadReportsView(APIView):
    """
    Feed for the Super Admin dashboard's fake-lead panel: every student
    with an open FAKE_LEAD_REPORT review item, its running distinct-teacher
    counts, and whether the account is currently active / sanctioned.
    """

    def get(self, request):
        from apps.trust.models import (
            AccountSanction,
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
            )
            .select_related("subject_user")
            .order_by("priority", "-updated_at")[:limit]
        )
        sanctions = {
            s.user_id: s
            for s in AccountSanction.objects.filter(
                active=True,
                user_id__in=[it.subject_user_id for it in items if it.subject_user_id],
            )
        }

        results = []
        for it in items:
            p = it.payload or {}
            user = it.subject_user
            sanction = sanctions.get(it.subject_user_id)
            results.append(
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
                    "auto_banned": bool(p.get("auto_banned")),
                    "sanction": (
                        {
                            "id": str(sanction.id),
                            "kind": sanction.kind,
                            "source": sanction.source,
                            "is_automatic": sanction.is_automatic,
                            "reason": sanction.reason,
                            "at": sanction.created_at.isoformat(),
                        }
                        if sanction
                        else None
                    ),
                    "priority": it.priority,
                    "updated_at": it.updated_at.isoformat(),
                }
            )
        return APIResponse.success(
            data={"results": results, "count": len(results)}
        )


@extend_schema(tags=["Operations"])
class OpsSanctionListCreateView(generics.ListAPIView):
    serializer_class = AccountSanctionSerializer

    def get_queryset(self):
        from apps.trust.models import AccountSanction

        qs = AccountSanction.objects.select_related(
            "user", "created_by", "lifted_by"
        )
        p = self.request.query_params
        if p.get("active") in ("true", "false"):
            qs = qs.filter(active=p["active"] == "true")
        if p.get("user"):
            qs = qs.filter(user_id=p["user"])
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            return APIResponse.paginated(
                data=self.get_serializer(page, many=True).data,
                pagination_meta={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                },
            )
        return APIResponse.success(data=self.get_serializer(qs, many=True).data)

    @extend_schema(
        request=inline_serializer(
            name="OpsSanctionCreate",
            fields={
                "user_id": serializers.UUIDField(),
                "kind": serializers.ChoiceField(choices=["ban", "suspend"]),
                "reason": serializers.CharField(required=False, allow_blank=True),
                "review_item_id": serializers.UUIDField(required=False),
            },
        ),
        responses={201: AccountSanctionSerializer},
    )
    def post(self, request):
        from apps.accounts.models import User
        from apps.ops.models import AuditCategory
        from apps.ops.services import AuditService
        from apps.trust.models import AccountSanctionKind, ManualReviewItem
        from apps.trust.services.sanction_service import SanctionService

        user_id = request.data.get("user_id")
        kind = (request.data.get("kind") or "ban").strip()
        reason = (request.data.get("reason") or "").strip()
        if kind not in (AccountSanctionKind.BAN, AccountSanctionKind.SUSPEND):
            raise ValidationException(detail="kind must be 'ban' or 'suspend'.")

        target = User.all_objects.filter(id=user_id).first() if user_id else None
        if target is None:
            raise ResourceNotFoundException(detail="User not found.")
        if target.id == request.user.id:
            raise ValidationException(detail="You can't sanction your own account.")

        review_item = None
        if request.data.get("review_item_id"):
            review_item = ManualReviewItem.objects.filter(
                id=request.data["review_item_id"]
            ).first()

        sanction = SanctionService.apply(
            target,
            kind=kind,
            reason=reason,
            by=request.user,
            review_item=review_item,
            audit_request=request,
        )
        AuditService.record(
            request=request,
            category=AuditCategory.USER,
            action="ops.account_sanctioned",
            target=target,
            message=f"{kind} {target.email}",
        )
        return APIResponse.created(
            data=AccountSanctionSerializer(sanction).data,
            message=f"{target.email} has been {'banned' if kind == 'ban' else 'suspended'}.",
        )


@extend_schema(
    tags=["Operations"],
    request=inline_serializer(
        name="OpsSanctionLift",
        fields={"reason": serializers.CharField(required=False, allow_blank=True)},
    ),
    responses={200: AccountSanctionSerializer},
)
class OpsSanctionLiftView(APIView):
    def post(self, request, id):
        from apps.trust.models import AccountSanction
        from apps.trust.services.sanction_service import SanctionService

        sanction = AccountSanction.objects.filter(id=id).first()
        if sanction is None:
            raise ResourceNotFoundException(detail="Sanction not found.")
        if not sanction.active:
            raise ValidationException(detail="This sanction has already been lifted.")

        SanctionService.lift(
            sanction,
            by=request.user,
            reason=(request.data.get("reason") or "").strip(),
            audit_request=request,
        )
        sanction.refresh_from_db()
        return APIResponse.success(
            data=AccountSanctionSerializer(sanction).data,
            message=f"{sanction.user.email} has been reactivated.",
        )


@extend_schema(
    tags=["Operations"],
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT, description="Users by risk state."
        )
    },
)
class OpsRiskView(APIView):
    def get(self, request):
        from django.db.models import Count

        from apps.trust.models import RiskState, TrustProfile

        state = request.query_params.get("state")
        qs = TrustProfile.objects.select_related("user").exclude(
            risk_state=RiskState.NORMAL
        )
        if state:
            qs = qs.filter(risk_state=state)
        qs = qs.order_by("-risk_score")[:200]
        counts = dict(
            TrustProfile.objects.exclude(risk_state=RiskState.NORMAL)
            .values_list("risk_state")
            .annotate(n=Count("id"))
        )
        return APIResponse.success(
            data={
                "counts": counts,
                "results": [
                    {
                        "user_id": str(tp.user_id),
                        "email": tp.user.email,
                        "role": tp.user.role,
                        "risk_score": tp.risk_score,
                        "risk_state": tp.risk_state,
                        "recomputed_at": tp.risk_recomputed_at,
                    }
                    for tp in qs
                ],
            }
        )
