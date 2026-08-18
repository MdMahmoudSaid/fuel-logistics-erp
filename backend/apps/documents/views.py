from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets, serializers
from rest_framework.parsers import FormParser, MultiPartParser

from apps.accounts.permissions import HasModulePermission
from .models import Document
from .serializers import DocumentSerializer

# Models this endpoint is allowed to attach a Document to, keyed as they'd
# appear in ContentType.model (app_label, model). Without this allowlist any
# authenticated user holding purchasing "create" rights could point a Document
# at an arbitrary model in the whole project (accounts.User, accounts.Role,
# ...) with an arbitrary object_id, since GenericForeignKey enforces no
# referential integrity of its own. Extend this as later phases add more
# attachable entities (spec §35: truck, trip, delivery, customer, invoice,
# payment, transporter, expense...).
ALLOWED_ATTACHMENT_MODELS = {
    ("purchasing", "supplierorder"),
    ("purchasing", "cessionletter"),
}


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [HasModulePermission]
    module = "purchasing"

    def get_queryset(self):
        # Defense in depth alongside the allowlist below: never surface
        # documents attached to a model outside what this module is allowed
        # to manage, even if one somehow got created (e.g. via the admin).
        content_types = ContentType.objects.filter(
            app_label__in={app_label for app_label, _ in ALLOWED_ATTACHMENT_MODELS},
            model__in={model for _, model in ALLOWED_ATTACHMENT_MODELS},
        )
        return Document.objects.filter(content_type__in=content_types)

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

        model_name = content_type_name.lower()
        allowed_model_names = {model for _, model in ALLOWED_ATTACHMENT_MODELS}
        if model_name not in allowed_model_names:
            raise serializers.ValidationError(
                {"content_type_name": "Type de contenu non autorisé."}
            )
        try:
            # Trouve le ContentType à partir du nom du modèle (ex: 'supplierorder')
            content_type = ContentType.objects.get(model=model_name)
        except ContentType.DoesNotExist:
            raise serializers.ValidationError(
                {"content_type_name": "Type de contenu invalide."}
            )

        model_cls = content_type.model_class()
        if not model_cls.objects.filter(pk=object_id).exists():
            raise serializers.ValidationError({"object_id": "Objet introuvable."})

        serializer.save(
            uploaded_by=self.request.user,
            content_type=content_type,
            object_id=object_id,
        )
