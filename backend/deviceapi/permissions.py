from rest_framework.permissions import BasePermission


class IsDevice(BasePermission):
    """Passes only for a request carrying a valid device token."""
    message = "A valid device token is required."

    def has_permission(self, request, view):
        return getattr(request, "device", None) is not None
