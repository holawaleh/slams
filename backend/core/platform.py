"""The platform administrator's view: every school, user, reader and
action across the whole system, without going through Django admin.

Only superusers get in. Everything here crosses the tenant boundary on
purpose, so nothing in this module may be reachable by anyone else.
Changes made here are written to the affected school's audit log,
signed "(platform admin)", so the school can see who touched its data.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, IntegerField, Max, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth_serializers import check_password
from .models import (AttendanceRecord, AuditLog, Card, ClassSession, Course, Device,
                     Student, TapEvent)
from .pagination import StandardPagination
from .tenancy import Membership, Organization

ONLINE = timedelta(minutes=5)      # same rule as the Devices page


class IsPlatformAdmin(permissions.BasePermission):
    message = "Only the platform administrator can see this."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_superuser)


def platform_audit(request, org, action_name, subject="", detail=""):
    """Record a platform action in the school it affected."""
    from .views import client_ip
    u = request.user
    AuditLog.objects.create(
        org=org, actor=u,
        actor_label=f"{u.get_full_name().strip() or u.username} (platform admin)"[:200],
        action=action_name, subject=str(subject)[:200], detail=detail,
        ip=client_ip(request))


def user_label(user):
    name = user.get_full_name().strip()
    return f"{name} ({user.username})" if name else user.username


def _count(model, since=None, field="created_at", **filters):
    """Rows of `model` per organisation, as a subquery. Separate
    subqueries avoid the row multiplication of several JOIN counts."""
    qs = model.objects.filter(org=OuterRef("pk"), **filters)
    if since is not None:
        qs = qs.filter(**{f"{field}__gte": since})
    sub = qs.order_by().values("org").annotate(c=Count("pk")).values("c")
    return Coalesce(Subquery(sub, output_field=IntegerField()), Value(0))


def _latest(model, field):
    sub = (model.objects.filter(org=OuterRef("pk")).order_by()
           .values("org").annotate(m=Max(field)).values("m"))
    return Subquery(sub)


def last_owner_of(user):
    """Schools where this user is the only owner."""
    owned = Membership.objects.filter(user=user, role=Membership.OWNER).values("org")
    return list(Organization.objects.filter(pk__in=owned).annotate(
        owners=Count("memberships", filter=Q(memberships__role=Membership.OWNER))
    ).filter(owners__lte=1).values_list("name", flat=True))


# ---------------- summary ----------------

class SummaryView(APIView):
    """GET /api/platform/summary/ - the whole system at a glance."""
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        now = timezone.now()
        d1, d7, d30 = (now - timedelta(days=n) for n in (1, 7, 30))
        start = (now - timedelta(days=29)).date()

        taps_by_day = dict(
            TapEvent.objects.filter(received_at__date__gte=start)
            .annotate(d=TruncDate("received_at")).values("d")
            .annotate(c=Count("pk")).values_list("d", "c"))
        signins_by_day = dict(
            AuditLog.objects.filter(action="sign_in", created_at__date__gte=start)
            .annotate(d=TruncDate("created_at")).values("d")
            .annotate(c=Count("pk")).values_list("d", "c"))
        days = [start + timedelta(days=i) for i in range(30)]

        top = (Organization.objects.annotate(taps=_count(TapEvent, d30, "received_at"))
               .filter(taps__gt=0).order_by("-taps")[:5])

        return Response({
            "schools": {
                "total": Organization.objects.count(),
                "active": Organization.objects.filter(active=True).count(),
                "new_30d": Organization.objects.filter(created_at__gte=d30).count(),
            },
            "users": {
                "total": User.objects.count(),
                "active": User.objects.filter(is_active=True).count(),
                "signed_in_7d": User.objects.filter(last_login__gte=d7).count(),
                "new_30d": User.objects.filter(date_joined__gte=d30).count(),
            },
            "students": Student.objects.count(),
            "cards": Card.objects.filter(active=True).count(),
            "courses": Course.objects.count(),
            "readers": {
                "total": Device.objects.filter(active=True).count(),
                "online": Device.objects.filter(active=True,
                                                last_seen__gte=now - ONLINE).count(),
            },
            "taps": {
                "today": TapEvent.objects.filter(received_at__gte=d1).count(),
                "d7": TapEvent.objects.filter(received_at__gte=d7).count(),
                "d30": TapEvent.objects.filter(received_at__gte=d30).count(),
            },
            "attendance_30d": AttendanceRecord.objects.filter(tapped_at__gte=d30).count(),
            "daily": [{"date": d.isoformat(), "taps": taps_by_day.get(d, 0),
                       "sign_ins": signins_by_day.get(d, 0)} for d in days],
            "top_schools": [{"id": o.id, "name": o.name, "taps": o.taps} for o in top],
        })


# ---------------- schools ----------------

class PlatformOrgSerializer(serializers.ModelSerializer):
    member_count  = serializers.IntegerField(read_only=True)
    student_count = serializers.IntegerField(read_only=True)
    device_count  = serializers.IntegerField(read_only=True)
    course_count  = serializers.IntegerField(read_only=True)
    taps_30d      = serializers.IntegerField(read_only=True)
    last_tap      = serializers.DateTimeField(read_only=True)
    last_action   = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Organization
        fields = ("id", "name", "slug", "address", "country", "term", "timezone",
                  "active", "created_at", "max_devices", "max_students",
                  "member_count", "student_count", "device_count", "course_count",
                  "taps_30d", "last_tap", "last_action")
        read_only_fields = ("slug", "created_at")


class PlatformOrgViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         mixins.UpdateModelMixin, mixins.DestroyModelMixin,
                         viewsets.GenericViewSet):
    serializer_class = PlatformOrgSerializer
    permission_classes = [IsPlatformAdmin]
    pagination_class = StandardPagination
    search_fields = ["name", "slug", "address", "country"]
    filterset_fields = ["active"]
    ordering_fields = ["name", "created_at", "taps_30d", "student_count", "last_tap"]
    ordering = ["name"]

    def get_queryset(self):
        d30 = timezone.now() - timedelta(days=30)
        return Organization.objects.annotate(
            member_count=_count(Membership, field="joined_at"),
            student_count=_count(Student),
            device_count=_count(Device, active=True),
            course_count=_count(Course),
            taps_30d=_count(TapEvent, d30, "received_at"),
            last_tap=_latest(TapEvent, "received_at"),
            last_action=_latest(AuditLog, "created_at"),
        )

    def retrieve(self, request, pk=None):
        org = self.get_object()
        data = self.get_serializer(org).data
        now = timezone.now()
        data["members"] = [{
            "id": m.id, "user": m.user_id, "username": m.user.username,
            "full_name": m.user.get_full_name(), "email": m.user.email,
            "role": m.role, "is_active": m.user.is_active,
            "last_login": m.user.last_login, "joined_at": m.joined_at,
        } for m in org.memberships.select_related("user").order_by("role", "user__username")]
        data["readers"] = [{
            "id": d.id, "name": d.name, "hardware_id": d.hardware_id,
            "venue": d.venue.code if d.venue_id else None, "firmware": d.firmware,
            "last_seen": d.last_seen,
            "online": bool(d.last_seen and d.last_seen > now - ONLINE),
        } for d in Device.objects.filter(org=org, active=True).select_related("venue")]
        return Response(data)

    def perform_update(self, serializer):
        org = serializer.instance
        before = {k: getattr(org, k) for k in serializer.validated_data}
        serializer.save()
        changed = {k: v for k, v in serializer.validated_data.items() if before[k] != v}
        if "active" in changed:
            platform_audit(self.request, org,
                           "org_enable" if changed.pop("active") else "org_disable",
                           subject=org.name)
        if changed:
            platform_audit(self.request, org, "org_update", subject=org.name,
                           detail="; ".join(f"{k}: {before[k]!r} -> {v!r}"
                                            for k, v in changed.items()))

    def destroy(self, request, pk=None):
        """Delete a school and everything in it. The caller must repeat
        the school's short code, so a slip of the mouse cannot do it."""
        org = self.get_object()
        if request.query_params.get("confirm") != org.slug:
            raise ValidationError({"confirm": f'Type "{org.slug}" to confirm.'})
        with transaction.atomic():
            # Readers keep their hardware ids unique across schools; free
            # them first so the units can be paired somewhere else.
            Device.objects.filter(org=org).update(hardware_id=None)
            # Lectures and cards protect the courses, venues and students
            # they point at, so clear them out before the cascade.
            for model in (AttendanceRecord, TapEvent, ClassSession, Card):
                model.objects.filter(org=org).delete()
            org.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------- users ----------------

class PlatformUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    memberships = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "full_name", "email",
                  "is_active", "is_superuser", "date_joined", "last_login",
                  "memberships")
        read_only_fields = ("date_joined", "last_login")

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_memberships(self, obj):
        return [{"id": m.id, "org": m.org_id, "org_name": m.org.name,
                 "org_slug": m.org.slug, "org_active": m.org.active, "role": m.role}
                for m in obj.memberships.all()]

    def validate_username(self, value):
        value = value.strip().lower()
        if User.objects.filter(username__iexact=value).exclude(
                pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate_email(self, value):
        return value.strip().lower()


class PlatformUserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          mixins.UpdateModelMixin, mixins.DestroyModelMixin,
                          viewsets.GenericViewSet):
    serializer_class = PlatformUserSerializer
    permission_classes = [IsPlatformAdmin]
    pagination_class = StandardPagination
    search_fields = ["username", "first_name", "last_name", "email",
                     "memberships__org__name"]
    filterset_fields = ["is_active", "is_superuser"]
    ordering_fields = ["username", "date_joined", "last_login"]
    ordering = ["-date_joined"]

    def get_queryset(self):
        qs = User.objects.prefetch_related("memberships__org")
        org = self.request.query_params.get("org")
        if org:
            qs = qs.filter(memberships__org_id=org)
        return qs.distinct()

    def _guard_self_and_last(self, user, data):
        me = self.request.user
        if user.pk == me.pk and (data.get("is_active") is False
                                 or data.get("is_superuser") is False):
            raise ValidationError("You cannot disable your own account or remove "
                                  "your own platform access.")
        if user.is_superuser and (data.get("is_superuser") is False
                                  or data.get("is_active") is False):
            others = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk)
            if not others.exists():
                raise ValidationError("This is the only active platform administrator.")

    def perform_update(self, serializer):
        user = serializer.instance
        data = serializer.validated_data
        self._guard_self_and_last(user, data)
        before = {k: getattr(user, k) for k in data}
        serializer.save()
        changed = {k: v for k, v in data.items() if before[k] != v}
        orgs = [m.org for m in user.memberships.select_related("org")]
        if "is_active" in changed:
            for org in orgs:
                platform_audit(self.request, org,
                               "user_enable" if changed["is_active"] else "user_disable",
                               subject=user_label(user))
            changed.pop("is_active")
        if changed:
            detail = ", ".join(k.replace("_", " ") for k in changed)
            for org in orgs:
                platform_audit(self.request, org, "user_update",
                               subject=user_label(user), detail=detail)

    def destroy(self, request, pk=None):
        user = self.get_object()
        if user.pk == request.user.pk:
            raise ValidationError("You cannot delete your own account.")
        self._guard_self_and_last(user, {"is_active": False})
        sole = last_owner_of(user)
        if sole:
            raise ValidationError(
                f"{user.username} is the only owner of {', '.join(sole)}. "
                "Make someone else an owner first, or delete the school.")
        label = user_label(user)
        orgs = [m.org for m in user.memberships.select_related("org")]
        with transaction.atomic():
            user.delete()
            for org in orgs:
                platform_audit(request, org, "user_delete", subject=label)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def set_password(self, request, pk=None):
        user = self.get_object()
        new = request.data.get("password", "")
        try:
            check_password(new, user)
        except ValidationError as e:
            raise ValidationError({"password": e.detail["password"]})
        user.set_password(new)
        user.save(update_fields=["password"])
        for m in user.memberships.select_related("org"):
            platform_audit(request, m.org, "staff_password", subject=user_label(user))
        return Response({"detail": "Password changed."})

    @action(detail=True, methods=["post"])
    def add_membership(self, request, pk=None):
        """Put this user in a school with a role."""
        user = self.get_object()
        org = Organization.objects.filter(pk=request.data.get("org")).first()
        role = request.data.get("role")
        if org is None:
            raise ValidationError({"org": "Choose a school."})
        if role not in dict(Membership.ROLES):
            raise ValidationError({"role": "Choose a role."})
        m, created = Membership.objects.get_or_create(
            user=user, org=org, defaults={"role": role,
                                          "is_default": not user.memberships.exists()})
        if not created:
            raise ValidationError(f"{user.username} is already in {org.name}.")
        platform_audit(request, org, "staff_add", subject=user_label(user),
                       detail=f"as {role}")
        return Response(self.get_serializer(user).data, status=status.HTTP_201_CREATED)


class PlatformMembershipViewSet(mixins.UpdateModelMixin, mixins.DestroyModelMixin,
                                viewsets.GenericViewSet):
    """Change someone's role in a school, or take them out of it."""
    permission_classes = [IsPlatformAdmin]
    queryset = Membership.objects.select_related("user", "org")

    class _S(serializers.ModelSerializer):
        class Meta:
            model = Membership
            fields = ("id", "role")

    serializer_class = _S

    @staticmethod
    def _is_last_owner(m):
        return (m.role == Membership.OWNER and
                Membership.objects.filter(org=m.org_id, role=Membership.OWNER).count() <= 1)

    def perform_update(self, serializer):
        m = serializer.instance
        new = serializer.validated_data.get("role", m.role)
        if new != Membership.OWNER and self._is_last_owner(m):
            raise ValidationError("The school needs at least one owner.")
        old = m.role
        serializer.save()
        if new != old:
            platform_audit(self.request, m.org, "staff_role",
                           subject=user_label(m.user), detail=f"{old} -> {new}")

    def perform_destroy(self, m):
        if self._is_last_owner(m):
            raise ValidationError("The school needs at least one owner.")
        platform_audit(self.request, m.org, "staff_remove",
                       subject=user_label(m.user), detail=f"was {m.role}")
        m.delete()


# ---------------- readers ----------------

class PlatformDeviceSerializer(serializers.ModelSerializer):
    org_name = serializers.CharField(source="org.name", read_only=True)
    venue_code = serializers.CharField(source="venue.code", read_only=True, default=None)
    online = serializers.SerializerMethodField()
    taps_30d = serializers.IntegerField(read_only=True)

    class Meta:
        model = Device
        fields = ("id", "name", "hardware_id", "org", "org_name", "venue_code",
                  "firmware", "last_seen", "queue_depth", "active", "online",
                  "taps_30d")
        read_only_fields = fields

    def get_online(self, obj):
        return bool(obj.last_seen and obj.last_seen > timezone.now() - ONLINE)


class PlatformDeviceViewSet(mixins.ListModelMixin, mixins.DestroyModelMixin,
                            viewsets.GenericViewSet):
    serializer_class = PlatformDeviceSerializer
    permission_classes = [IsPlatformAdmin]
    pagination_class = StandardPagination
    search_fields = ["name", "hardware_id", "org__name"]
    filterset_fields = ["org", "active"]
    ordering_fields = ["name", "last_seen", "org__name"]
    ordering = ["org__name", "name"]

    def get_queryset(self):
        d30 = timezone.now() - timedelta(days=30)
        return Device.objects.select_related("org", "venue").filter(active=True).annotate(
            taps_30d=Count("taps", filter=Q(taps__received_at__gte=d30)))

    def perform_destroy(self, device):
        """Same as removing it inside the school: it stops working, and
        its hardware id is freed so it can be paired again."""
        import secrets
        hw = device.hardware_id
        device.active = False
        device.hardware_id = None
        device.token = secrets.token_urlsafe(32)
        device.name = f"{device.name} (removed {timezone.now():%Y-%m-%d %H:%M})"[:64]
        device.save()
        platform_audit(self.request, device.org, "device_remove",
                       subject=f"reader {device.name}" + (f" ({hw})" if hw else ""),
                       detail="by the platform administrator")


# ---------------- activity ----------------

class PlatformActivitySerializer(serializers.ModelSerializer):
    org_name = serializers.CharField(source="org.name", read_only=True)
    actor_name = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ("id", "org", "org_name", "actor", "actor_name", "action",
                  "description", "ip", "created_at")
        read_only_fields = fields

    def get_actor_name(self, obj):
        return obj.actor_label or (obj.actor.username if obj.actor_id else "")

    def get_description(self, obj):
        from .audit_text import describe
        return describe(obj)


class PlatformActivityViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Every school's audit log in one list."""
    serializer_class = PlatformActivitySerializer
    permission_classes = [IsPlatformAdmin]
    pagination_class = StandardPagination
    queryset = AuditLog.objects.select_related("org", "actor")
    filterset_fields = ["org", "action", "actor"]
    search_fields = ["subject", "detail", "actor_label", "actor__username", "org__name"]
    ordering = ["-created_at"]
