"""
Geocoding service for the Teacher Marketplace Platform.

PincodeGeocodingService.get_or_geocode() is the entry point every
other part of this app should use to resolve a pincode string into
a PincodeLocation - it NEVER fabricates coordinates. If a pincode
isn't already in our table, it calls a real external geocoding
provider (default: OpenStreetMap Nominatim, free and keyless) and
permanently caches the result, so the same pincode is only ever
looked up externally once.

PROVIDER: defaults to Nominatim (settings.GEOCODING_PROVIDER =
"nominatim"). Nominatim's usage policy requires a real User-Agent
header identifying the application and a maximum of 1 request per
second for its free public endpoint - both respected here. For
higher-volume production use, switch settings.GEOCODING_PROVIDER to
"google" (requires GOOGLE_GEOCODING_API_KEY) - the provider
interface below is deliberately swappable via one settings value,
not hardcoded to Nominatim throughout the codebase.
"""

import logging
import time

import requests
from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.cache import cache

from apps.core.exceptions.custom_exceptions import ValidationException
from apps.matching.models import PincodeLocation

logger = logging.getLogger("apps.matching.geocoding")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = (
    "TeacherMarketplacePlatform/1.0 (contact: support@teachermarketplace.example)"
)

# Nominatim's usage policy caps free-tier requests at 1/second -
# this module-level throttle enforces that across all calls within
# this process, regardless of caller.
_RATE_LIMIT_CACHE_KEY = "nominatim_last_request_ts"
_MIN_SECONDS_BETWEEN_REQUESTS = 1.1  # slightly over 1s for safety margin


class GeocodingError(ValidationException):
    default_detail = "Could not resolve this pincode to a real location."
    error_code = "GEOCODING_FAILED"


class PincodeGeocodingService:

    @staticmethod
    def get_or_geocode(pincode: str, country: str = "India") -> PincodeLocation:
        """
        Returns the PincodeLocation for `pincode`, geocoding and
        persisting it if this is the first time it's been seen.
        Raises GeocodingError if the pincode cannot be resolved by
        the configured provider - callers must handle this as a
        genuine "we don't know where this is" case, never silently
        substitute a guessed location.
        """
        existing = PincodeLocation.objects.filter(pincode=pincode).first()
        if existing is not None:
            return existing

        provider = getattr(settings, "GEOCODING_PROVIDER", "nominatim")
        if provider == "nominatim":
            lat, lng, city, state, resolved_country = (
                PincodeGeocodingService._geocode_nominatim(pincode, country)
            )
        elif provider == "google":
            lat, lng, city, state, resolved_country = (
                PincodeGeocodingService._geocode_google(pincode, country)
            )
        else:
            raise GeocodingError(
                detail=f"Unknown GEOCODING_PROVIDER '{provider}' configured."
            )

        location = PincodeLocation.objects.create(
            pincode=pincode,
            location=Point(lng, lat, srid=4326),
            city=city,
            state=state,
            country=resolved_country or country,
        )
        logger.info("Geocoded and cached new pincode: %s (%s, %s)", pincode, lat, lng)
        return location

    @staticmethod
    def _throttle_nominatim():
        """Enforces Nominatim's 1 request/second policy across this process."""
        last_ts = cache.get(_RATE_LIMIT_CACHE_KEY)
        now = time.monotonic()
        if last_ts is not None:
            elapsed = now - last_ts
            if elapsed < _MIN_SECONDS_BETWEEN_REQUESTS:
                time.sleep(_MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
        cache.set(_RATE_LIMIT_CACHE_KEY, time.monotonic(), timeout=10)

    @staticmethod
    def _geocode_nominatim(pincode: str, country: str):
        PincodeGeocodingService._throttle_nominatim()

        try:
            response = requests.get(
                NOMINATIM_URL,
                params={
                    "postalcode": pincode,
                    "country": country,
                    "format": "json",
                    "addressdetails": 1,
                    "limit": 1,
                },
                headers={"User-Agent": NOMINATIM_USER_AGENT},
                timeout=10,
            )
            response.raise_for_status()
            results = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error(
                "Nominatim geocoding request failed for pincode %s: %s", pincode, exc
            )
            raise GeocodingError(
                detail="Geocoding service is currently unavailable. Please try again shortly."
            )

        if not results:
            raise GeocodingError(detail=f"Pincode '{pincode}' could not be found.")

        result = results[0]
        address = result.get("address", {})
        return (
            float(result["lat"]),
            float(result["lon"]),
            address.get("city") or address.get("town") or address.get("village"),
            address.get("state"),
            address.get("country"),
        )

    @staticmethod
    def _geocode_google(pincode: str, country: str):
        api_key = getattr(settings, "GOOGLE_GEOCODING_API_KEY", None)
        if not api_key:
            raise GeocodingError(
                detail="Google geocoding is not configured (missing GOOGLE_GEOCODING_API_KEY)."
            )

        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": f"{pincode}, {country}", "key": api_key},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error(
                "Google geocoding request failed for pincode %s: %s", pincode, exc
            )
            raise GeocodingError(
                detail="Geocoding service is currently unavailable. Please try again shortly."
            )

        if data.get("status") != "OK" or not data.get("results"):
            raise GeocodingError(detail=f"Pincode '{pincode}' could not be found.")

        result = data["results"][0]
        location = result["geometry"]["location"]
        components = {
            c["types"][0]: c["long_name"]
            for c in result.get("address_components", [])
            if c.get("types")
        }
        return (
            location["lat"],
            location["lng"],
            components.get("locality"),
            components.get("administrative_area_level_1"),
            components.get("country"),
        )

    @staticmethod
    def get_or_geocode_city(city) -> "PincodeLocation":
        """
        Resolves a City (by name, already matched via
        LocationResolutionService) to a representative PincodeLocation
        - the city's approximate centroid - for use in offline
        distance matching when a student searches by city name
        rather than an exact pincode.

        Cached under a SYNTHETIC pincode key f"CITY:{city.id}", not a
        real postal code - this is a deliberate, clearly-marked
        distinction from genuine pincode rows (never confusable with
        a real pincode since real ones are purely numeric, per
        _looks_like_pincode's digit check). Keying by city.id (not
        the raw search text) means "Kolkata", "kolkata", and any
        fuzzy-matched variant that all resolve to the same City row
        share ONE cached geocode - the external API is called at
        most once ever per city, regardless of how many different
        text variants a student might type.
        """
        synthetic_key = f"CITY:{city.id}"
        existing = PincodeLocation.objects.filter(pincode=synthetic_key).first()
        if existing is not None:
            return existing

        provider = getattr(settings, "GEOCODING_PROVIDER", "nominatim")
        # city.state is a State instance and city.country is a Country instance
        # (see apps.location.models) - join their names, not the model objects.
        state_name = getattr(city.state, "name", None)
        country_name = getattr(city.country, "name", None)
        query_text = ", ".join(filter(None, [city.name, state_name, country_name]))

        if provider == "nominatim":
            lat, lng = PincodeGeocodingService._geocode_place_nominatim(query_text)
        elif provider == "google":
            lat, lng = PincodeGeocodingService._geocode_place_google(query_text)
        else:
            raise GeocodingError(
                detail=f"Unknown GEOCODING_PROVIDER '{provider}' configured."
            )

        location = PincodeLocation.objects.create(
            pincode=synthetic_key,
            location=Point(lng, lat, srid=4326),
            city=city.name,
            state=state_name,
            country=country_name,
        )
        logger.info(
            "Geocoded and cached city centroid: %s -> (%s, %s)", city.name, lat, lng
        )
        return location

    @staticmethod
    def _geocode_place_nominatim(query_text: str):
        """
        General free-text place geocoding (not postal-code-specific)
        - used for city centroids, where there's no single postal
        code to query by.
        """
        PincodeGeocodingService._throttle_nominatim()

        try:
            response = requests.get(
                NOMINATIM_URL,
                params={"q": query_text, "format": "json", "limit": 1},
                headers={"User-Agent": NOMINATIM_USER_AGENT},
                timeout=10,
            )
            response.raise_for_status()
            results = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error(
                "Nominatim place geocoding failed for '%s': %s", query_text, exc
            )
            raise GeocodingError(
                detail="Geocoding service is currently unavailable. Please try again shortly."
            )

        if not results:
            raise GeocodingError(
                detail=f"Could not determine coordinates for '{query_text}'."
            )

        return float(results[0]["lat"]), float(results[0]["lon"])

    @staticmethod
    def _geocode_place_google(query_text: str):
        api_key = getattr(settings, "GOOGLE_GEOCODING_API_KEY", None)
        if not api_key:
            raise GeocodingError(
                detail="Google geocoding is not configured (missing GOOGLE_GEOCODING_API_KEY)."
            )

        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": query_text, "key": api_key},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("Google place geocoding failed for '%s': %s", query_text, exc)
            raise GeocodingError(
                detail="Geocoding service is currently unavailable. Please try again shortly."
            )

        if data.get("status") != "OK" or not data.get("results"):
            raise GeocodingError(
                detail=f"Could not determine coordinates for '{query_text}'."
            )

        location = data["results"][0]["geometry"]["location"]
        return location["lat"], location["lng"]
