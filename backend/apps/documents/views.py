from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets, serializers
from rest_framework.parsers import FormParser, MultiPartParser

from apps.accounts.permissions import HasModulePermission
from .models import Document
from .serializers import DocumentSerializer


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [HasModulePermission]
    module = "purchasing"

    def perform_create(self, serializer):
        content_type_name = self.request.data.get("content_type_name")
        object_id = self.request.data.get("object_id")
        # content_type/object_id are required, non-nullable columns on
        # Document (it's a generic attachment, always attached to something).
        # Silently saving without them used to hit an unhandled IntegrityError
        # (500) instead of a clean validation error.
        if not content_type_name or not object_id:
            raise serializers.ValidationError(
                {
                    "content_type_name": "Ce champ est requis.",
                    "object_id": "Ce champ est requis.",
                }
            )
        try:
            object_id = int(object_id)
        except (TypeError, ValueError):
            raise serializers.ValidationError(
                {"object_id": "Doit être un identifiant entier."}
            )
        try:
            # Trouve le ContentType à partir du nom du modèle (ex: 'supplierorder')
            content_type = ContentType.objects.get(model=content_type_name.lower())
        except ContentType.DoesNotExist:
            raise serializers.ValidationError(
                {"content_type_name": "Type de contenu invalide."}
            )
        serializer.save(
            uploaded_by=self.request.user,
            content_type=content_type,
            object_id=object_id,
        )
