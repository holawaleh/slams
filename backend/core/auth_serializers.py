import re
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers
from .tenancy import Organization, Membership, Invitation


def check_password(password, user):
    """Run Django's validators and report failures against the password
    field, so the form can show them under the right input."""
    try:
        validate_password(password, user)
    except DjangoValidationError as e:
        raise serializers.ValidationError({"password": list(e.messages)})


def unique_slug(name):
    base = slugify(name)[:40] or "org"
    slug, n = base, 1
    while Organization.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"[:48]
    return slug


class RegisterSerializer(serializers.Serializer):
    """Creates a user, their institution, and an owner membership.

    Sign-up asks only for the school, its address, a username, an email
    and a password. The owner can add their name later under Settings."""
    username      = serializers.CharField(max_length=150)
    email         = serializers.EmailField()
    password      = serializers.CharField(write_only=True, min_length=8)
    org_name      = serializers.CharField(max_length=128)
    address       = serializers.CharField(max_length=255)
    country       = serializers.CharField(max_length=64, required=False,
                                          allow_blank=True)
    term          = serializers.CharField(max_length=16, required=False,
                                          default="2025/2026-1")

    def validate_username(self, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{3,150}", value):
            raise serializers.ValidationError(
                "Use 3 or more letters, digits, dot, underscore or hyphen.")
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError(
                "That username is already taken.")
        return value

    def validate_email(self, value):
        return value.strip().lower()

    def validate_org_name(self, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError("Enter the school's name.")
        return value

    def validate_address(self, value):
        value = " ".join(value.split())
        if len(value) < 5:
            raise serializers.ValidationError("Enter the school's address.")
        return value

    def validate(self, data):
        probe = User(username=data.get("username", ""),
                     email=data.get("email", ""))
        check_password(data["password"], probe)
        return data

    @transaction.atomic
    def create(self, validated):
        user = User.objects.create_user(
            username=validated["username"],
            email=validated["email"],
            password=validated["password"])
        org = Organization.objects.create(
            name=validated["org_name"],
            address=validated["address"],
            slug=unique_slug(validated["org_name"]),
            country=validated.get("country", ""),
            term=validated.get("term") or "2025/2026-1")
        Membership.objects.create(user=user, org=org,
                                  role=Membership.OWNER, is_default=True)
        return {"user": user, "org": org}


class AcceptInviteSerializer(serializers.Serializer):
    """Joins an existing organization instead of creating one. Works for
    a brand new user or one who already has an account elsewhere."""
    code       = serializers.CharField(max_length=64)
    username   = serializers.CharField(max_length=150, required=False,
                                       help_text="Required for a new account")
    password   = serializers.CharField(write_only=True, min_length=8,
                                       required=False)
    first_name = serializers.CharField(max_length=64, required=False)
    last_name  = serializers.CharField(max_length=64, required=False)

    def validate_code(self, value):
        try:
            inv = Invitation.objects.select_related("org").get(code=value)
        except Invitation.DoesNotExist:
            raise serializers.ValidationError("Invalid invitation.")
        if inv.accepted:
            raise serializers.ValidationError("Invitation already used.")
        if inv.expires_at < timezone.now():
            raise serializers.ValidationError("Invitation has expired.")
        self.invitation = inv
        return value

    @transaction.atomic
    def create(self, validated):
        inv = self.invitation
        email = inv.email.strip().lower()
        # An existing account is matched by the invited email address.
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            username = (validated.get("username") or "").strip().lower()
            if not username:
                raise serializers.ValidationError(
                    {"username": "Required for a new account."})
            if not re.fullmatch(r"[a-z0-9._-]{3,150}", username):
                raise serializers.ValidationError(
                    {"username": "Use 3 or more letters, digits, "
                                 "dot, underscore or hyphen."})
            if User.objects.filter(username__iexact=username).exists():
                raise serializers.ValidationError(
                    {"username": "That username is already taken."})
            if not validated.get("password"):
                raise serializers.ValidationError(
                    {"password": "Required for a new account."})
            check_password(validated["password"], User(
                username=username, email=email,
                first_name=validated.get("first_name", ""),
                last_name=validated.get("last_name", "")))
            user = User.objects.create_user(
                username=username, email=email,
                password=validated["password"],
                first_name=validated.get("first_name", ""),
                last_name=validated.get("last_name", ""))
        has_default = Membership.objects.filter(
            user=user, is_default=True).exists()
        Membership.objects.get_or_create(
            user=user, org=inv.org,
            defaults={"role": inv.role, "is_default": not has_default})
        inv.accepted = True
        inv.save(update_fields=["accepted"])
        return {"user": user, "org": inv.org}


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = ("id", "email", "role", "code", "accepted",
                  "expires_at", "created_at")
        read_only_fields = ("code", "accepted", "created_at")


class MembershipSerializer(serializers.ModelSerializer):
    username   = serializers.CharField(source="user.username", read_only=True)
    email      = serializers.CharField(source="user.email", read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)
    full_name  = serializers.SerializerMethodField()
    org_name   = serializers.CharField(source="org.name", read_only=True)
    org_slug   = serializers.CharField(source="org.slug", read_only=True)

    class Meta:
        model = Membership
        fields = ("id", "user", "username", "full_name", "email", "last_login",
                  "org", "org_name",
                  "org_slug", "role", "is_default", "joined_at")
        read_only_fields = ("user", "org", "joined_at")

    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()


class OrganizationSerializer(serializers.ModelSerializer):
    member_count  = serializers.IntegerField(read_only=True)
    student_count = serializers.IntegerField(read_only=True)
    device_count  = serializers.IntegerField(read_only=True)

    class Meta:
        model = Organization
        fields = ("id", "name", "slug", "address", "country", "term", "timezone",
                  "active", "created_at", "max_devices", "max_students",
                  "member_count", "student_count", "device_count")
        read_only_fields = ("slug", "active", "created_at",
                            "max_devices", "max_students")


