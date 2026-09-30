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


def clean_uid(value):
    """Card UIDs as stored: uppercase hex, no separators, 4/7/10 bytes."""
    uid = value.strip().upper().replace(":", "").replace(" ", "").replace("-", "")
    if not uid or not all(c in "0123456789ABCDEF" for c in uid):
        raise serializers.ValidationError("Card number must be hexadecimal.")
    if len(uid) not in (8, 14, 20):
        raise serializers.ValidationError(
            "Card number must be 8, 14 or 20 hex characters (4, 7 or 10 bytes).")
    return uid


class CardBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Card
        fields = ("id", "uid", "active", "is_admin", "issued_at")


class StudentSerializer(TenantSerializer):
    cards = CardBriefSerializer(many=True, read_only=True)
    # Write-only: the card to give this student. On create it is bound
    # straight away; on edit a different number replaces their card.
    card_uid = serializers.CharField(write_only=True, required=False,
                                     allow_blank=True, max_length=32)

    class Meta:
        model = Student
        fields = ("id", "full_name", "matric_no", "phone", "email",
                  "department", "level", "short_name", "active",
                  "created_at", "cards", "card_uid")
        read_only_fields = ("created_at", "short_name")
        extra_kwargs = {"matric_no": {"required": False}}

    def validate_full_name(self, value):
        value = " ".join(value.split())
        if len(value) < 3:
            raise serializers.ValidationError("Enter the student's full name.")
        return value

    def validate_matric_no(self, value):
        value = value.strip().upper()
        if value:
            unique_in_org(self, Student, "matric_no", value,
                          "A student with this matric number already exists.")
        return value

    def validate_phone(self, value):
        value = value.strip()
        if not value:
            return value
        digits = "".join(c for c in value if c.isdigit())
        if not all(c.isdigit() or c in "+ -()" for c in value)                 or not 7 <= len(digits) <= 15 or "+" in value[1:]:
            raise serializers.ValidationError(
                "Enter a phone number, e.g. 08031234567 or +2348031234567.")
        return ("+" if value.startswith("+") else "") + digits

    def validate_email(self, value):
        return value.strip().lower()

    def validate_level(self, value):
        return value.strip().upper()

    def validate_card_uid(self, value):
        if not value.strip():
            return ""
        uid = clean_uid(value)
        card = Card.objects.filter(org=self._org(), uid=uid).select_related(
            "student").first()
        if card is None or not card.active:
            return uid
        if card.is_admin:
            raise serializers.ValidationError("That is an admin card.")
        if card.student_id and (self.instance is None
                                or card.student_id != self.instance.pk):
            raise serializers.ValidationError(
                f"That card is already registered to {card.student.full_name}.")
        return uid

    def create(self, validated_data):
        validated_data.pop("card_uid", None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("card_uid", None)
        return super().update(instance, validated_data)


class CardSerializer(TenantSerializer):
    student_name = serializers.CharField(source="student.full_name",
                                         read_only=True, default=None)
    matric_no    = serializers.CharField(source="student.matric_no",
                                         read_only=True, default=None)
    holder_name  = serializers.CharField(source="holder.get_full_name",
                                         read_only=True, default=None)
    # Filled in by CardViewSet's annotations.
    last_used    = serializers.DateTimeField(read_only=True, default=None)
    uses_30d     = serializers.IntegerField(read_only=True, default=0)
    uses_total   = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Card
        fields = ("id", "uid", "student", "student_name", "matric_no",
                  "holder", "holder_name", "is_admin", "active", "issued_at",
                  "revoked_at", "last_used", "uses_30d", "uses_total")
        read_only_fields = ("issued_at", "revoked_at")

    def validate_uid(self, value):
        uid = clean_uid(value)
        unique_in_org(self, Card, "uid", uid,
                      "A card with this number is already on record.")
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
        return obj.student.full_name


def normalise_hardware_id(value):
    """A reader's MAC address as AA:BB:CC:DD:EE:FF, however it was typed."""
    raw = "".join(c for c in str(value).upper() if c in "0123456789ABCDEF")
    if len(raw) != 12:
        raise serializers.ValidationError(
            "Enter the reader ID shown on its screen or setup page, "
            "e.g. A4:CF:12:34:56:78.")
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))


class DeviceSerializer(TenantSerializer):
    venue_code = serializers.CharField(source="venue.code", read_only=True)
    online     = serializers.SerializerMethodField()

    class Meta:
        model = Device
        # token is deliberately absent. It is revealed once, through a
        # dedicated action, so it never appears in a list response.
        fields = ("id", "name", "hardware_id", "venue", "venue_code",
                  "enroll_mode", "active", "last_seen", "firmware",
                  "queue_depth", "online")
        read_only_fields = ("last_seen", "firmware", "queue_depth", "active")
        # The model's own unique check would say only "already exists".
        # validate_hardware_id says where, and what to do about it.
        extra_kwargs = {"hardware_id": {"validators": [], "required": True,
                                        "allow_null": False}}

    def validate_name(self, value):
        value = value.strip()
        unique_in_org(self, Device, "name", value,
                      "A reader with this name already exists.")
        return value

    def validate_hardware_id(self, value):
        hw = normalise_hardware_id(value)
        taken = Device.objects.filter(hardware_id=hw)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        other = taken.first()
        if other is None:
            return hw
        if other.org_id == self._org().id:
            raise serializers.ValidationError(
                f"This reader is already registered here as {other.name}.")
        # Deliberately says nothing about which account holds it.
        raise serializers.ValidationError(
            "This reader is registered to another account. It must be "
            "removed from that account before it can be added here.")

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

