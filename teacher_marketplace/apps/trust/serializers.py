"""Serializers for the trust app's public endpoints."""

from rest_framework import serializers


class OTPConfirmSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=4, max_length=10, trim_whitespace=True)


class SuspensionAppealCreateSerializer(serializers.Serializer):
    message = serializers.CharField(
        min_length=20, max_length=4000, trim_whitespace=True
    )
    contact_email = serializers.EmailField(required=False, allow_blank=True)
