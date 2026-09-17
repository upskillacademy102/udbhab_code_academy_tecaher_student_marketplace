"""
Location matching service for the Teacher Marketplace Platform.

Implements Section 11-13 of the matching spec exactly:
    - Pincode -> lat/long -> distance calculation -> nearest
      eligible teachers (via PincodeLocation + PostGIS, never
      numeric pincode comparison).
    - Radius expansion (`radius_used_km`): start at
      INITIAL_LOCATION_RADIUS_KM, widen by
      LOCATION_RADIUS_INCREMENT_KM until ANY candidate is found or
      MAX_LOCATION_RADIUS_KM is reached - purely informational
      ("how far did we have to look"), NOT the per-candidate
      eligibility cutoff.
    - ELIGIBILITY is a flat `distance_km <= MAX_LOCATION_RADIUS_KM`
      check for every candidate independently - never unbounded, and
      never narrowed to whatever smaller radius the expansion above
      happened to stop at. A teacher 10km away is eligible whether or
      not a teacher 2km away also exists; the closer one only affects
      ORDERING (nearest offered first), not whether the farther one
      is in the pool at all - required for "offer the nearest
      teacher, then the next-nearest on reject/timeout" to ever be
      able to reach a second candidate.
    - LocationScoringService converts distance into a 0-100 score.

SCORING APPROACH CHOSEN: LINEAR DECAY, explained per the spec's
explicit "explain your choice" requirement.
    - Distance buckets were considered but rejected: they create
      arbitrary cliff-edges (a teacher at 4.9km scoring identically
      to one at 0.1km if both fall in the same bucket, then a sharp
      drop at 5.0km) that don't reflect genuine proximity
      preference and are harder for the "search result explanation"
      feature to justify with a specific number.
    - Exponential decay was considered but rejected as
      over-engineered for this stage: it requires choosing a decay
      constant with no principled way to pick one from the spec's
      inputs, and produces the same qualitative behavior (closer is
      much better than far) as linear decay for the sub-20km ranges
      this app operates in - the mathematical nuance of exponential
      decay only matters at scales/distances this marketplace
      doesn't operate at.
    - Linear decay was chosen because it's the simplest function
      that is (a) monotonic, (b) exactly 100 at distance=0, (c)
      exactly 0 at max_radius, and (d) trivially explainable to a
      student ("this teacher is 40% of the way to your search
      radius, so ~60% location score") - directly serving the
      spec's transparency requirement (Section 39) better than a
      curve whose exact percentage at a given distance is less
      intuitive to justify.
"""

from dataclasses import dataclass
from typing import Optional

from django.contrib.gis.db.models.functions import Distance

from apps.matching.models import PincodeLocation
from apps.matching.services.config_service import get_config


@dataclass(frozen=True)
class LocationMatchResult:
    is_eligible: bool
    score: int  # 0-100
    distance_km: Optional[float]
    radius_used_km: Optional[int]
    matched_via: str  # "within_radius" | "no_teachers_found" | "not_applicable"


class LocationScoringService:
    """
    Pure scoring function - see module docstring for the linear-
    decay rationale.
    """

    @staticmethod
    def score_for_distance(distance_km: float, max_radius_km: int) -> int:
        if max_radius_km <= 0:
            return 0
        if distance_km <= 0:
            return 100
        if distance_km >= max_radius_km:
            return 0
        ratio = distance_km / max_radius_km
        return round((1 - ratio) * 100)


class LocationMatchingService:
    """
    Radius-expansion candidate search. find_eligible_teacher_ids()
    is the primary entry point - returns a dict of
    {teacher_id: (distance_km, score)} for every teacher pincode
    found within the final radius reached, expanding the search
    radius step by step until at least one candidate is found or
    the configured maximum is reached.
    """

    @staticmethod
    def find_eligible_teacher_ids(
        student_pincode_location: PincodeLocation,
        candidate_teacher_pincode_ids: dict,
    ) -> dict:
        """
        Args:
            student_pincode_location: the student's PincodeLocation.
            candidate_teacher_pincode_ids: {teacher_id: pincode_location_id}
                for the ALREADY subject/language-filtered candidate
                teachers (per the two-phase performance strategy -
                this method must never be called against the full
                teacher table).

        Returns:
            {teacher_id: LocationMatchResult} for every candidate
            teacher, INCLUDING ones beyond the final radius reached
            (marked is_eligible=False) - the caller (EligibilityService)
            decides what to do with ineligible entries; this method's
            job is purely to compute distance and eligibility, not to
            filter the response shape.
        """
        config = get_config()

        if student_pincode_location is None or not candidate_teacher_pincode_ids:
            return {
                teacher_id: LocationMatchResult(
                    is_eligible=False,
                    score=0,
                    distance_km=None,
                    radius_used_km=None,
                    matched_via="not_applicable",
                )
                for teacher_id in candidate_teacher_pincode_ids
            }

        candidate_location_ids = set(candidate_teacher_pincode_ids.values())
        candidate_locations = PincodeLocation.objects.filter(
            id__in=candidate_location_ids
        ).annotate(distance=Distance("location", student_pincode_location.location))
        distance_by_location_id = {
            loc.id: loc.distance.km for loc in candidate_locations
        }

        radius = config.initial_location_radius_km
        radius_used = radius
        found_any = False

        while radius <= config.max_location_radius_km:
            found_any = any(
                distance_by_location_id.get(loc_id) is not None
                and distance_by_location_id[loc_id] <= radius
                for loc_id in candidate_location_ids
            )
            radius_used = radius
            if found_any:
                break
            radius += config.location_radius_increment_km

        results = {}
        for teacher_id, location_id in candidate_teacher_pincode_ids.items():
            distance_km = distance_by_location_id.get(location_id)
            if distance_km is None:
                results[teacher_id] = LocationMatchResult(
                    is_eligible=False,
                    score=0,
                    distance_km=None,
                    radius_used_km=radius_used,
                    matched_via="not_applicable",
                )
                continue

            # ELIGIBILITY is a flat cutoff at the configured MAXIMUM radius,
            # never the (possibly much smaller) `radius_used` the expansion
            # loop above happened to stop at. `radius_used` only answers
            # "how far did we have to look to find ANYONE at all" - it is
            # not a per-candidate cutoff. Using it as one would make a
            # genuinely in-range teacher (e.g. 10km away, well inside a
            # 20km max) ineligible just because a CLOSER teacher (e.g.
            # 2km away) also exists and made the search stop expanding
            # early - which would silently defeat "offer the nearest
            # teacher first, and only fall back to a farther one if they
            # reject or time out": the farther-but-still-in-range teacher
            # would never even be a candidate to fall back to.
            is_within = distance_km <= config.max_location_radius_km
            score = LocationScoringService.score_for_distance(
                distance_km, config.max_location_radius_km
            )
            results[teacher_id] = LocationMatchResult(
                is_eligible=is_within,
                score=score,
                distance_km=round(distance_km, 2),
                radius_used_km=radius_used,
                matched_via="within_radius" if is_within else "beyond_max_radius",
            )

        return results

    @staticmethod
    def distance_between(
        location_a: PincodeLocation, location_b: PincodeLocation
    ) -> Optional[float]:
        """
        Convenience single-pair distance check (e.g. for
        best-slots-style ad-hoc queries), in kilometres.
        """
        if location_a is None or location_b is None:
            return None
        result = (
            PincodeLocation.objects.filter(id=location_a.id)
            .annotate(distance=Distance("location", location_b.location))
            .first()
        )
        return round(result.distance.km, 2) if result else None
