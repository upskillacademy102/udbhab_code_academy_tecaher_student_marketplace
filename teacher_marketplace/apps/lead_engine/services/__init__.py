"""
Services package for the lead_engine app.

Re-exports the most commonly-imported names at the package level so
existing call sites using `from apps.lead_engine.services import X`
continue to work exactly as before this package was introduced.
"""

from apps.lead_engine.services.lead_generation_service import (
    _teaching_modes_compatible,
    find_candidate_teacher_profiles,
    generate_leads_for_requirement,
)

__all__ = [
    "_teaching_modes_compatible",
    "find_candidate_teacher_profiles",
    "generate_leads_for_requirement",
]
