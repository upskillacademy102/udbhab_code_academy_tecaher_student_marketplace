"""
Upload safety for the profile-photo field (`PATCH /api/v1/students/me/`).

`profile_photo` is the only file any user can upload. It is now capped at
5 MB, 6000 px per side, and JPEG/PNG/WebP only - verified by decoding the
image header, not by trusting the filename or the client Content-Type.

Run: python manage.py test apps.students.tests.test_photo_upload_validation \
     --settings=config.settings.test
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.accounts.tests.helpers import login, make_user

ME = "/api/v1/students/me/"


def _png(width=64, height=64, mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, (width, height), "blue").save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def _noise_png(side):
    buf = io.BytesIO()
    Image.effect_noise((side, side), 128).save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


class ProfilePhotoUploadValidationTests(APITestCase):
    def setUp(self):
        self.user = make_user(role=UserRole.STUDENT)
        login(self.client, self.user)
        self.client.post(ME, {"bio": "hi"}, format="json")

    def _upload(self, upload):
        return self.client.patch(ME, {"profile_photo": upload}, format="multipart")

    def test_valid_png_is_accepted(self):
        r = self._upload(SimpleUploadedFile("me.png", _png(), content_type="image/png"))
        self.assertEqual(r.status_code, 200, r.content)

    def test_non_image_payload_is_rejected(self):
        html = b"<html><script>alert(1)</script></html>"
        r = self._upload(SimpleUploadedFile("x.png", html, content_type="image/png"))
        self.assertEqual(r.status_code, 400, r.content)

    def test_disallowed_format_is_rejected_even_with_png_content_type(self):
        buf = io.BytesIO()
        Image.new("RGB", (32, 32), "red").save(buf, format="GIF")
        r = self._upload(
            SimpleUploadedFile("x.png", buf.getvalue(), content_type="image/png")
        )
        self.assertEqual(r.status_code, 400, r.content)

    def test_oversized_file_is_rejected(self):
        big = _noise_png(3000)  # incompressible noise -> several MB
        self.assertGreater(len(big), 5 * 1024 * 1024)
        r = self._upload(SimpleUploadedFile("big.png", big, content_type="image/png"))
        self.assertEqual(r.status_code, 400, r.content)

    def test_oversized_dimensions_are_rejected(self):
        tall = _png(width=10, height=6001)  # tiny file, huge dimension
        r = self._upload(SimpleUploadedFile("tall.png", tall, content_type="image/png"))
        self.assertEqual(r.status_code, 400, r.content)
