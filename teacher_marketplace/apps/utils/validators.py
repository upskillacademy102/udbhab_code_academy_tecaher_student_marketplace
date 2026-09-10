"""
Reusable field validators for the Teacher Marketplace Platform.

These are plain DRF/Django-style validators - callables that raise
django.core.exceptions.ValidationError on invalid input - so they
can be attached directly to model fields (via `validators=[...]`)
or to DRF serializer fields, and will surface as proper 400
responses through our custom exception handler either way.

Phase 1 scope: only generic field-level validation (email, mobile,
password strength). No business rules (e.g. "teacher must have a
qualification") belong here - those are service-layer concerns for
later phases.
"""

import re

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.utils.translation import gettext_lazy as _

# ==========================================================
# EMAIL VALIDATION
# ==========================================================
# Wraps Django's own EmailValidator so all our apps import a
# single, consistent validator from one place rather than each
# app importing directly from django.core.validators.
validate_email_format = EmailValidator(message=_("Enter a valid email address."))


# ==========================================================
# MOBILE NUMBER VALIDATION
# ==========================================================
# Digits only - no '+', no spaces, no hyphens. 10 to 15 digits total.
MOBILE_NUMBER_REGEX = re.compile(r"^[0-9]{10,15}$")


def validate_mobile_number(value: str) -> None:
    """
    Validates that `value` contains ONLY numeric digits (10 to 15
    digits total). No '+', spaces, or special characters allowed.
    """
    if not value or not MOBILE_NUMBER_REGEX.match(value):
        raise ValidationError(
            _("Mobile number must contain only digits (10 to 15 numbers)."),
            code="invalid_mobile_number",
        )


# ==========================================================
# NAME VALIDATION (first_name / last_name)
# ==========================================================
# Letters only - no digits, no special characters. Spaces allowed
# for compound names (e.g. "Mary Jane"), hyphens/apostrophes allowed
# for names like "Anne-Marie" or "O'Brien".
NAME_REGEX = re.compile(r"^[A-Za-z][A-Za-z\s'-]*$")


def validate_name(value: str) -> None:
    """
    Validates that `value` contains only alphabetic characters
    (optionally with spaces, hyphens, or apostrophes for compound
    names). Rejects digits and other special characters.
    """
    if not value or not NAME_REGEX.match(value):
        raise ValidationError(
            _("This field must contain only letters."),
            code="invalid_name",
        )


# ==========================================================
# PASSWORD STRENGTH VALIDATION
# ==========================================================
class PasswordStrengthValidator:
    """
    Custom password validator implementing Django's password
    validator interface (validate() + get_help_text()), so it can
    be plugged directly into AUTH_PASSWORD_VALIDATORS in settings
    alongside Django's built-in validators, OR called directly from
    a serializer for immediate field-level feedback at registration
    time.

    Enforces, in addition to Django's built-in length/similarity/
    common-password checks:
        - At least one uppercase letter
        - At least one lowercase letter
        - At least one digit
        - At least one special character
    """

    UPPERCASE_REGEX = re.compile(r"[A-Z]")
    LOWERCASE_REGEX = re.compile(r"[a-z]")
    DIGIT_REGEX = re.compile(r"\d")
    SPECIAL_CHAR_REGEX = re.compile(r"[!@#$%^&*()\-_=+\[\]{};:'\",.<>/?\\|`~]")

    def validate(self, password, user=None):
        errors = []

        if not self.UPPERCASE_REGEX.search(password):
            errors.append(_("Password must contain at least one uppercase letter."))

        if not self.LOWERCASE_REGEX.search(password):
            errors.append(_("Password must contain at least one lowercase letter."))

        if not self.DIGIT_REGEX.search(password):
            errors.append(_("Password must contain at least one digit."))

        if not self.SPECIAL_CHAR_REGEX.search(password):
            errors.append(_("Password must contain at least one special character."))

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _(
            "Your password must contain at least one uppercase letter, "
            "one lowercase letter, one digit, and one special character."
        )


# ==========================================================
# FREE-TEXT HYGIENE
# ==========================================================
# Control characters (except tab/newline) and angle brackets have no
# place in a name/city/headline field - they are almost always a paste
# accident or an injection attempt.
_CONTROL_CHARS_REGEX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ANGLE_BRACKET_REGEX = re.compile(r"[<>]")


def validate_no_control_characters(value: str) -> None:
    """Rejects control characters and angle brackets in short text fields."""
    if value is None:
        return
    if _CONTROL_CHARS_REGEX.search(value):
        raise ValidationError(
            _("This field contains characters that aren't allowed."),
            code="invalid_characters",
        )
    if _ANGLE_BRACKET_REGEX.search(value):
        raise ValidationError(
            _("The characters '<' and '>' aren't allowed here."),
            code="invalid_characters",
        )


# A place name: at least one letter, then letters / spaces / digits and
# the punctuation that legitimately appears in place names
# ("St. John's", "Sector-21", "Al Ain"). No leading/trailing space
# (callers strip first), 2-100 chars.
_PLACE_NAME_REGEX = re.compile(
    r"^(?=.*[A-Za-z])[A-Za-z0-9][A-Za-z0-9 .,'\-/()&]{1,99}$"
)


def validate_place_name(value: str) -> None:
    """
    Validates a city / state / country style field: must contain a
    letter, only sensible characters, 2-100 chars. Rejects all-digit,
    all-punctuation, or junk input like 'asdf!!!' / '12345'.
    """
    if value is None or value == "":
        return
    validate_no_control_characters(value)
    if not _PLACE_NAME_REGEX.match(value):
        raise ValidationError(
            _(
                "Enter a valid place name (letters, and optionally spaces, "
                "digits, and . , ' - / characters)."
            ),
            code="invalid_place_name",
        )


# ==========================================================
# REFERENCE-DATA / TAXONOMY NAMES
# ==========================================================
# A taxonomy display name (subject, language, plan, package, tier label...):
# must contain a letter; letters / digits / spaces and the punctuation that
# legitimately appears in such names ("C++", "Chinese - Mandarin",
# "English (US)", "Class 9 & 10"). 2-150 chars.
_TAXONOMY_NAME_REGEX = re.compile(
    r"^(?=.*[A-Za-z])[A-Za-z0-9][A-Za-z0-9 .,'\-/()&+#]{1,149}$"
)


def validate_taxonomy_name(value: str) -> None:
    if value is None or value == "":
        return
    validate_no_control_characters(value)
    if not _TAXONOMY_NAME_REGEX.match(value):
        raise ValidationError(
            _(
                "Enter a valid name (letters, and optionally digits, spaces, and "
                ". , ' - / ( ) & + # characters)."
            ),
            code="invalid_taxonomy_name",
        )


# A language / locale code: starts with a letter, then letters / digits /
# hyphens, 2-10 chars. Accepts 'en', 'hi', 'pt-br', 'zh-hans'. Rejects '!!!',
# '12', 'en glish'.
_LANGUAGE_CODE_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,9}$")


def validate_language_code(value: str) -> None:
    if value is None or value == "":
        return
    if not _LANGUAGE_CODE_REGEX.match(value):
        raise ValidationError(
            _("Enter a valid language code, e.g. 'en', 'hi', 'pt-br'."),
            code="invalid_language_code",
        )


# ISO 3166-1 alpha-2 or alpha-3 country code (letters only, 2-3 chars).
_COUNTRY_CODE_REGEX = re.compile(r"^[A-Za-z]{2,3}$")


def validate_country_code(value: str) -> None:
    if value is None or value == "":
        return
    if not _COUNTRY_CODE_REGEX.match(value):
        raise ValidationError(
            _("Enter a valid ISO country code (2 or 3 letters, e.g. 'IN', 'USA')."),
            code="invalid_country_code",
        )


# ==========================================================
# IMAGE UPLOADS (profile photos)
# ==========================================================
# A profile photo is the only file a user can upload. Cap it hard so it
# cannot be used for storage abuse, a decompression bomb, or to smuggle a
# non-image payload (e.g. an HTML/SVG file that a browser might render).
_ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
_MAX_IMAGE_DIMENSION = 6000  # px, per side


def validate_image_upload(value) -> None:
    """
    Validate an uploaded image field value: <= 5 MB, real JPEG/PNG/WebP
    (verified by decoding the header, not trusting the extension or the
    client-sent Content-Type), and <= 6000 px per side.

    Only runs when a NEW file is supplied through the serializer - an
    unchanged, already-stored photo is never re-read.
    """
    if value is None:
        return

    size = getattr(value, "size", None)
    if size is not None and size > _MAX_IMAGE_BYTES:
        raise ValidationError(
            _("The image must be 5 MB or smaller."), code="image_too_large"
        )

    # Client-sent content type: reject an obvious mismatch early. Absent on
    # an already-saved FieldFile (re-validation) - skip in that case.
    content_type = getattr(value, "content_type", None)
    if content_type and content_type.lower() not in _ALLOWED_IMAGE_CONTENT_TYPES:
        raise ValidationError(
            _("Upload a JPEG, PNG, or WebP image."), code="image_bad_type"
        )

    # Authoritative check: actually decode the image header with Pillow.
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:  # Pillow is a hard dependency; defensive only.
        return

    try:
        value.seek(0)
    except (AttributeError, OSError):
        pass
    try:
        with Image.open(value) as img:
            image_format = (img.format or "").upper()
            width, height = img.size
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError(_("Upload a valid image file."), code="image_invalid")
    finally:
        try:
            value.seek(0)
        except (AttributeError, OSError):
            pass

    if image_format not in _ALLOWED_IMAGE_FORMATS:
        raise ValidationError(
            _("Upload a JPEG, PNG, or WebP image."), code="image_bad_type"
        )
    if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
        raise ValidationError(
            _("The image must be at most 6000×6000 pixels."),
            code="image_too_large",
        )


def validate_password_strength(password: str) -> None:
    """
    Functional wrapper around PasswordStrengthValidator, for
    convenient direct use inside DRF serializers where a plain
    callable is simpler to wire up than instantiating a class:

        from apps.utils.validators import validate_password_strength

        class RegisterSerializer(serializers.Serializer):
            password = serializers.CharField(
                write_only=True,
                validators=[validate_password_strength],
            )
    """
    PasswordStrengthValidator().validate(password)
