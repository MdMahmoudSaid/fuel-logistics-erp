from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets, serializers
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission

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
    ("finance", "customerpayment"),
}

# model name -> owning module, derived from ALLOWED_ATTACHMENT_MODELS above.
# HasModulePermission.has_permission() reads `view.module` per-request
# (apps/accounts/permissions.py), so a single hardcoded class attribute here
# used to gate EVERY attachable model behind "purchasing" permission alone -
# a Finance-only role (view-only on purchasing, full rights on finance per
# the seeded Role grid) would get 403 uploading a customer-payment proof
# even once its content type was allowlisted. `module` below resolves per
# request instead, from the target model being attached.
_MODEL_MODULES = {model: app_label for app_label, model in ALLOWED_ATTACHMENT_MODELS}
_DEFAULT_MODULE = "purchasing"


class _AnyAttachableModulePermission(BasePermission):
    """`list` gate: unlike create/retrieve/update/destroy, `list` doesn't
    target one specific document/content type, so there's no single
    `module` to check the way HasModulePermission expects. A caller may
    list here as soon as they can view ANY of the modules Document can be
    attached under (purchasing, finance, ...) - get_queryset() below then
    filters the actual rows down to just the modules they're permitted to
    see, so this only decides whether the endpoint is reachable at all,
    not what it returns.
    """

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        role = request.user.role
        if role is None:
            return False
        return any(
            role.has_permission(module, "view") for module in set(_MODEL_MODULES.values())
        )


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    parser_classes = (MultiPartParser, FormParser)

    def get_permissions(self):
        if self.action == "list":
            return [_AnyAttachableModulePermission()]
        return [HasModulePermission()]

    @property
    def module(self):
        content_type_name = str(self.request.data.get("content_type_name") or "").lower()
        if content_type_name in _MODEL_MODULES:
            return _MODEL_MODULES[content_type_name]

        # retrieve/update/partial_update/destroy: no content_type_name in
        # the request body, but the target Document already exists -
        # resolve the module from what it's actually attached to instead of
        # falling back to a single hardcoded module (a Finance-only role
        # must be able to retrieve/delete a customerpayment proof it's
        # permitted to manage, without holding "purchasing" too).
        pk = self.kwargs.get("pk")
        if pk is not None:
            model_name = (
                Document.objects.filter(pk=pk).values_list("content_type__model", flat=True).first()
            )
            if model_name in _MODEL_MODULES:
                return _MODEL_MODULES[model_name]

        return _DEFAULT_MODULE

    def get_queryset(self):
        # Defense in depth alongside the allowlist below: never surface
        # documents attached to a model outside what this module is allowed
        # to manage, even if one somehow got created (e.g. via the admin) -
        # AND never surface documents from a module this caller's role
        # can't view, even though _AnyAttachableModulePermission let the
        # `list` request through because they can view at least one module.
        user = self.request.user
        if user and user.is_authenticated and user.is_superuser:
            permitted = ALLOWED_ATTACHMENT_MODELS
        else:
            role = getattr(user, "role", None)
            permitted = {
                (app_label, model)
                for app_label, model in ALLOWED_ATTACHMENT_MODELS
                if role is not None and role.has_permission(app_label, "view")
            }
        content_types = ContentType.objects.filter(
            app_label__in={app_label for app_label, _ in permitted},
            model__in={model for _, model in permitted},
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
