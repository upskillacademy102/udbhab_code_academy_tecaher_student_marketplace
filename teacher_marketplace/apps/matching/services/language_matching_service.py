"""
Language matching service for the Teacher Marketplace Platform.
Mirrors SubjectMatchingService exactly - see that file's module
docstring for the full three-tier precedence reasoning.
"""

from django.contrib.postgres.search import TrigramSimilarity

from apps.languages.models import Language
from apps.matching.services.config_service import get_config
from apps.matching.services.subject_matching_service import (
    ALIAS_MATCH_SCORE,
    FUZZY_SCORE_FLOOR,
    MatchResult,
)


class LanguageMatchingService:

    @staticmethod
    def match_by_id(teacher_language_ids: set, required_language_id) -> MatchResult:
        """
        FK-to-FK comparison - the common, fast path used by
        eligibility/scoring for an actual TeacherProfile against an
        actual StudentRequirement (both already normalized to real
        Language rows). No alias/fuzzy tier needed here since both
        sides are already-resolved database ids, not free text.

        Parameter names are language-specific (not the copy-pasted
        `teacher_subject_ids` / `required_subject_id`) because
        EligibilityService calls this by keyword - a mismatch there
        used to raise TypeError and 500 every eligibility check.

        A null `required_language_id` means the student expressed NO
        language preference: there is nothing to fail to match, so
        this is a full-score pass, mirroring
        MatchingService._language_score's handling of the same case.
        """
        if required_language_id is None:
            return MatchResult(is_eligible=True, score=100, matched_via="exact")
        if required_language_id in teacher_language_ids:
            return MatchResult(is_eligible=True, score=100, matched_via="exact")
        return MatchResult(is_eligible=False, score=0, matched_via="none")

    @staticmethod
    def match_by_text(query_text: str) -> MatchResult:
        config = get_config()
        normalized = query_text.strip()

        exact = Language.objects.filter(name__iexact=normalized, is_active=True).first()
        if exact is not None:
            return MatchResult(
                is_eligible=True, score=100, matched_via="exact", matched_subject=exact
            )

        from apps.matching.models import LanguageAlias

        alias = (
            LanguageAlias.objects.filter(
                alias_text__iexact=normalized, language__is_active=True
            )
            .select_related("language")
            .first()
        )
        if alias is not None:
            return MatchResult(
                is_eligible=True,
                score=ALIAS_MATCH_SCORE,
                matched_via="alias",
                matched_subject=alias.language,
            )

        fuzzy_candidate = (
            Language.objects.filter(is_active=True)
            .annotate(similarity=TrigramSimilarity("name", normalized))
            .filter(similarity__gt=FUZZY_SCORE_FLOOR / 100)
            .order_by("-similarity")
            .first()
        )
        if fuzzy_candidate is not None:
            fuzzy_score = round(fuzzy_candidate.similarity * 100)
            is_eligible = fuzzy_score >= config.language_match_threshold
            return MatchResult(
                is_eligible=is_eligible,
                score=fuzzy_score,
                matched_via="fuzzy",
                matched_subject=fuzzy_candidate,
            )

        return MatchResult(is_eligible=False, score=0, matched_via="none")
