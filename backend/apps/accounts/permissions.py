from rest_framework.permissions import BasePermission

ACTION_MAP = {
    "list": "view",
    "retrieve": "view",
    "create": "create",
    "update": "edit",
    "partial_update": "edit",
    "destroy": "cancel",
}


class HasModulePermission(BasePermission):
    """Gate ViewSet actions by the caller's Role permission matrix.

    Set `module = "<one of Role.MODULES>"` as a class attribute on any
    ViewSet using this permission class. Superusers bypass the check.
    """

    module: str | None = None

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        module = getattr(view, "module", self.module)
        action = ACTION_MAP.get(view.action, view.action)

        role = request.user.role
        if role is None or module is None:
            return False
        return role.has_permission(module, action)
