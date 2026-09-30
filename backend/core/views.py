from django.db.models import Count, Q, Max, ProtectedError
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (Student, Card, Venue, Course, Enrollment, Device,
                     TimetableSlot, ClassSession, TapEvent,
                     AttendanceRecord, AuditLog)
from .serializers import (StudentSerializer, CardSerializer, VenueSerializer,
                          CourseSerializer, EnrollmentSerializer,
                          DeviceSerializer, TimetableSlotSerializer,
                          ClassSessionSerializer, TapEventSerializer,
                          AttendanceRecordSerializer, AuditLogSerializer,
                          BindCardSerializer)
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


class StudentViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Student.objects.prefetch_related("cards").all()
    serializer_class = StudentSerializer
    permission_classes = [IsOrgAdminOrReadOnly]
    pagination_class = StandardPagination
    filterset_fields = ["active", "department", "level"]
    search_fields = ["matric_no", "first_name", "last_name"]
    ordering_fields = ["matric_no", "last_name", "created_at"]
    ordering = ["matric_no"]

    def destroy(self, request, *args, **kwargs):
        return destroy_or_conflict(self, request, "student")

    @action(detail=True)
    def attendance(self, request, pk=None):
        """Attendance percentage per course for one student."""
        student = self.get_object()
        rows = list(AttendanceRecord.objects
                .filter(student=student)
                .values("session__course__code")
                .annotate(attended=Count("id"),
                          present=Count("id", filter=Q(status="present")),
                          late=Count("id", filter=Q(status="late")))
                .order_by("session__course__code"))

        # One query for every course's held-session count, instead of one
        # query per row - this used to be an N+1 as the course list grew.
        codes = [r["session__course__code"] for r in rows]
        held_map = dict(ClassSession.objects
                         .filter(org=self.org, course__code__in=codes,
                                 status="closed")
                         .values("course__code")
                         .annotate(held=Count("id"))
                         .values_list("course__code", "held"))

        out = []
        for r in rows:
            code = r["session__course__code"]
            held = held_map.get(code, 0)
            out.append({
                "course": code, "sessions_held": held,
                "attended": r["attended"], "present": r["present"],
                "late": r["late"],
                "percentage": round(100 * r["attended"] / held, 1) if held else None,
            })
        return Response(out)


class CardViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    queryset = Card.objects.select_related("student", "holder").all()
    serializer_class = CardSerializer
    permission_classes = [IsOrgAdmin]
    pagination_class = StandardPagination
    filterset_fields = ["active", "is_admin", "student"]
    search_fields = ["uid", "student__matric_no", "student__last_name"]

    def perform_create(self, serializer):
        card = serializer.save()
        audit(self.request, "card_create",
              f"uid={card.uid} student={card.student_id} admin={card.is_admin}")

    def perform_update(self, serializer):
        card = serializer.save()
        audit(self.request, "card_update",
              f"uid={card.uid} student={card.student_id} active={card.active}")

    def perform_destroy(self, instance):
        # Cards are revoked, never deleted, so history stays intact.
        instance.active = False
        instance.revoked_at = timezone.now()
        instance.save()
        audit(self.request, "card_revoke", f"uid={instance.uid}")

    @action(detail=False, methods=["post"])
    def bind(self, request):
        """Attach a seen-but-unregistered UID to a student."""
        s = BindCardSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        uid = s.validated_data["uid"].strip().upper()
        try:
            student = Student.objects.get(org=self.org, pk=s.validated_data["student_id"])
        except Student.DoesNotExist:
            return Response({"detail": "No such student."},
                            status=status.HTTP_404_NOT_FOUND)

        if s.validated_data["replace"]:
            old = Card.objects.filter(org=self.org, student=student, active=True)
            for c in old:
                c.active = False
                c.revoked_at = timezone.now()
                c.save()
                audit(request, "card_revoke",
                      f"uid={c.uid} replaced for {student.matric_no}")

        card, created = Card.objects.get_or_create(
            org=self.org, uid=uid, defaults={"student": student})
        if not created:
            if card.student_id and card.student_id != student.id:
                return Response(
                    {"detail": f"UID already bound to {card.student}."},
                    status=status.HTTP_409_CONFLICT)
            card.student = student
            card.active = True
            card.revoked_at = None
            card.save()

        audit(request, "card_bind", f"uid={uid} -> {student.matric_no}")
        return Response(CardSerializer(card).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


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
    search_fields = ["student__matric_no", "student__first_name",
                     "student__last_name"]
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
    search_fields = ["name"]

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


class TapEventViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    queryset = TapEvent.objects.select_related("device", "student").all()
    serializer_class = TapEventSerializer
    permission_classes = [IsLecturerOrAdmin]
    pagination_class = StandardPagination
    filterset_fields = ["device", "outcome", "session", "time_conf"]
    search_fields = ["uid"]
    ordering = ["-received_at"]

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
    ordering = ["-created_at"]


