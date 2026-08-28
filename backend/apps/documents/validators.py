from pathlib import Path

from rest_framework import serializers


ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_UPLOAD_ERROR = "Seules les images JPG, JPEG, PNG ou WEBP sont autorisées."


def validate_image_upload(file):
    content_type = str(getattr(file, "content_type", "") or "").lower()
    extension = Path(getattr(file, "name", "")).suffix.lower()
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES or extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise serializers.ValidationError(IMAGE_UPLOAD_ERROR)
    return file
