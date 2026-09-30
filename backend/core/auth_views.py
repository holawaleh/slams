from datetime import timedelta
from django.db.models import Count
from django.utils import timezone
from rest_framework import status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .tenancy import Organization, Membership, Invitation
from .auth_serializers import (RegisterSerializer, AcceptInviteSerializer,
                               InvitationSerializer, MembershipSerializer,
                               OrganizationSerializer)
from .permissions import IsOrgMember, IsOrgAdmin, get_membership
from . import account
from .pagination import LargePagination
from .views import audit


class SignupThrottle(AnonRateThrottle):
    """Open registration needs a ceiling or the table fills with junk."""
    rate = "5/hour"


def tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class RegisterView(APIView):
    # No authentication at all, not just AllowAny. With JWT auth enabled,
    # a stale token left in the browser is rejected with a 401 before
    # AllowAny is even consulted, and sign-up becomes impossible.
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [SignupThrottle]

    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        result = s.save()
        return Response({
            "tokens": tokens_for(result["user"]),
            "username": result["user"].username,
            "org": {"name": result["org"].name, "slug": result["org"].slug},
            "role": Membership.OWNER,
        }, status=status.HTTP_201_CREATED)


class AcceptInviteView(APIView):
    authentication_classes = []     # see RegisterView
    permission_classes = [AllowAny]
    throttle_classes = [SignupThrottle]

    def post(self, request):
        s = AcceptInviteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        result = s.save()
        return Response({
            "tokens": tokens_for(result["user"]),
            "org": {"name": result["org"].name, "slug": result["org"].slug},
        }, status=status.HTTP_200_OK)


class MeView(APIView):
    """What the frontend calls after login to learn who it is talking to."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        m = get_membership(request)
        if request.user.is_superuser:
            organizations = [
                {"slug": o.slug, "name": o.name, "role": Membership.OWNER,
                 "is_default": bool(m and o.pk == m.org_id)}
                for o in Organization.objects.filter(active=True).order_by("name")]
        else:
            organizations = [
                {"slug": x.org.slug, "name": x.org.name, "role": x.role,
                 "is_default": x.is_default}
                for x in Membership.objects.select_related("org").filter(
                    user=request.user, org__active=True)]
        return Response({
            "user": {
                "id": request.user.id,
                "username": request.user.username,
                "email": request.user.email,
                "first_name": request.user.first_name,
                "last_name": request.user.last_name,
                "is_platform_admin": request.user.is_superuser,
            },
            "current_org": ({"slug": m.org.slug, "name": m.org.name,
                             "role": m.role, "term": m.org.term,
                             "timezone": m.org.timezone} if m else None),
            "organizations": organizations,
        })


class OrganizationView(APIView):
    """The caller's own organization. There is no list endpoint - an org
    is never visible to anyone outside it."""
    permission_classes = [IsOrgMember]

    def get(self, request):
        m = get_membership(request)
        org = Organization.objects.filter(pk=m.org_id).annotate(
            member_count=Count("memberships", distinct=True),
            student_count=Count("students", distinct=True),
            device_count=Count("devices", distinct=True)).first()
        return Response(OrganizationSerializer(org).data)

    def patch(self, request):
        m = get_membership(request)
        if not m.can_administer:
            return Response({"detail": "Administrator privileges required."},
                            status=status.HTTP_403_FORBIDDEN)
        s = OrganizationSerializer(m.org, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


class MembershipViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin,
                        mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Manage who is in this organization. The role rules live in
    core/account.py so every path applies the same ones."""
    serializer_class = MembershipSerializer
    permission_classes = [IsOrgMember]
    pagination_class = LargePagination

    def get_queryset(self):
        m = get_membership(self.request)
        return Membership.objects.select_related("user", "org").filter(
            org=m.org).order_by("user__first_name", "user__username")

    def create(self, request):
        """Add a staff member with a temporary password."""
        m = account.add_staff(request)
        audit(request, "staff_add", f"{m.user.username} as {m.role}")
        return Response(MembershipSerializer(m).data,
                        status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        target = self.get_object()
        new_role = serializer.validated_data.get("role", target.role)
        account.check_role_change(self.request, target, new_role)
        serializer.save()
        if new_role != target.role:
            audit(self.request, "staff_role",
                  f"{target.user.username}: {target.role} -> {new_role}")

    def perform_destroy(self, instance):
        account.check_remove(self.request, instance)
        audit(self.request, "staff_remove",
              f"{instance.user.username} ({instance.role})")
        instance.delete()

    @action(detail=True, methods=["post"])
    def set_password(self, request, pk=None):
        """Give a staff member a new temporary password, e.g. when they
        have forgotten theirs."""
        target = self.get_object()
        account.reset_staff_password(request, target)
        audit(request, "staff_password", target.user.username)
        return Response({"detail": "Password changed."})

    @action(detail=False, methods=["post"])
    def switch(self, request):
        """Change which org this user lands in by default."""
        slug = request.data.get("slug")
        target = Membership.objects.filter(
            user=request.user, org__slug=slug, org__active=True).first()
        if not target:
            return Response({"detail": "Not a member of that organization."},
                            status=status.HTTP_404_NOT_FOUND)
        Membership.objects.filter(user=request.user).update(is_default=False)
        target.is_default = True
        target.save(update_fields=["is_default"])
        return Response(MembershipSerializer(target).data)


class InvitationViewSet(viewsets.ModelViewSet):
    serializer_class = InvitationSerializer
    permission_classes = [IsOrgAdmin]

    def get_queryset(self):
        m = get_membership(self.request)
        return Invitation.objects.filter(org=m.org).order_by("-created_at")

    def perform_create(self, serializer):
        m = get_membership(self.request)
        serializer.save(org=m.org, invited_by=self.request.user,
                        expires_at=timezone.now() + timedelta(days=14))

