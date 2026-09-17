"""
Single source of truth for role-aware navigation.

`nav_for(role)` returns a list of sections; each section is
{"label": str|None, "items": [NavItem, ...]}.

NavItem keys:
    label   visible text
    url     target path (None when future=True)
    icon    icon id (see templates/web/_icons.html)
    match   path prefix used to compute the "active" state (defaults to url)
    future  True -> rendered disabled with a "Coming soon" hint (no API yet)

Only routes whose data is actually served by an existing API are real links;
everything the backend cannot support yet is marked future=True rather than
faked (per the build brief).
"""

# Hick's Law: decision time grows with the number of options, and the
# comfortable ceiling for a sidebar is around seven. Profile, Settings and
# Report an Issue moved into the account menu in the topbar — they are
# destinations you go to deliberately, not things you scan for.
_STUDENT = [
    {
        "label": None,
        "items": [
            {
                "label": "Learn Something New",
                "url": "/student/",
                "icon": "sparkles",
                "match": "/student/$",
            },
            {"label": "Find Verified Teachers", "url": "/student/teachers/", "icon": "search"},
            {
                "label": "Posted Requirements",
                "url": "/student/requirements/",
                "icon": "clipboard",
            },
            {
                "label": "Notifications",
                "url": "/student/notifications/",
                "icon": "bell",
                "badge": "notifications",
            },
        ],
    },
]

# Was twelve items across three groups. Subscription + Buy Tokens + Payments
# became one "Plan & unlocks" page; Settings and Report an Issue moved to the
# account menu; Wallet is already dropped while TOKEN_SYSTEM_ENABLED is off.
# Six, one group, no scrolling.
_TEACHER = [
    {
        "label": None,
        "items": [
            {
                "label": "Home",
                "url": "/teacher/",
                "icon": "home",
                "match": "/teacher/$",
            },
            {
                "label": "Leads",
                "url": "/teacher/leads/",
                "icon": "inbox",
                "badge": "leads",
            },
            {
                "label": "Offers",
                "url": "/teacher/assignments/",
                "icon": "target",
                "badge": "offers",
                "glow": True,
            },
            {
                "label": "Your hours",
                "url": "/teacher/availability/",
                "icon": "calendar",
            },
            {"label": "Your profile", "url": "/teacher/profile/", "icon": "user"},
            {
                "label": "Plan & unlocks",
                "url": "/teacher/plan/",
                "icon": "star",
                # Keep the old routes highlighting this item — they redirect
                # here. `match` is a plain prefix UNLESS it ends with "$",
                # which switches nav_active() to a regex fullmatch.
                "match": "/teacher/(plan|subscription|tokens|payments)/$",
            },
            {
                "label": "Notifications",
                "url": "/teacher/notifications/",
                "icon": "bell",
                "badge": "notifications",
            },
        ],
    },
]

_ADMIN_SECTIONS = [
    {
        "label": None,
        "items": [
            {
                "label": "Dashboard",
                "url": "/admin-portal/",
                "icon": "chart",
                "match": "/admin-portal/$",
            },
        ],
    },
    {
        "label": "People",
        "items": [
            {"label": "Users", "url": "/admin-portal/users/", "icon": "users"},
            {"label": "Students", "url": "/admin-portal/students/", "icon": "user"},
            {"label": "Teachers", "url": "/admin-portal/teachers/", "icon": "academic"},
            {
                "label": "Onboarding Calls",
                "url": "/admin-portal/onboarding-calls/",
                "icon": "video",
            },
            {
                "label": "Bugs Reported",
                "url": "/admin-portal/support-tickets/",
                "icon": "alert-triangle",
            },
        ],
    },
    {
        "label": "Reference Data",
        "items": [
            {"label": "Subjects", "url": "/admin-portal/subjects/", "icon": "book"},
            {"label": "Languages", "url": "/admin-portal/languages/", "icon": "globe"},
            {"label": "Grade Levels", "url": "/admin-portal/grade-levels/", "icon": "list"},
            {"label": "Locations", "url": "/admin-portal/locations/", "icon": "pin"},
        ],
    },
    {
        "label": "Commerce",
        "items": [
            {
                "label": "Token Packages",
                "url": "/admin-portal/token-packages/",
                "icon": "coin",
            },
            {
                "label": "Subscription Plans",
                "url": "/admin-portal/plans/",
                "icon": "star",
            },
            {
                "label": "Lead Pricing",
                "url": "/admin-portal/lead-pricing/",
                "icon": "tag",
            },
        ],
    },
    {
        "label": "Matching Engine",
        "items": [
            {
                "label": "Config",
                "url": "/admin-portal/matching/config/",
                "icon": "sliders",
            },
            {
                "label": "Subject Aliases",
                "url": "/admin-portal/matching/subject-aliases/",
                "icon": "link",
            },
            {
                "label": "Language Aliases",
                "url": "/admin-portal/matching/language-aliases/",
                "icon": "link",
            },
            {
                "label": "Pincode Locations",
                "url": "/admin-portal/matching/pincodes/",
                "icon": "pin",
            },
        ],
    },
    {
        "label": "Account",
        "items": [
            {
                "label": "Notifications",
                "url": "/admin-portal/notifications/",
                "icon": "bell",
                "badge": "notifications",
            },
            {"label": "Settings", "url": "/admin-portal/settings/", "icon": "cog"},
        ],
    },
]

# Super Admin = the full Admin surface, re-homed under /super-admin/, plus the
# platform-oversight tools (user management, impersonation, admin-login
# approvals, audit log, operations).
_SUPERADMIN_OVERSIGHT = {
    "label": "Platform Oversight",
    "items": [
        {
            "label": "Operations",
            "url": "/super-admin/oversight/",
            "icon": "activity",
            "match": "/super-admin/oversight/",
        },
        {
            "label": "Review queue",
            "url": "/super-admin/review-queue/",
            "icon": "alert-triangle",
            "match": "/super-admin/review-queue/",
        },
        {"label": "Users", "url": "/super-admin/users/", "icon": "users"},
        {
            "label": "Admin access requests",
            "url": "/super-admin/admin-requests/",
            "icon": "shield",
            "badge": "admin_requests",
        },
        {"label": "Audit log", "url": "/super-admin/audit/", "icon": "list"},
    ],
}


def _rehome(sections, old, new):
    out = []
    for section in sections:
        items = []
        for item in section["items"]:
            it = dict(item)
            if it.get("url"):
                it["url"] = it["url"].replace(old, new, 1)
                it["match"] = it.get("match", it["url"]).replace(old, new, 1)
            items.append(it)
        out.append({"label": section["label"], "items": items})
    return out


def _teacher_nav():
    """
    The teacher nav, adjusted for whichever unlock economy is live.

    The default list carries no Wallet: while TOKEN_SYSTEM_ENABLED is False a
    token ledger is meaningless to a teacher who never sees tokens, and the
    word "token" must not reach the screen. If the token economy is ever
    switched on, the ledger becomes worth reading and the link is added back.
    """
    from django.conf import settings

    if not settings.TOKEN_SYSTEM_ENABLED:
        return _TEACHER

    sections = []
    for section in _TEACHER:
        items = list(section["items"])
        # Sits next to Plan & unlocks, which is what it's the ledger for.
        for i, item in enumerate(items):
            if item.get("url") == "/teacher/plan/":
                items.insert(
                    i + 1,
                    {"label": "Wallet", "url": "/teacher/wallet/", "icon": "wallet"},
                )
                break
        sections.append({**section, "items": items})
    return sections


def nav_for(role):
    if role == "student":
        return _STUDENT
    if role == "teacher":
        return _teacher_nav()
    if role == "admin":
        return _ADMIN_SECTIONS
    if role == "superadmin":
        base = _rehome(_ADMIN_SECTIONS, "/admin-portal/", "/super-admin/")
        # drop the plain "Users" link (superadmin gets the full management one
        # under Platform Oversight instead)
        base[1]["items"] = [
            i for i in base[1]["items"] if i.get("url") != "/super-admin/users/"
        ]
        return base[:-1] + [_SUPERADMIN_OVERSIGHT] + base[-1:]
    return []
