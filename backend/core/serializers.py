from datetime import time

from rest_framework import serializers
from .base_serializers import TenantSerializer
from django.contrib.auth.models import User
from .models import (Student, Card, Venue, Course, Enrollment, Device,
                     TimetableSlot, ClassSession, TapEvent,
                     AttendanceRecord, AuditLog)


def unique_in_org(serializer, model, field, value, message):
    """Per-org unique constraints are not checked by DRF, because org is
    never an input field. Without this a duplicate is an IntegrityError
    and a 500 instead of a form error."""
    qs = model.objects.filter(org=serializer._org(), **{field: value})
    if serializer.instance is not None:
        qs = qs.exclude(pk=serializer.instance.pk)
    if qs.exists():
        raise serializers.ValidationError(message)


class UserBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name")


class CardBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Card
        fields = ("id", "uid", "active", "is_admin", "issued_at")


class StudentSerializer(TenantSerializer):
    cards = CardBriefSerializer(many=True, read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = ("id", "matric_no", "first_name", "last_name", "full_name",
                  "short_name", "department", "level", "active",
                  "created_at", "cards")
        read_only_fields = ("created_at",)

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"

    def validate_matric_no(self, value):
        value = value.strip().upper()
        unique_in_org(self, Student, "matric_no", value,
                      "A student with this matric number already exists.")
        return value


class CardSerializer(TenantSerializer):
    student_name = serializers.CharField(source="student.short_name",
                                         read_only=True)

    class Meta:
        model = Card
        fields = ("id", "uid", "student", "student_name", "holder",
                  "is_admin", "active", "issued_at", "revoked_at")
        read_only_fields = ("issued_at", "revoked_at")

    def validate_uid(self, value):
        uid = value.strip().upper().replace(":", "").replace(" ", "")
        if not all(c in "0123456789ABCDEF" for c in uid):
            raise serializers.ValidationError("UID must be hexadecimal.")
        if len(uid) not in (8, 14, 20):
            raise serializers.ValidationError(
                "UID must be 8, 14 or 20 hex characters (4, 7 or 10 bytes).")
        return uid


class VenueSerializer(TenantSerializer):
    class Meta:
        model = Venue
        fields = ("id", "code", "name", "capacity")

    def validate_code(self, value):
        value = value.strip().upper()
        unique_in_org(self, Venue, "code", value,
                      "A venue with this code already exists.")
        return value


class CourseSerializer(TenantSerializer):
    lecturer_name    = serializers.CharField(source="lecturer.get_full_name",
                                             read_only=True)
    enrolled_count   = serializers.IntegerField(read_only=True)

    def validate_code(self, value):
        value = value.strip().upper()
        unique_in_org(self, Course, "code", value,
                      "A course with this code already exists.")
        return value

    class Meta:
        model = Course
        fields = ("id", "code", "title", "lecturer", "lecturer_name",
                  "enrolled_count")


class EnrollmentSerializer(TenantSerializer):
    student_name = serializers.CharField(source="student.short_name",
                                         read_only=True)
    matric_no    = serializers.CharField(source="student.matric_no",
                                         read_only=True)
    full_name    = serializers.SerializerMethodField()
    course_code  = serializers.CharField(source="course.code", read_only=True)

    class Meta:
        model = Enrollment
        fields = ("id", "student", "student_name", "matric_no", "full_name",
                  "course", "course_code", "term")

    def get_full_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"


class DeviceSerializer(TenantSerializer):
    venue_code = serializers.CharField(source="venue.code", read_only=True)
    online     = serializers.SerializerMethodField()

    class Meta:
        model = Device
        # token is deliberately absent. It is revealed once, through a
        # dedicated action, so it never appears in a list response.
        fields = ("id", "name", "venue", "venue_code", "enroll_mode",
                  "active", "last_seen", "firmware", "queue_depth", "online")
        read_only_fields = ("last_seen", "firmware", "queue_depth")

    def get_online(self, obj):
        from django.utils import timezone
        from datetime import timedelta
        if not obj.last_seen:
            return False
        return obj.last_seen > timezone.now() - timedelta(minutes=5)


class TimetableSlotSerializer(TenantSerializer):
    # The teaching week. Lectures run Monday to Saturday, 07:00 to 18:00.
    FIRST_DAY, LAST_DAY = 0, 5
    DAY_START, DAY_END = time(7, 0), time(18, 0)

    course_code  = serializers.CharField(source="course.code", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)
    lecturer_name = serializers.CharField(
        source="course.lecturer.get_full_name", read_only=True, default="")
    venue_code   = serializers.CharField(source="venue.code", read_only=True)
    weekday_name = serializers.CharField(source="get_weekday_display",
                                         read_only=True)

    class Meta:
        model = TimetableSlot
        fields = ("id", "course", "course_code", "course_title",
                  "lecturer_name", "venue", "venue_code",
                  "weekday", "weekday_name", "start_time", "end_time",
                  "grace_minutes", "term", "active")
        extra_kwargs = {"term": {"required": False}}

    def validate_weekday(self, value):
        if not self.FIRST_DAY <= value <= self.LAST_DAY:
            raise serializers.ValidationError(
                "Lectures run Monday to Saturday.")
        return value

    def validate_grace_minutes(self, value):
        if value > 120:
            raise serializers.ValidationError("At most 120 minutes.")
        return value

    def validate(self, data):
        # super() carries the cross-organisation check. Skipping it here
        # once let a slot be attached to another school's venue.
        data = super().validate(data)

        # A PATCH may send one field; judge the slot as it will end up.
        cur = lambda k: data.get(k, getattr(self.instance, k, None))
        start, end = cur("start_time"), cur("end_time")
        if start and end:
            if end <= start:
                raise serializers.ValidationError(
                    {"end_time": "End time must be after the start time."})
            if start < self.DAY_START or end > self.DAY_END:
                raise serializers.ValidationError(
                    {"start_time": "Lectures must fall between 07:00 and 18:00."})

        if not cur("term"):
            data["term"] = self._org().term

        # Two lectures cannot share a room at the same time. Touching
        # (one ends 10:00, the next starts 10:00) is fine.
        venue, day = cur("venue"), cur("weekday")
        if venue and day is not None and start and end and cur("active") is not False:
            clash = TimetableSlot.objects.filter(
                org=self._org(), venue=venue, weekday=day, active=True,
                term=data.get("term") or cur("term"),
                start_time__lt=end, end_time__gt=start)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            other = clash.select_related("course").first()
            if other:
                raise serializers.ValidationError({"venue": (
                    f"{venue.code} is already booked for {other.course.code} "
                    f"{other.start_time:%H:%M}-{other.end_time:%H:%M}.")})
        return data


class ClassSessionSerializer(TenantSerializer):
    course_code  = serializers.CharField(source="course.code", read_only=True)
    venue_code   = serializers.CharField(source="venue.code", read_only=True)
    present_count = serializers.IntegerField(read_only=True)
    late_count    = serializers.IntegerField(read_only=True)

    class Meta:
        model = ClassSession
        fields = ("id", "slot", "course", "course_code", "venue", "venue_code",
                  "starts_at", "ends_at", "grace_minutes", "status",
                  "opened_by", "roster_version",
                  "present_count", "late_count")
        read_only_fields = ("opened_by", "roster_version")


class TapEventSerializer(TenantSerializer):
    device_name  = serializers.CharField(source="device.name", read_only=True)
    student_name = serializers.CharField(source="student.short_name",
                                         read_only=True)

    class Meta:
        model = TapEvent
        fields = ("id", "device", "device_name", "uid", "student",
                  "student_name", "session", "outcome", "device_outcome",
                  "tapped_at",
                  "time_conf", "client_id", "received_at")
        read_only_fields = fields          # the raw log is never edited


class AttendanceRecordSerializer(TenantSerializer):
    student_name = serializers.CharField(source="student.short_name",
                                         read_only=True)
    matric_no    = serializers.CharField(source="student.matric_no",
                                         read_only=True)
    course_code  = serializers.CharField(source="session.course.code",
                                         read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = ("id", "session", "course_code", "student", "student_name",
                  "matric_no", "status", "tapped_at", "device", "verified")


class AuditLogSerializer(TenantSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = AuditLog
        fields = ("id", "actor", "actor_name", "action", "detail",
                  "ip", "created_at")
        read_only_fields = fields


class BindCardSerializer(serializers.Serializer):
    """Binding a UID to a student is the fraud-sensitive operation, so it
    gets its own endpoint and is always written to the audit log."""
    uid        = serializers.CharField(max_length=20)
    student_id = serializers.IntegerField()
    replace    = serializers.BooleanField(
        default=False,
        help_text="Revoke the student's existing cards first")

