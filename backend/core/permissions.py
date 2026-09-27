from rest_framework import permissions, exceptions
from .tenancy import Membership


def get_membership(request):
    """Resolve which organization this request acts within.

    Read from the database every time rather than trusting a token claim,
    so revoking a membership takes effect immediately. An optional X-Org
    header allows switching, but only to an org the user belongs to."""
    if not request.user.is_authenticated:
        return None
    cached = getattr(request, "_membership", None)
    if cached is not None:
        return cached

    qs = Membership.objects.select_related("org").filter(
        user=request.user, org__active=True)
    slug = request.headers.get("X-Org")
    m = qs.filter(org__slug=slug).first() if slug else \
        (qs.filter(is_default=True).first() or qs.first())

    request._membership = m
    return m


class IsOrgMember(permissions.BasePermission):
    """Baseline: the caller belongs to an active organization."""
    message = "You do not belong to an active organization."

    def has_permission(self, request, view):
        return get_membership(request) is not None


class IsOrgAdmin(permissions.BasePermission):
    """Owner or admin of the current org."""
    message = "Administrator privileges are required."

    def has_permission(self, request, view):
        m = get_membership(request)
        return m is not None and m.can_administer


class IsOrgAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        m = get_membership(request)
        if m is None:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return m.can_administer


class IsLecturerOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        m = get_membership(request)
        return m is not None and m.role in (
            Membership.OWNER, Membership.ADMIN, Membership.LECTURER)

    def has_object_permission(self, request, view, obj):
        m = get_membership(request)
        if m is None or obj.org_id != m.org_id:
            return False
        if m.can_administer:
            return True
        course = getattr(obj, "course", None)
        return course is not None and course.lecturer_id == request.user.id


class TenantScopedMixin:
    """Every tenant viewset inherits this. Scoping lives here rather than
    in each view, because one forgotten filter is a data leak."""
    permission_classes = [IsOrgMember]

    @property
    def org(self):
        m = get_membership(self.request)
        if m is None:
            raise exceptions.PermissionDenied("No organization for this user.")
        return m.org

    def get_queryset(self):
        return super().get_queryset().filter(org=self.org)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = self.org
        return ctx

    def perform_create(self, serializer):
        serializer.save(org=self.org)
