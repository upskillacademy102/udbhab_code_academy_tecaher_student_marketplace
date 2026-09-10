#!/usr/bin/env python
"""
Django's command-line utility for administrative tasks.

This file is intentionally kept close to Django's default scaffold.
The only customization is ensuring DJANGO_SETTINGS_MODULE defaults to
our development settings when not explicitly set (e.g. local dev
without a .env file yet), while still respecting whatever is set in
the environment (e.g. production servers exporting the production
settings module).
"""
import os
import sys


def main() -> None:
    """Run administrative tasks."""
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "config.settings.development",
    )
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()