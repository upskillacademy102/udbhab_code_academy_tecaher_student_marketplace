import re

from django import template
from django.utils.safestring import mark_safe

from apps.web.nav import nav_for as _nav_for

register = template.Library()


@register.simple_tag
def nav_for(role, user=None):
    return _nav_for(role, user)


@register.simple_tag(takes_context=True)
def nav_active(context, item):
    """'true' if the current path matches this nav item, else ''."""
    path = context["request"].path
    match = item.get("match") or item.get("url")
    if not match:
        return ""
    if match.endswith("$"):
        return "true" if re.fullmatch(match[:-1], path) else ""
    return "true" if path.startswith(match) else ""


@register.filter
def initials(value):
    parts = [p for p in str(value or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


@register.simple_tag
def icon(name, cls="h-5 w-5"):
    return mark_safe(
        f'<svg class="{cls}" aria-hidden="true" focusable="false">'
        f'<use href="#i-{name}"></use></svg>'
    )
