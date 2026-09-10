"""
Location resolution service for the Teacher Marketplace Platform.

resolve() accepts ONE plain-text field that may be either a city
name ("Kolkata") or a pincode ("700001"), auto-detects which, and
resolves it to the appropriate internal entity:
    - Pincode-like input (all digits, 4-10 chars) -> PincodeGeocodingService
      (already built) -> PincodeLocation.
    - Otherwise -> treated as a city name -> apps.location.City,
      resolved via exact name match, then pg_trgm fuzzy fallback -
      mirroring SubjectMatchingService's exact-then-fuzzy pattern,
      no new matching technology.

Returns both city and pincode_location (whichever was resolved) so
the caller (StudentRequirementWriteSerializer) can populate
StudentRequirement's existing city (apps.location.City FK) and/or
pincode_location (apps.matching.PincodeLocation FK) fields
unchanged - this service does not alter what those fields mean.
"""

from dataclasses import dataclass
from typing import Optional

from django.contrib.postgres.search import TrigramSimilarity

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.location.models import City
from apps.matching.models import PincodeLocation
from apps.matching.services.config_service import get_config
from apps.matching.services.geocoding_service import (
    GeocodingError,
    PincodeGeocodingService,
)

FUZZY_CITY_SCORE_FLOOR = 50


@dataclass(frozen=True)
class LocationResolutionResult:
    city: Optional[City]
    pincode_location: Optional[PincodeLocation]
    matched_via: str  # "pincode" | "city_exact" | "city_fuzzy" | "none"


class LocationResolutionService:

    @staticmethod
    def _looks_like_pincode(text: str) -> bool:
        stripped = text.strip()
        return stripped.isdigit() and 4 <= len(stripped) <= 10

    @staticmethod
    def resolve(
        location_text: str, *, defer_city_geocode: bool = False
    ) -> LocationResolutionResult:
        """
        Raises ValidationException if the input cannot be resolved
        to any known city or valid pincode - never guesses.

        ``defer_city_geocode=True`` skips the best-effort city-centroid
        geocode (an outbound HTTP call with a multi-second timeout). Used
        by the requirement-create serializer so a slow/unreachable geocoder
        never delays the student's submission - the async lead task
        backfills ``pincode_location`` before matching. A *pincode* input
        is still resolved synchronously here: its coordinates are the
        location's identity, not an optional enrichment, and the lookup is
        normally a cache hit.
        """
        if not location_text or not location_text.strip():
            raise ValidationException(detail="Location is required.")

        text = location_text.strip()

        if LocationResolutionService._looks_like_pincode(text):
            try:
                pincode_location = PincodeGeocodingService.get_or_geocode(text)
            except GeocodingError as exc:
                raise ValidationException(detail=str(exc.detail))
            return LocationResolutionResult(
                city=None, pincode_location=pincode_location, matched_via="pincode"
            )

        def _centroid(city):
            return (
                None
                if defer_city_geocode
                else LocationResolutionService._try_geocode_city(city)
            )

        exact = City.objects.filter(name__iexact=text, is_active=True).first()
        if exact is not None:
            return LocationResolutionResult(
                city=exact, pincode_location=_centroid(exact), matched_via="city_exact"
            )

        config = get_config()
        fuzzy_candidate = (
            City.objects.filter(is_active=True)
            .annotate(similarity=TrigramSimilarity("name", text))
            .filter(similarity__gt=FUZZY_CITY_SCORE_FLOOR / 100)
            .order_by("-similarity")
            .first()
        )
        if fuzzy_candidate is not None:
            fuzzy_score = round(fuzzy_candidate.similarity * 100)
            threshold = getattr(
                config, "subject_match_threshold", 70
            )  # reuse same default bar
            if fuzzy_score >= threshold:
                return LocationResolutionResult(
                    city=fuzzy_candidate,
                    pincode_location=_centroid(fuzzy_candidate),
                    matched_via="city_fuzzy",
                )

        raise ValidationException(
            detail=f"Location '{location_text}' could not be recognized. Please provide a valid city name or pincode."
        )

    @staticmethod
    def _try_geocode_city(city) -> Optional[PincodeLocation]:
        """
        Best-effort city-centroid geocoding for offline distance
        matching. Deliberately non-fatal: if geocoding fails (e.g.
        the geocoding service is temporarily down), the city name
        resolution itself still succeeds - the caller just won't get
        radius-based distance ranking for this search, degrading
        gracefully rather than blocking an otherwise-valid city match.
        """
        try:
            return PincodeGeocodingService.get_or_geocode_city(city)
        except GeocodingError:
            return None
