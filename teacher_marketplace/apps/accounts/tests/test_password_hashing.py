"""
Password hashing policy.

Login / register / change-password were slow (~0.4-1.4 s) - 100% of that was
Django's default PBKDF2 hasher (1.2M iterations, ~350 ms/hash on the reference
box). The project now uses Argon2id: memory-hard, OWASP's first recommendation,
and several times faster.

These tests read `config.settings.base` directly because `config.settings.test`
deliberately swaps in the fast MD5 hasher.
"""

import importlib

from django.contrib.auth.hashers import identify_hasher, make_password
from django.test import TestCase, override_settings

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import make_user

BASE = importlib.import_module("config.settings.base")

_REAL_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]


class PasswordHashingPolicyTests(TestCase):
    def test_base_settings_prefer_argon2(self):
        self.assertEqual(
            BASE.PASSWORD_HASHERS[0],
            "django.contrib.auth.hashers.Argon2PasswordHasher",
            "Argon2id must be the preferred hasher (see PASSWORD_HASHERS).",
        )

    def test_argon2_backend_is_installed(self):
        # Would raise if argon2-cffi were missing.
        import argon2  # noqa: F401

    def test_new_hashes_are_argon2(self):
        with override_settings(PASSWORD_HASHERS=_REAL_HASHERS):
            self.assertEqual(
                identify_hasher(make_password("Str0ng!Pass1")).algorithm, "argon2"
            )

    def test_legacy_pbkdf2_hash_verifies_and_upgrades_transparently(self):
        # A password hashed before the switch (PBKDF2 only)...
        with override_settings(
            PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
        ):
            legacy = make_password("Str0ng!Pass1")
            self.assertEqual(identify_hasher(legacy).algorithm, "pbkdf2_sha256")

        user = make_user(UserRole.TEACHER)
        user.password = legacy
        user.save(update_fields=["password"])

        with override_settings(PASSWORD_HASHERS=_REAL_HASHERS):
            self.assertTrue(user.check_password("Str0ng!Pass1"))  # still authenticates
            user.refresh_from_db()
            self.assertEqual(
                identify_hasher(user.password).algorithm,
                "argon2",
                "check_password() should have rehashed the legacy hash to Argon2",
            )
