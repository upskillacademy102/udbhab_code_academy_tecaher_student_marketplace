"""
App configuration for the common app.

This app contains reusable abstract base models (BaseModel,
UUIDModel, TimestampModel, SoftDeleteModel, AuditModel) shared
across the entire project. It has no models of its own that
create database tables (all models here are abstract), so it
requires no migrations.
"""

from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    verbose_name = "Common"
