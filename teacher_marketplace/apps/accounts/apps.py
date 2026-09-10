"""
App configuration for the accounts app.

This app owns the custom User model (authentication/identity),
plus - in later files within this same app - the Register/Login/
Logout/Refresh/Change-Password/Forgot-Password/Reset-Password APIs.
"""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Accounts"

    def ready(self):
        """
        Django calls this once the app registry is fully populated.
        Reserved for signal registration in later phases (e.g. a
        post_save signal on User that auto-creates a linked
        Student or Teacher profile based on role).

        Phase 1 deliberately registers no signals here - doing so
        would mean writing cross-app business logic (User ->
        Student/Teacher linkage), which violates this phase's
        "no business logic" rule. Left as an explicit no-op with
        this docstring so the intended future extension point is
        clear rather than silently absent.
        """
        pass
