from datetime import timedelta, timezone as dt_timezone

import django_filters
from django.db import transaction
from django.db.models import (Count, IntegerField, Max, OuterRef, Q,
                              ProtectedError, Subquery, Value)
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import (Student, Card, Venue, Course, Enrollment, Device,
                     TimetableSlot, ClassSession, TapEvent,
                     AttendanceRecord, AuditLog)
from .serializers import (StudentSerializer, CardSerializer, VenueSerializer,
                          CourseSerializer, EnrollmentSerializer,
                          DeviceSerializer, TimetableSlotSerializer,
                          ClassSessionSerializer, TapEventSerializer,
                          AttendanceRecordSerializer, AuditLogSerializer,
                          BindCardSerializer, clean_uid)
from .reports import held_sessions, local_day_range
from .permissions import (TenantScopedMixin, IsOrgAdmin, IsOrgAdminOrReadOnly,
                          IsLecturerOrAdmin, get_membership)
from .pagination import StandardPagination, LargePagination


def client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")


def destroy_or_conflict(view, request, what):
    """Delete, or explain why not. Rows with attendance history are
    protected, and a raw ProtectedError would surface as a 500."""
    try:
        return viewsets.ModelViewSet.destroy(view, request)
    except ProtectedError:
        return Response(
            {"detail": f"This {what} has lecture or attendance history and "
                       f"cannot be deleted."},
            status=status.HTTP_409_CONFLICT)


def audit(request, action_name, detail):
    m = get_membership(request)
    if m is None:
        return
    AuditLog.objects.create(
        org=m.org,
        actor=request.user if request.user.is_authenticated else None,
        action=action_name, detail=detail, ip=client_ip(request))


def bind_card(request, org, uid, student, replace=False):
    """Give a card to a student. The one place a card is ever bound, so
    the rules and the audit trail are the same from every screen.

    replace revokes the student's other active cards: a lost or broken
    card is replaced without losing the attendance it recorded."""
    card = Card.objects.filter(org=org, uid=uid).select_related("student").first()
    if card and card.active:
        if card.is_admin:
            raise ValidationError({"card_uid": "That is an admin card."})
        if card.student_id and card.student_id != student.id:
            raise ValidationError({"card_uid":
                f"That card is already registered to {card.student.full_name}."})

    if replace:
        for old in Card.objects.filter(org=org, student=student,
                                       active=True).exclude(uid=uid):
            old.active = False
            old.revoked_at = timezone.now()
            old.save(update_fields=["active", "revoked_at"])
            audit(request, "card_revoke",
                  f"uid={old.uid} replaced for {student_label(student)}")

    if card is None:
        card = Card.objects.create(org=org, uid=uid, student=student)
    else:
        card.student, card.is_admin, card.active = student, False, True
        card.revoked_at = None
        card.save()
    audit(request, "card_bind", f"uid={uid} -> {student_label(student)}")
    return card


def student_label(student):
    if student.matric_no:
        return f"{student.full_name} ({student.matric_no})"
    return student.full_name


class StudentFilter(django_filters.FilterSet):
    # "Has a card" is the question a registrar actually asks.
    has_card = django_filters.BooleanFilter(method="filter_has_card")

    class Meta:
        model = Student
        fields = ["active", "department", "level"]

    def filter_has_card(self, qs, name, value):
        with_card = Q(cards__active=True)
        return (qs.filter(with_card) if value else qs.exclude(with_card)).distinct()


class StudentViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Student.objects.prefetch_related("cards").all()
    serializer_class = StudentSerializer
    permission_classes = [IsOrgAdminOrReadOnly]
    pagination_class = StandardPagination
    filterset_class = StudentFilter
    search_fields = ["full_name", "matric_no", "phone", "email", "level",
                     "department", "cards__uid"]
    ordering_fields = ["full_name", "matric_no", "level", "created_at"]
    ordering = ["full_name"]

    def get_queryset(self):
        # Searching on cards__uid joins cards, which would repeat a
        # student once per card they have ever held.
        qs = super().get_queryset()
        return qs.distinct() if self.request.query_params.get("search") else qs

    @transaction.atomic
    def perform_create(self, serializer):
        uid = serializer.validated_data.get("card_uid")
        student = serializer.save()
        audit(self.request, "student_create", student_label(student))
        if uid:
            bind_card(self.request, self.org, uid, student)

    @transaction.atomic
    def perform_update(self, serializer):
        uid = serializer.validated_data.get("card_uid")
        student = serializer.save()
        audit(self.request, "student_update", student_label(student))
        if uid and not student.cards.filter(uid=uid, active=True).exists():
            bind_card(self.request, self.org, uid, student, replace=True)

    def destroy(self, request, *args, **kwargs):
        return destroy_or_conflict(self, request, "student")

    @action(detail=False)
    def levels(self, request):
        """Levels in use, for the filter list."""
        values = (Student.objects.filter(org=self.org).exclude(level="")
                  .values_list("level", flat=True).distinct())
        return Response(sorted(set(values), key=lambda v: (len(v), v)))

    @action(detail=True)
    def attendance(self, request, pk=None):
        """Attendance per course for one student, against the lectures
        that have actually taken place."""
        student = self.get_object()
        rows = list(AttendanceRecord.objects
                .filter(student=student)
                .values("session__course_id", "session__course__code")
                .annotate(attended=Count("id"),
                          present=Count("id", filter=Q(status="present")),
                          late=Count("id", filter=Q(status="late")))
                .order_by("session__course__code"))

        # One query for every course's held-session count, instead of one
        # query per row.
        held_map = dict(held_sessions(self.org)
                        .filter(course_id__in=[r["session__course_id"] for r in rows])
                        .values("course_id").annotate(held=Count("id"))
                        .values_list("course_id", "held"))

        out = []
        for r in rows:
            held = held_map.get(r["session__course_id"], 0)
            out.append({
                "course": r["session__course__code"], "sessions_held": held,
                "attended": r["attended"], "present": r["present"],
                "late": r["late"],
                "percentage": round(100 * r["attended"] / held, 1) if held else None,
            })
        return Response(out)


# A card used fewer times than this in the last 30 days is "rarely used".
RARE_USES_30D = 3


def card_usage(qs):
    """Annotate cards with when and how often they have been tapped since
    they were issued. Taps are matched by UID within the same org; taps
    from before the card was issued (while it was still unknown) do not
    count as use."""
    since_issue = TapEvent.objects.filter(
        org=OuterRef("org"), uid=OuterRef("uid"),
        tapped_at__gte=OuterRef("issued_at"))

    def count(q):
        return Coalesce(Subquery(q.values("uid").annotate(n=Count("id"))
                                 .values("n")[:1], output_field=IntegerField()),
                        Value(0))

    month_ago = timezone.now() - timedelta(days=30)
    return qs.annotate(
        last_used=Subquery(since_issue.order_by("-tapped_at")
                           .values("tapped_at")[:1]),
        uses_total=count(since_issue),
        uses_30d=count(since_issue.filter(tapped_at__gte=month_ago)))


class CardFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(
        choices=[("active", "Active"), ("revoked", "Revoked"),
                 ("unassigned", "Unassigned")], method="filter_status")
    usage = django_filters.ChoiceFilter(
        choices=[("never", "Never used"), ("rare", "Rarely used"),
                 ("regular", "Regular")], method="filter_usage")

    class Meta:
        model = Card
        fields = ["is_admin", "student"]

    def filter_status(self, qs, name, value):
        if value == "active":
            return qs.filter(active=True)
        if value == "revoked":
            return qs.filter(active=False)
        return qs.filter(active=True, student__isnull=True, is_admin=False)

    def filter_usage(self, qs, name, value):
        if value == "never":
            return qs.filter(uses_total=0)
        if value == "rare":
            return qs.filter(uses_total__gt=0, uses_30d__lt=RARE_USES_30D)
        return qs.filter(uses_30d__gte=RARE_USES_30D)


class CardViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Card.objects.select_related("student", "holder").all()
    serializer_class = CardSerializer
    permission_classes = [IsOrgAdmin]
    pagination_class = StandardPagination
    filterset_class = CardFilter
    search_fields = ["uid", "student__matric_no", "student__full_name"]
    ordering_fields = ["issued_at", "last_used", "uses_30d", "uid"]
    ordering = ["-issued_at"]

    def get_queryset(self):
        return card_usage(super().get_queryset())

    def perform_create(self, serializer):
        card = serializer.save()
        audit(self.request, "card_create",
              f"uid={card.uid} student={card.student_id} admin={card.is_admin}")

    def perform_update(self, serializer):
        card = serializer.save()
        if card.active and card.revoked_at:
            card.revoked_at = None
            card.save(update_fields=["revoked_at"])
        audit(self.request, "card_update",
              f"uid={card.uid} student={card.student_id} active={card.active}")

    def perform_destroy(self, instance):
        # Cards are revoked, never deleted, so history stays intact.
        instance.active = False
        instance.revoked_at = timezone.now()
        instance.save()
        audit(self.request, "card_revoke", f"uid={instance.uid}")

    @action(detail=False)
    def summary(self, request):
        """Counts for the Cards page header."""
        rows = card_usage(Card.objects.filter(org=self.org)).values_list(
            "active", "is_admin", "student_id", "uses_total", "uses_30d")
        out = {"total": 0, "active": 0, "revoked": 0, "admin": 0,
               "unassigned": 0, "never_used": 0, "rarely_used": 0,
               "regular": 0, "rare_threshold": RARE_USES_30D}
        for active, is_admin, student, total, month in rows:
            out["total"] += 1
            if not active:
                out["revoked"] += 1
                continue
            out["active"] += 1
            if is_admin:
                out["admin"] += 1
            elif not student:
                out["unassigned"] += 1
            if total == 0:
                out["never_used"] += 1
            elif month < RARE_USES_30D:
                out["rarely_used"] += 1
            else:
                out["regular"] += 1
        return Response(out)

    @action(detail=False)
    def capture(self, request):
        """The card most recently tapped on one reader since a moment in
        time. The dashboard polls this while waiting for a card to be
        swiped, so the number never has to be typed.

        The reader uploads every tap, known or not, within seconds, so
        this needs nothing special from the firmware. received_at is the
        server's clock, so the reader's clock does not matter here."""
        device = Device.objects.filter(
            org=self.org, active=True,
            pk=request.query_params.get("device") or 0).first()
        since = parse_datetime(request.query_params.get("since", "") or "")
        if device is None or since is None:
            return Response({"detail": "device and since are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(since):
            since = since.replace(tzinfo=dt_timezone.utc)

        tap = (TapEvent.objects.filter(org=self.org, device=device,
                                       received_at__gt=since)
               .order_by("-received_at").first())
        online = bool(device.last_seen and
                      device.last_seen > timezone.now() - timedelta(minutes=5))
        if tap is None:
            return Response({"uid": None, "device_online": online})

        card = Card.objects.filter(org=self.org, uid=tap.uid).select_related(
            "student").first()
        if card is None:
            state, who = "new", None
        elif not card.active:
            state, who = "revoked", None
        elif card.is_admin:
            state, who = "admin", None
        elif card.student_id:
            state, who = "taken", card.student.full_name
        else:
            state, who = "unassigned", None
        return Response({"uid": tap.uid, "seen_at": tap.received_at,
                         "state": state, "student": who,
                         "student_id": card.student_id if card else None,
                         "device_online": online})

    @action(detail=False, methods=["post"])
    def bind(self, request):
        """Attach a seen-but-unregistered UID to a student."""
        s = BindCardSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            uid = clean_uid(s.validated_data["uid"])
        except ValidationError as e:
            return Response({"uid": e.detail}, status=status.HTTP_400_BAD_REQUEST)
        try:
            student = Student.objects.get(org=self.org, pk=s.validated_data["student_id"])
        except Student.DoesNotExist:
            return Response({"detail": "No such student."},
                            status=status.HTTP_404_NOT_FOUND)
        existed = Card.objects.filter(org=self.org, uid=uid).exists()
        try:
            with transaction.atomic():
                card = bind_card(request, self.org, uid, student,
                                 s.validated_data["replace"])
        except ValidationError as e:
            return Response({"detail": e.detail["card_uid"]},
                            status=status.HTTP_409_CONFLICT)
        return Response(CardSerializer(card).data,
                        status=status.HTTP_200_OK if existed
                        else status.HTTP_201_CREATED)


class VenueViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Venue.objects.all()
    serializer_class = VenueSerializer
    permission_classes = [IsOrgAdminOrReadOnly]
    pagination_class = LargePagination
    search_fields = ["code", "name"]
    ordering = ["code"]

    def destroy(self, request, *args, **kwargs):
        return destroy_or_conflict(self, request, "venue")


class CourseViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Course.objects.select_related("lecturer").annotate(
        enrolled_count=Count("enrollments", distinct=True))
    serializer_class = CourseSerializer
    permission_classes = [IsOrgAdminOrReadOnly]
    pagination_class = StandardPagination
    filterset_fields = ["lecturer"]
    search_fields = ["code", "title"]
    ordering = ["code"]

    def destroy(self, request, *args, **kwargs):
        return destroy_or_conflict(self, request, "course")

    @action(detail=True)
    def roster(self, request, pk=None):
        course = self.get_object()
        students = Student.objects.filter(
            enrollments__course=course, active=True).order_by("matric_no")
        page = self.paginate_queryset(students)
        return self.get_paginated_response(
            StudentSerializer(page, many=True).data)


class EnrollmentViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Enrollment.objects.select_related("student", "course").all()
    serializer_class = EnrollmentSerializer
    # Lecturers need to see who is on their course; only admins change it.
    permission_classes = [IsOrgAdminOrReadOnly]
    pagination_class = LargePagination
    filterset_fields = ["course", "student", "term"]
    search_fields = ["student__matric_no", "student__full_name"]
    ordering = ["student__matric_no"]

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        """Enrol many students onto one course in a single query."""
        course_id = request.data.get("course")
        ids = request.data.get("student_ids", [])
        term = request.data.get("term") or self.org.term
        if not course_id or not isinstance(ids, list):
            return Response({"detail": "course and student_ids are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        # Only students from this org, so a forged id cannot reach across.
        valid = set(Student.objects.filter(
            org=self.org, id__in=ids).values_list("id", flat=True))
        if not Course.objects.filter(org=self.org, id=course_id).exists():
            return Response({"detail": "No such course."},
                            status=status.HTTP_404_NOT_FOUND)
        objs = [Enrollment(org=self.org, course_id=course_id,
                           student_id=i, term=term) for i in valid]
        created = Enrollment.objects.bulk_create(objs, ignore_conflicts=True)
        audit(request, "enroll_bulk", f"course={course_id} n={len(ids)}")
        return Response({"requested": len(ids), "created": len(created)},
                        status=status.HTTP_201_CREATED)


class DeviceViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Device.objects.select_related("venue").all()
    serializer_class = DeviceSerializer
    permission_classes = [IsOrgAdmin]
    filterset_fields = ["active", "venue", "enroll_mode"]
    search_fields = ["name", "hardware_id"]
    ordering = ["name"]

    def check_plan_limit(self):
        active = Device.objects.filter(org=self.org, active=True).count()
        if active >= self.org.max_devices:
            raise ValidationError({"detail":
                f"Your plan allows {self.org.max_devices} readers. "
                f"Remove one first."})

    def perform_create(self, serializer):
        self.check_plan_limit()
        device = serializer.save()
        audit(self.request, "device_add", f"{device.name} {device.hardware_id}")

    @action(detail=False)
    def discover(self, request):
        """Readers on this network that are not registered anywhere."""
        from deviceapi.pairing import discover
        return Response(discover(request, self.org))

    @action(detail=False, methods=["post"])
    def claim(self, request):
        """Add a discovered reader, proven by the code on its screen. The
        reader picks up its token by itself; nothing to copy."""
        from deviceapi.pairing import claim
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.check_plan_limit()
        device = claim(request, self.org, serializer)
        audit(request, "device_add", f"{device.name} {device.hardware_id} (paired)")
        return Response(self.get_serializer(device).data,
                        status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        device = serializer.save()
        audit(self.request, "device_update",
              f"{device.name} {device.hardware_id}")

    def perform_destroy(self, instance):
        """Removing a reader frees its hardware id so another account can
        add it, and replaces its token so it stops working here. The row
        stays, because every tap it ever recorded points at it."""
        import secrets
        hw = instance.hardware_id
        instance.active = False
        instance.hardware_id = None
        instance.token = secrets.token_urlsafe(32)
        instance.name = (f"{instance.name} (removed "
                         f"{timezone.now():%Y-%m-%d %H:%M})")[:64]
        instance.save()
        audit(self.request, "device_remove", f"{instance.name} {hw}")

    @action(detail=True, methods=["post"])
    def reveal_token(self, request, pk=None):
        """Shows the token once, for provisioning. Always audited."""
        device = self.get_object()
        audit(request, "device_token_reveal", f"device={device.name}")
        return Response({"name": device.name, "token": device.token})

    @action(detail=True, methods=["post"])
    def rotate_token(self, request, pk=None):
        import secrets
        device = self.get_object()
        device.token = secrets.token_urlsafe(32)
        device.save()
        audit(request, "device_token_rotate", f"device={device.name}")
        return Response({"name": device.name, "token": device.token})


class TimetableSlotViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = TimetableSlot.objects.select_related("course", "venue").all()
    serializer_class = TimetableSlotSerializer
    permission_classes = [IsOrgAdminOrReadOnly]
    pagination_class = LargePagination
    filterset_fields = ["course", "venue", "weekday", "term", "active"]
    ordering = ["weekday", "start_time"]

    def _drop_future_sessions(self, slot):
        """Sessions are generated from a slot the first time a reader
        checks in that day. After an edit, a session already generated
        for later today would keep the old time, and the reader would
        also get a second one at the new time. Removing sessions that
        have not started lets them be generated again from the new slot.
        One that has started, or has attendance, is left alone."""
        ClassSession.objects.filter(
            org=self.org, slot=slot, status="scheduled",
            starts_at__gt=timezone.now(), records__isnull=True).delete()

    def perform_create(self, serializer):
        slot = serializer.save()
        audit(self.request, "slot_create", self._describe(slot))

    def perform_update(self, serializer):
        slot = serializer.save()
        self._drop_future_sessions(slot)
        audit(self.request, "slot_update", self._describe(slot))

    def perform_destroy(self, instance):
        self._drop_future_sessions(instance)
        audit(self.request, "slot_delete", self._describe(instance))
        instance.delete()

    @staticmethod
    def _describe(slot):
        return (f"{slot.course.code} {slot.get_weekday_display()} "
                f"{slot.start_time:%H:%M}-{slot.end_time:%H:%M} "
                f"{slot.venue.code}")


class ClassSessionViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = ClassSession.objects.select_related("course", "venue").annotate(
        present_count=Count("records", filter=Q(records__status="present")),
        late_count=Count("records", filter=Q(records__status="late")))
    serializer_class = ClassSessionSerializer
    permission_classes = [IsLecturerOrAdmin]
    pagination_class = StandardPagination
    filterset_fields = ["course", "venue", "status"]
    ordering = ["-starts_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        # ?running=true: lectures under way right now, whether the timetable
        # started them or a lecturer opened them by hand.
        if self.request.query_params.get("running") == "true":
            now = timezone.now()
            qs = qs.filter(starts_at__lte=now, ends_at__gte=now).exclude(
                status__in=["closed", "cancelled"])
        m = get_membership(self.request)
        if m.can_administer:
            return qs
        return qs.filter(course__lecturer=self.request.user)

    @action(detail=True, methods=["post"])
    def open(self, request, pk=None):
        session = self.get_object()
        self.check_object_permissions(request, session)
        session.status = "open"
        session.opened_by = request.user
        session.roster_version += 1
        session.save()
        audit(request, "session_open", f"session={session.id}")
        return Response(self.get_serializer(session).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        session = self.get_object()
        self.check_object_permissions(request, session)
        session.status = "closed"
        session.save()
        audit(request, "session_close", f"session={session.id}")
        return Response(self.get_serializer(session).data)

    @action(detail=True)
    def live(self, request, pk=None):
        """Lecturer view during class. Pass ?since=<iso> to get only new
        rows, so polling stays cheap."""
        session = self.get_object()
        qs = AttendanceRecord.objects.filter(
            session=session).select_related("student")
        since = request.query_params.get("since")
        if since:
            qs = qs.filter(tapped_at__gt=since)
        qs = qs.order_by("tapped_at")
        return Response({
            "server_time": timezone.now().isoformat(),
            "records": AttendanceRecordSerializer(qs, many=True).data,
        })


class TapEventFilter(django_filters.FilterSet):
    """Dates are the institution's calendar days, not UTC days."""
    date_from = django_filters.DateFilter(method="filter_from")
    date_to   = django_filters.DateFilter(method="filter_to")
    counted   = django_filters.BooleanFilter(method="filter_counted")

    class Meta:
        model = TapEvent
        fields = ["device", "outcome", "session", "student", "time_conf"]

    def filter_from(self, qs, name, value):
        start, _ = local_day_range(get_membership(self.request).org, value, value)
        return qs.filter(tapped_at__gte=start)

    def filter_to(self, qs, name, value):
        _, end = local_day_range(get_membership(self.request).org, value, value)
        return qs.filter(tapped_at__lt=end)

    def filter_counted(self, qs, name, value):
        q = Q(outcome__in=["present", "late"])
        return qs.filter(q) if value else qs.exclude(q)


class TapEventViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    queryset = TapEvent.objects.select_related("device", "student").all()
    serializer_class = TapEventSerializer
    permission_classes = [IsLecturerOrAdmin]
    pagination_class = StandardPagination
    filterset_class = TapEventFilter
    search_fields = ["uid", "student__full_name", "student__matric_no",
                     "device__name"]
    ordering_fields = ["tapped_at", "received_at"]
    ordering = ["-tapped_at"]

    def get_queryset(self):
        return super().get_queryset().select_related(
            "session", "session__course")

    @action(detail=False)
    def unregistered(self, request):
        """Cards seen by a device but not in the Card table. This is the
        registrar's worklist for binding new cards."""
        known = Card.objects.filter(org=self.org).values_list("uid", flat=True)
        rows = (TapEvent.objects.filter(org=self.org, outcome="unknown")
                .exclude(uid__in=known)
                .values("uid")
                .annotate(times_seen=Count("id"),
                          last_seen=Max("received_at"),
                          last_device=Max("device__name"))
                .order_by("-last_seen"))
        page = self.paginate_queryset(rows)
        return self.get_paginated_response(list(page))


class AttendanceRecordViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AttendanceRecord.objects.select_related(
        "student", "session", "session__course", "device").all()
    serializer_class = AttendanceRecordSerializer
    permission_classes = [IsLecturerOrAdmin]
    pagination_class = LargePagination
    filterset_fields = ["session", "student", "status", "verified"]
    ordering = ["-tapped_at"]


class AuditLogViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("actor").all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsOrgAdmin]
    pagination_class = StandardPagination
    filterset_fields = ["action", "actor"]
    search_fields = ["action", "detail", "actor__username"]
    ordering = ["-created_at"]


