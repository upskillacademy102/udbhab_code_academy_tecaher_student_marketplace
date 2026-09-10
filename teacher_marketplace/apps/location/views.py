"""
Views for the location app.

Endpoints (wired up in apps/location/urls.py, next file):
    GET/POST                /api/v1/location/countries/
    GET/PUT/PATCH/DELETE     /api/v1/location/countries/{id}/
    GET/POST                /api/v1/location/states/            (filterable by ?country=<id>)
    GET/PUT/PATCH/DELETE     /api/v1/location/states/{id}/
    GET/POST                /api/v1/location/cities/            (filterable by ?state=<id> or ?country=<id>)
    GET/PUT/PATCH/DELETE     /api/v1/location/cities/{id}/

Design note: List/Retrieve are public (read-only for anyone) since
location data is needed for registration forms and search filters
before a user is authenticated. Only mutations require Admin/
SuperAdmin role - same pattern as subjects/languages.
"""

import logging

import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.filters import SearchFilter

from apps.core.responses import APIResponse
from apps.location.models import City, Country, State
from apps.location.serializers import CitySerializer, CountrySerializer, StateSerializer

logger = logging.getLogger("apps.location")


# ==========================================================
# FILTERSETS
# ==========================================================
class StateFilterSet(django_filters.FilterSet):
    """
    Allows filtering states by their parent country, e.g.
    GET /api/v1/location/states/?country=<country_uuid>
    """

    country = django_filters.UUIDFilter(field_name="country__id")

    class Meta:
        model = State
        fields = ["country", "is_active"]


class CityFilterSet(django_filters.FilterSet):
    """
    Allows filtering cities by their direct parent state, or by
    country (traversing state -> country), e.g.
    GET /api/v1/location/cities/?state=<state_uuid>
    GET /api/v1/location/cities/?country=<country_uuid>
    """

    state = django_filters.UUIDFilter(field_name="state__id")
    country = django_filters.UUIDFilter(field_name="state__country__id")

    class Meta:
        model = City
        fields = ["state", "country", "is_active"]


# ==========================================================
# COUNTRY
# ==========================================================
@extend_schema(tags=["Location"])
class CountryListCreateView(generics.ListCreateAPIView):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend, SearchFilter]
    filterset_fields = ["is_active"]
    search_fields = ["name", "code"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        country = serializer.save()
        logger.info("Country created: %s (by %s)", country.name, request.user.email)
        return APIResponse.created(
            data=CountrySerializer(country).data,
            message="Country created successfully.",
        )


@extend_schema(tags=["Location"])
class CountryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        country = serializer.save()
        logger.info("Country updated: %s (by %s)", country.name, request.user.email)
        return APIResponse.success(
            data=CountrySerializer(country).data,
            message="Country updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        name = instance.name
        instance.delete()
        logger.info("Country soft-deleted: %s (by %s)", name, request.user.email)
        return APIResponse.no_content(message="Country deleted successfully.")


# ==========================================================
# STATE
# ==========================================================
@extend_schema(tags=["Location"])
class StateListCreateView(generics.ListCreateAPIView):
    queryset = State.objects.select_related("country").all()
    serializer_class = StateSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend, SearchFilter]
    filterset_class = StateFilterSet
    search_fields = ["name", "code", "country__name"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        state = serializer.save()
        logger.info("State created: %s (by %s)", state.name, request.user.email)
        return APIResponse.created(
            data=StateSerializer(state).data,
            message="State created successfully.",
        )


@extend_schema(tags=["Location"])
class StateDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = State.objects.select_related("country").all()
    serializer_class = StateSerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        state = serializer.save()
        logger.info("State updated: %s (by %s)", state.name, request.user.email)
        return APIResponse.success(
            data=StateSerializer(state).data,
            message="State updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        name = instance.name
        instance.delete()
        logger.info("State soft-deleted: %s (by %s)", name, request.user.email)
        return APIResponse.no_content(message="State deleted successfully.")


# ==========================================================
# CITY
# ==========================================================
@extend_schema(tags=["Location"])
class CityListCreateView(generics.ListCreateAPIView):
    queryset = City.objects.select_related("state", "state__country").all()
    serializer_class = CitySerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend, SearchFilter]
    filterset_class = CityFilterSet
    search_fields = ["name", "state__name", "state__country__name"]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        city = serializer.save()
        logger.info("City created: %s (by %s)", city.name, request.user.email)
        return APIResponse.created(
            data=CitySerializer(city).data,
            message="City created successfully.",
        )


@extend_schema(tags=["Location"])
class CityDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = City.objects.select_related("state", "state__country").all()
    serializer_class = CitySerializer
    lookup_field = "id"

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return APIResponse.success(data=response.data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        city = serializer.save()
        logger.info("City updated: %s (by %s)", city.name, request.user.email)
        return APIResponse.success(
            data=CitySerializer(city).data,
            message="City updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        name = instance.name
        instance.delete()
        logger.info("City soft-deleted: %s (by %s)", name, request.user.email)
        return APIResponse.no_content(message="City deleted successfully.")
