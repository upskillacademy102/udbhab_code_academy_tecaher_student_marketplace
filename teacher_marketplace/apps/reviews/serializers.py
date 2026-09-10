"""Serializers for the reviews app."""

from rest_framework import serializers

from apps.reviews.models import Review


class ReviewSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    teacher_id = serializers.UUIDField(source="teacher.id", read_only=True)

    class Meta:
        model = Review
        fields = (
            "id",
            "author_name",
            "teacher_id",
            "rating",
            "text",
            "status",
            "created_at",
        )
        read_only_fields = fields

    def get_author_name(self, obj) -> str:
        name = obj.author.get_full_name() or "Student"
        # only show first name + last initial
        parts = name.split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[-1][0]}."
        return parts[0] if parts else "Student"


class ReviewWriteSerializer(serializers.Serializer):
    teacher_id = serializers.UUIDField()
    lead_id = serializers.UUIDField(required=False)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    text = serializers.CharField(required=False, allow_blank=True, max_length=2000)
