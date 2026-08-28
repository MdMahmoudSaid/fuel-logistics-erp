from rest_framework import serializers
from .models import Document
from .validators import validate_image_upload

class DocumentSerializer(serializers.ModelSerializer):
    uploaded_by_email = serializers.EmailField(source="uploaded_by.email", read_only=True)

    def validate_file(self, value):
        return validate_image_upload(value)

    class Meta:
        model = Document
        fields = [
            "id", "file", "document_type", "reference", 
            "uploaded_by", "uploaded_by_email", "created_at"
        ]
        read_only_fields = ["id", "uploaded_by", "uploaded_by_email", "created_at"]
