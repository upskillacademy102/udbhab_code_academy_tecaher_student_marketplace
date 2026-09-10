"""Give every new User a TrustProfile row."""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import User
from apps.trust.models import TrustProfile


@receiver(post_save, sender=User, dispatch_uid="trust_create_profile")
def create_trust_profile(sender, instance, created, **kwargs):
    if created:
        TrustProfile.objects.get_or_create(user=instance)
