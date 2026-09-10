"""
URL configuration for the location app.

Included from config/urls.py at the `api/v1/location/` prefix, so
the full paths resolve to:

    GET/POST                /api/v1/location/countries/
    GET/PUT/PATCH/DELETE     /api/v1/location/countries/{id}/
    GET/POST                /api/v1/location/states/             (?country=<id> to filter)
    GET/PUT/PATCH/DELETE     /api/v1/location/states/{id}/
    GET/POST                /api/v1/location/cities/             (?state=<id> or ?country=<id> to filter)
    GET/PUT/PATCH/DELETE     /api/v1/location/cities/{id}/
"""

from django.urls import path

from apps.location.views import (
    CityDetailView,
    CityListCreateView,
    CountryDetailView,
    CountryListCreateView,
    StateDetailView,
    StateListCreateView,
)

app_name = "location"

urlpatterns = [
    # Countries
    path("countries/", CountryListCreateView.as_view(), name="country-list-create"),
    path("countries/<uuid:id>/", CountryDetailView.as_view(), name="country-detail"),
    # States
    path("states/", StateListCreateView.as_view(), name="state-list-create"),
    path("states/<uuid:id>/", StateDetailView.as_view(), name="state-detail"),
    # Cities
    path("cities/", CityListCreateView.as_view(), name="city-list-create"),
    path("cities/<uuid:id>/", CityDetailView.as_view(), name="city-detail"),
]
