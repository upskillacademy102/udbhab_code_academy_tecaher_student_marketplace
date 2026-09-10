"""
Subject matching service for the Teacher Marketplace Platform.

Implements the spec's exact three-tier precedence:
    1. Exact Subject ID match       -> score 100
    2. Alias match (SubjectAlias)    -> score 90-99 (configurable
                                        band, see ALIAS_MATCH_SCORE)
    3. Fuzzy match (pg_trgm)         -> score = similarity * 100,
                                        only if above the fuzzy
                                        floor; below threshold overall
                                        -> NOT ELIGIBLE

"Prefer normalized IDs wherever possible" is satisfied by tier 1
being checked first and short-circuiting immediately if it matches -
tiers 2/3 only run when the caller has FREE-TEXT input (e.g. a
search query string), not when comparing two already-normalized FK
ids (which is the common case: TeacherProfile.subjects vs
StudentRequirement.subject are both real FKs, so
match_by_id() below - trivial equality - handles that path; the
free-text tiers exist for search-query matching, not FK-to-FK
comparison).
"""

from dataclasses import dataclass
from typing import Optional

from django.contrib.postgres.search import TrigramSimilarity

from apps.matching.services.config_service import get_config
from apps.subjects.models import Subject

ALIAS_MATCH_SCORE = 95  # midpoint of the spec's "90-99" alias band
FUZZY_SCORE_FLOOR = (
    50  # below this raw similarity*100, don't even offer it as a candidate
)


@dataclass(frozen=True)
class MatchResult:
    """
    Uniform result shape shared by subject/language/location
    matching services - `matched_via` feeds directly into the
    spec's "Search Result Explanation" feature (Section 39).
    """

    is_eligible: bool
    score: int  # 0-100
    matched_via: str  # "exact" | "alias" | "fuzzy" | "none"
    matched_subject: Optional[Subject] = None


class SubjectMatchingService:

    @staticmethod
    def match_by_id(teacher_subject_ids: set, required_subject_id) -> MatchResult:
        """
        FK-to-FK comparison - the common, fast path used by
        eligibility/scoring for an actual TeacherProfile against an
        actual StudentRequirement (both already normalized to real
        Subject rows). No alias/fuzzy tier needed here since both
        sides are already-resolved database ids, not free text.
        """
        if required_subject_id in teacher_subject_ids:
            return MatchResult(is_eligible=True, score=100, matched_via="exact")
        return MatchResult(is_eligible=False, score=0, matched_via="none")

    @staticmethod
    def match_by_text(query_text: str) -> MatchResult:
        """
        Free-text resolution path - e.g. a search box where a
        student types "Math" and the system must resolve that to
        the canonical Mathematics Subject. Tries exact name match,
        then SubjectAlias, then pg_trgm fuzzy similarity against
        Subject.name, in that order, per the spec's precedence.
        """
        config = get_config()
        normalized = query_text.strip()

        exact = Subject.objects.filter(name__iexact=normalized, is_active=True).first()
        if exact is not None:
            return MatchResult(
                is_eligible=True, score=100, matched_via="exact", matched_subject=exact
            )

        from apps.matching.models import SubjectAlias

        alias = (
            SubjectAlias.objects.filter(
                alias_text__iexact=normalized, subject__is_active=True
            )
            .select_related("subject")
            .first()
        )
        if alias is not None:
            return MatchResult(
                is_eligible=True,
                score=ALIAS_MATCH_SCORE,
                matched_via="alias",
                matched_subject=alias.subject,
            )

        fuzzy_candidate = (
            Subject.objects.filter(is_active=True)
            .annotate(similarity=TrigramSimilarity("name", normalized))
            .filter(similarity__gt=FUZZY_SCORE_FLOOR / 100)
            .order_by("-similarity")
            .first()
        )
        if fuzzy_candidate is not None:
            fuzzy_score = round(fuzzy_candidate.similarity * 100)
            is_eligible = fuzzy_score >= config.subject_match_threshold
            return MatchResult(
                is_eligible=is_eligible,
                score=fuzzy_score,
                matched_via="fuzzy",
                matched_subject=fuzzy_candidate,
            )

        return MatchResult(is_eligible=False, score=0, matched_via="none")
