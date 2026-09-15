"""
Frontend routes. `page(template, roles=..., title=...)` renders the shell;
the browser fetches data from /api/v1. superadmin is implicitly allowed on
every role_required() route (mirrors the API), and additionally gets the
/super-admin/ mirror of the admin pages.
"""

from django.urls import path

from apps.web import views
from apps.web.views import page, spa

S = ("student",)
T = ("teacher",)
A = ("admin",)
SA = ("superadmin",)

app_name = "web"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("login/", views.login_page, name="login"),
    path("register/", views.register_page, name="register"),
    path("login/staff/", views.staff_login_page, name="staff-login"),
    path("suspended/", views.suspended_page, name="suspended"),
    path("add-role/", views.add_role_page, name="add-role"),
    # ============ STUDENT ============
    # Stage B: the student home is the React Discover page. Every other
    # student route is still a Django template and moves across in stage C.
    path(
        "student/",
        spa(
            roles=S,
            title="Learn Something New",
            desc="Teachers who teach what you want, in your language, when you're free.",
        ),
        name="student-home",
    ),
    path(
        "student/teachers/",
        spa(
            roles=S,
            title="Find Verified Teachers",
            desc="Search verified teachers by subject, language, price and when you're free.",
        ),
        name="student-teachers",
    ),
    path(
        "student/teachers/<uuid:id>/",
        spa(roles=S, title="Teacher"),
        name="student-teacher-detail",
    ),
    path(
        "student/requirements/",
        spa(
            roles=S,
            title="Posted Requirements",
            desc="Post it once. Matching teachers get in touch with you.",
        ),
        name="student-requirements",
    ),
    path(
        "student/requirements/<uuid:id>/",
        spa(roles=S, title="Your request"),
        name="student-requirement-detail",
    ),
    path(
        "student/profile/",
        spa(
            roles=S,
            title="Your profile",
            desc="Helps us aim better. All of it is optional.",
        ),
        name="student-profile",
    ),
    path(
        "student/notifications/",
        spa(roles=S, title="Notifications"),
        name="student-notifications",
    ),
    path(
        "student/settings/",
        page("web/settings.html", roles=S, title="Settings"),
        name="student-settings",
    ),
    path(
        "student/connect-admin/",
        page(
            "web/connect_admin.html",
            roles=S,
            title="Report an Issue",
            desc="Report a bug, glitch, or issue - with screenshots or a call request.",
        ),
        name="student-connect-admin",
    ),
    # ============ TEACHER ============
    path(
        "teacher/",
        spa(
            roles=T,
            title="Your enquiries",
            desc="Monitor lead requests, unlocked contacts, and conversion status.",
        ),
        name="teacher-home",
    ),
    path(
        "teacher/leads/",
        spa(
            roles=T,
            title="Enquiries",
            desc="Students who want what you teach. Unlock one to see how to reach them.",
        ),
        name="teacher-leads",
    ),
    path(
        "teacher/leads/<uuid:id>/",
        spa(roles=T, title="Enquiry"),
        name="teacher-lead-detail",
    ),
    path(
        "teacher/assignments/",
        spa(
            roles=T,
            title="Offers",
            desc="First refusal on students who match you closely. They expire.",
        ),
        name="teacher-assignments",
    ),
    path(
        "teacher/wallet/",
        page(
            "web/teacher/wallet.html",
            roles=T,
            title="Wallet",
            desc="Your token balance and transaction history.",
        ),
        name="teacher-wallet",
    ),
    # Plan, top-ups and payment history were three nav items asking a teacher
    # to hold state across pages to answer one question. They are one page
    # now; the old three keep their route names so existing links and tests
    # still resolve, and the SPA redirects them to /teacher/plan/.
    path(
        "teacher/plan/",
        spa(
            roles=T,
            title="Plan & unlocks",
            desc="Where you are, what you could change, and what you've paid.",
        ),
        name="teacher-plan",
    ),
    path(
        "teacher/tokens/",
        spa(roles=T, title="Plan & unlocks"),
        name="teacher-tokens",
    ),
    path(
        "teacher/subscription/",
        spa(roles=T, title="Plan & unlocks"),
        name="teacher-subscription",
    ),
    path(
        "teacher/payments/",
        spa(roles=T, title="Plan & unlocks"),
        name="teacher-payments",
    ),
    # The legacy template is still reachable at ?legacy=1 because identity
    # verification (document + selfie upload) has not been ported yet.
    path(
        "teacher/profile/",
        views.teacher_profile,
        name="teacher-profile",
    ),
    path(
        "teacher/availability/",
        spa(
            roles=T,
            title="Your hours",
            desc="We only match you to students who are free when you are.",
        ),
        name="teacher-availability",
    ),
    path(
        "teacher/notifications/",
        spa(roles=T, title="Notifications"),
        name="teacher-notifications",
    ),
    path(
        "teacher/settings/",
        page("web/settings.html", roles=T, title="Settings"),
        name="teacher-settings",
    ),
    path(
        "teacher/connect-admin/",
        page(
            "web/connect_admin.html",
            roles=T,
            title="Report an Issue",
            desc="Report a bug, glitch, or issue - with screenshots or a call request.",
        ),
        name="teacher-connect-admin",
    ),
]


# ============ ADMIN + SUPER ADMIN (same templates, two prefixes) ============
def _admin_routes(prefix, roles, name_prefix):
    R = page  # alias
    common = {"roles": roles}
    return [
        path(
            f"{prefix}/",
            R("web/admin/dashboard.html", title="Platform Dashboard", **common),
            name=f"{name_prefix}-home",
        ),
        path(
            f"{prefix}/users/",
            R(
                "web/admin/users.html",
                title="Users",
                desc="Every account on the platform.",
                **common,
            ),
            name=f"{name_prefix}-users",
        ),
        path(
            f"{prefix}/students/",
            R(
                "web/admin/people.html",
                title="Students",
                desc="Search and review student accounts.",
                resource="students",
                **common,
            ),
            name=f"{name_prefix}-students",
        ),
        path(
            f"{prefix}/students/<uuid:id>/",
            R(
                "web/admin/person_detail.html",
                title="Student",
                resource="students",
                **common,
            ),
            name=f"{name_prefix}-student-detail",
        ),
        path(
            f"{prefix}/teachers/",
            R(
                "web/admin/people.html",
                title="Teachers",
                desc="Search and review teacher accounts.",
                resource="teachers",
                **common,
            ),
            name=f"{name_prefix}-teachers",
        ),
        path(
            f"{prefix}/teachers/<uuid:id>/",
            R(
                "web/admin/person_detail.html",
                title="Teacher",
                resource="teachers",
                **common,
            ),
            name=f"{name_prefix}-teacher-detail",
        ),
        path(
            f"{prefix}/onboarding-calls/",
            R(
                "web/admin/onboarding_calls.html",
                title="Onboarding Calls",
                desc="Teachers asking for an onboarding video call.",
                **common,
            ),
            name=f"{name_prefix}-onboarding-calls",
        ),
        path(
            f"{prefix}/support-tickets/",
            R(
                "web/admin/support_tickets.html",
                title="Bugs Reported",
                desc="Issues students and teachers have reported via Report an Issue.",
                **common,
            ),
            name=f"{name_prefix}-support-tickets",
        ),
        path(
            f"{prefix}/subjects/",
            R(
                "web/admin/resource.html",
                title="Subjects",
                resource="subjects",
                **common,
            ),
            name=f"{name_prefix}-subjects",
        ),
        path(
            f"{prefix}/languages/",
            R(
                "web/admin/resource.html",
                title="Languages",
                resource="languages",
                **common,
            ),
            name=f"{name_prefix}-languages",
        ),
        path(
            f"{prefix}/grade-levels/",
            R(
                "web/admin/resource.html",
                title="Grade Levels",
                resource="grade-levels",
                **common,
            ),
            name=f"{name_prefix}-grade-levels",
        ),
        path(
            f"{prefix}/locations/",
            R(
                "web/admin/locations.html",
                title="Locations",
                desc="Countries, states and cities used across the platform.",
                **common,
            ),
            name=f"{name_prefix}-locations",
        ),
        path(
            f"{prefix}/token-packages/",
            R(
                "web/admin/resource.html",
                title="Token Packages",
                resource="token-packages",
                **common,
            ),
            name=f"{name_prefix}-token-packages",
        ),
        path(
            f"{prefix}/plans/",
            R(
                "web/admin/resource.html",
                title="Subscription Plans",
                resource="plans",
                **common,
            ),
            name=f"{name_prefix}-plans",
        ),
        path(
            f"{prefix}/lead-pricing/",
            R(
                "web/admin/resource.html",
                title="Lead Unlock Pricing",
                resource="lead-pricing",
                **common,
            ),
            name=f"{name_prefix}-lead-pricing",
        ),
        path(
            f"{prefix}/matching/config/",
            R(
                "web/admin/resource.html",
                title="Matching Config",
                resource="matching-config",
                **common,
            ),
            name=f"{name_prefix}-matching-config",
        ),
        path(
            f"{prefix}/matching/subject-aliases/",
            R(
                "web/admin/resource.html",
                title="Subject Aliases",
                resource="subject-aliases",
                **common,
            ),
            name=f"{name_prefix}-subject-aliases",
        ),
        path(
            f"{prefix}/matching/language-aliases/",
            R(
                "web/admin/resource.html",
                title="Language Aliases",
                resource="language-aliases",
                **common,
            ),
            name=f"{name_prefix}-language-aliases",
        ),
        path(
            f"{prefix}/matching/pincodes/",
            R(
                "web/admin/resource.html",
                title="Pincode Locations",
                resource="pincodes",
                **common,
            ),
            name=f"{name_prefix}-pincodes",
        ),
        path(
            f"{prefix}/notifications/",
            R("web/notifications.html", title="Notifications", **common),
            name=f"{name_prefix}-notifications",
        ),
        path(
            f"{prefix}/settings/",
            R("web/settings.html", title="Settings", **common),
            name=f"{name_prefix}-settings",
        ),
    ]


urlpatterns += _admin_routes("admin-portal", A, "admin")
urlpatterns += _admin_routes("super-admin", SA, "super-admin")

urlpatterns += [
    path(
        "super-admin/oversight/",
        page(
            "web/superadmin/oversight.html",
            roles=SA,
            title="Operations",
            desc="Platform health, key metrics and recent errors.",
        ),
        name="super-admin-oversight",
    ),
    path(
        "super-admin/admin-requests/",
        page(
            "web/superadmin/admin_requests.html",
            roles=SA,
            title="Admin access requests",
            desc="Approve or deny pending administrator sign-ins.",
        ),
        name="super-admin-admin-requests",
    ),
    path(
        "super-admin/audit/",
        page(
            "web/superadmin/audit.html",
            roles=SA,
            title="Audit log",
            desc="Privileged and security-relevant actions across the platform.",
        ),
        name="super-admin-audit",
    ),
    path(
        "super-admin/review-queue/",
        page(
            "web/superadmin/review_queue.html",
            roles=SA,
            title="Review queue",
            desc="Every fraud, verification, dispute and anomaly signal in one place.",
        ),
        name="super-admin-review-queue",
    ),
]
