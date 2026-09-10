"""
URL configuration for the reviews app.

Two exported pattern lists (same dual-prefix pattern as apps.payments):
    /api/v1/reviews/                -> review_urlpatterns
    /api/v1/teachers/{id}/reviews/   -> teacher_reviews_urlpatterns
"""

from django.urls import path

from apps.reviews.views import MyReviewsView, ReviewDetailView, TeacherReviewsView

app_name = "reviews"

review_urlpatterns = [
    path("", MyReviewsView.as_view(), name="my-reviews"),
    path("<uuid:id>/", ReviewDetailView.as_view(), name="review-detail"),
]

teacher_reviews_urlpatterns = [
    path("<uuid:id>/reviews/", TeacherReviewsView.as_view(), name="teacher-reviews"),
]
