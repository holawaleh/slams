"""The signed-in user's own account, and staff management for admins.

Role rules, in one place:
  - owners manage anyone, including other owners and admins;
  - admins manage lecturers and viewers only;
  - nobody can remove or demote the last owner, or remove themselves.
"""

import re

from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth_serializers import check_password
from .permissions import get_membership
from .tenancy import Membership

ROLE_RANK = {Membership.VIEWER: 0, Membership.LECTURER: 1,
             Membership.ADMIN: 2, Membership.OWNER: 3}


def split_name(full):
    first, _, last = " ".join(full.split()).partition(" ")
    return first[:150], last[:150]


def may_manage(me, role):
    """Whether membership `me` may create, change or remove someone who
    has (or would get) `role`."""
    if me.role == Membership.OWNER:
        return True
    return me.role == Membership.ADMIN and role in (Membership.LECTURER,
                                                    Membership.VIEWER)


def require_manage(me, *roles):
    for role in roles:
        if not may_manage(me, role):
            raise PermissionDenied(
                "Only an owner can manage owners and admins." if me.can_administer
                else "Administrator privileges are required.")


def last_owner(org, membership):
    return (membership.role == Membership.OWNER and
            Membership.objects.filter(org=org, role=Membership.OWNER).count() <= 1)


# ---------------- your own account ----------------

class ProfileSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=300)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_full_name(self, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError("Enter your name.")
        return value


class ProfileView(APIView):
    """PATCH /api/me/profile/ - change your own name and email."""
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        s = ProfileSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        u = request.user
        if "full_name" in s.validated_data:
            u.first_name, u.last_name = split_name(s.validated_data["full_name"])
        if "email" in s.validated_data:
            u.email = s.validated_data["email"].strip().lower()
        u.save(update_fields=["first_name", "last_name", "email"])
        return Response({"full_name": u.get_full_name(), "email": u.email,
                         "first_name": u.first_name, "last_name": u.last_name})


class ChangePasswordView(APIView):
    """POST /api/me/password/ - requires the current password, so a
    session left open on a shared computer cannot lock its owner out."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current = request.data.get("current_password", "")
        new = request.data.get("new_password", "")
        if not request.user.check_password(current):
            return Response({"current_password": ["That is not your current password."]},
                            status=status.HTTP_400_BAD_REQUEST)
        if new == current:
            return Response({"new_password": ["Choose a password you have not just used."]},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            check_password(new, request.user)
        except ValidationError as e:
            return Response({"new_password": e.detail["password"]},
                            status=status.HTTP_400_BAD_REQUEST)
        request.user.set_password(new)
        request.user.save(update_fields=["password"])
        return Response({"detail": "Password changed."})


# ---------------- staff ----------------

class AddStaffSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=300)
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=[r for r, _ in Membership.ROLES])
    password = serializers.CharField(write_only=True)

    def validate_full_name(self, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError("Enter the staff member's name.")
        return value

    def validate_username(self, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{3,150}", value):
            raise serializers.ValidationError(
                "Use 3 or more letters, digits, dot, underscore or hyphen.")
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate(self, data):
        first, last = split_name(data["full_name"])
        check_password(data["password"], User(
            username=data["username"], email=data.get("email", ""),
            first_name=first, last_name=last))
        return data


def add_staff(request):
    """POST /api/members/ - create a staff account in this organisation
    with a temporary password the admin hands over."""
    me = get_membership(request)
    s = AddStaffSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    d = s.validated_data
    require_manage(me, d["role"])
    first, last = split_name(d["full_name"])
    with transaction.atomic():
        user = User.objects.create_user(
            username=d["username"], email=(d.get("email") or "").lower(),
            password=d["password"], first_name=first, last_name=last)
        m = Membership.objects.create(user=user, org=me.org, role=d["role"],
                                      is_default=True)
    return m


def reset_staff_password(request, target):
    me = get_membership(request)
    require_manage(me, target.role)
    if target.user_id == request.user.id:
        raise ValidationError("Use Change password for your own account.")
    new = request.data.get("password", "")
    try:
        check_password(new, target.user)
    except ValidationError as e:
        raise ValidationError({"password": e.detail["password"]})
    target.user.set_password(new)
    target.user.save(update_fields=["password"])


def check_role_change(request, target, new_role):
    me = get_membership(request)
    if target.user_id == request.user.id and new_role != target.role:
        raise ValidationError("You cannot change your own role.")
    require_manage(me, target.role, new_role)
    if new_role != Membership.OWNER and last_owner(me.org, target):
        raise ValidationError("The organisation needs at least one owner.")


def check_remove(request, target):
    me = get_membership(request)
    if target.user_id == request.user.id:
        raise ValidationError("You cannot remove yourself.")
    require_manage(me, target.role)
    if last_owner(me.org, target):
        raise ValidationError("The organisation needs at least one owner.")
