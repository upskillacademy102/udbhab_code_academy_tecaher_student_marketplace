"""
Small helpers for the languages app, split out of
apps.student_requirement.serializers so the same "make up a short code for
a freshly-typed language name" logic can be reused by the Learning Partner
taxonomy-request approval flow (apps.accounts.admin_api), not just the
original student-requirement free-text auto-create path.
"""

import re

from apps.languages.models import Language


def derive_language_code(name: str) -> str:
    """
    Build a Language.code candidate for a human-typed name: 2-10 lowercase
    letters/digits, starting with a letter, unique. This code has no ISO
    meaning - it is just a stable short identifier satisfying the schema;
    a Super Admin can replace it with the real ISO code from
    /super-admin/languages/ any time.
    """
    base = re.sub(r"[^a-z0-9]", "", name.lower())
    if not base or not base[0].isalpha():
        base = "x" + base
    base = base[:10] or "xx"
    if len(base) < 2:
        base = base + "x"

    candidate = base
    suffix = 1
    while Language.all_objects.filter(code=candidate).exists() and suffix < 50:
        suffix_str = str(suffix)
        candidate = base[: 10 - len(suffix_str)] + suffix_str
        suffix += 1
    return candidate
