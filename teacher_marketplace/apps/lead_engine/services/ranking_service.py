"""
Ranking service for the Teacher Marketplace Platform.

RankingService.rank_candidates() takes a list of already-scored
candidates (each a dict from MatchingService.score_teacher(), plus
the teacher_profile they belong to) and returns them sorted by
relevance, with explicit tie-breaking rules.

TIE-BREAKING ORDER (when match_score is equal):
    1. time_score (higher first) - per the core business rule,
       time compatibility is the single most important
       differentiator among otherwise-equal candidates, so it acts
       as the first tie-breaker even though it's already baked
       into match_score - two teachers CAN tie on the same overall
       match_score while having different time_score components
       (e.g. one scores higher on time but lower on rating than the
       other, netting the same composite).
    2. rating_score (higher first) - a reasonable, transparent
       secondary signal once subject/time are already equal.
    3. created_at of the teacher's profile (earlier first) - a
       final deterministic tie-breaker so ordering is stable and
       reproducible across repeated calls with identical input,
       rather than depending on incidental database row order.

This is a small, standalone service specifically so this exact
ordering logic has ONE place to test the spec's explicit
"Tie-breaking" requirement in isolation, without needing to
re-run the full matching pipeline for every tie-break test case.
"""


class RankingService:

    @staticmethod
    def rank_candidates(scored_candidates: list) -> list:
        """
        Args:
            scored_candidates: list of dicts, each with at least:
                - "teacher_profile": a TeacherProfile instance
                - "score": the dict returned by
                  MatchingService.score_teacher()

        Returns the same list, sorted by (match_score desc,
        [verification_score desc, when the flag is on,]
        time_score desc, rating_score desc, teacher_profile.created_at asc).
        """
        from apps.trust.matching_support import ranking_enabled, verification_score_map

        vscore = (
            verification_score_map(
                c["teacher_profile"].teacher_id for c in scored_candidates
            )
            if ranking_enabled()
            else {}
        )

        def sort_key(candidate):
            score = candidate["score"]
            profile = candidate["teacher_profile"]
            return (
                -score["match_score"],
                -float(vscore.get(profile.teacher_id, 0)),
                -score["time_score"],
                -score["rating_score"],
                profile.created_at,
            )

        return sorted(scored_candidates, key=sort_key)

    @staticmethod
    def filter_minimum_relevance(
        scored_candidates: list, minimum_match_score: int = 0
    ) -> list:
        """
        Optional post-ranking filter: excludes candidates below a
        minimum match_score threshold entirely, rather than
        generating leads/showing search results for teachers who
        are essentially irrelevant matches. Defaults to 0 (no
        filtering) - callers opt into a real threshold explicitly,
        since the appropriate cutoff differs between "generate a
        Lead" (probably should have SOME minimum bar) and "general
        search browsing" (a student might legitimately want to see
        even weak matches while exploring).
        """
        if minimum_match_score <= 0:
            return scored_candidates
        return [
            c
            for c in scored_candidates
            if c["score"]["match_score"] >= minimum_match_score
        ]
