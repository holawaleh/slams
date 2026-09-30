import secrets
from django.db import models
from django.contrib.auth.models import User
from .tenancy import Organization, Membership, Invitation, TenantModel


class Student(TenantModel):
    # Name is stored as written. Institutions order names differently
    # (surname first or last), so splitting it would guess wrong.
    full_name  = models.CharField(max_length=128)
    # Required, and unique within the org.
    matric_no  = models.CharField(max_length=32)
    phone      = models.CharField(max_length=20, blank=True)
    email      = models.EmailField(blank=True)
    short_name = models.CharField(max_length=16, blank=True,
                                  help_text="Shown on the reader's display")
    department = models.CharField(max_length=64, blank=True)
    level      = models.CharField(max_length=8, blank=True)
    active     = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["org", "matric_no"], condition=~models.Q(matric_no=""),
            name="uniq_matric_per_org")]
        indexes = [models.Index(fields=["org", "active"]),
                   models.Index(fields=["org", "level"])]

    def save(self, *args, **kwargs):
        if not self.short_name:
            self.short_name = " ".join(self.full_name.split())[:16].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.matric_no or self.full_name


class Card(TenantModel):
    """UID is unique per org, not globally. Two institutions may legitimately
    hold different cards with the same UID, and a global constraint would
    also tell one org that another already holds a given card."""
    uid        = models.CharField(max_length=20)
    student    = models.ForeignKey(Student, null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="cards")
    holder     = models.ForeignKey(User, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    is_admin   = models.BooleanField(default=False)
    active     = models.BooleanField(default=True)
    issued_at  = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["org", "uid"], name="uniq_uid_per_org")]
        indexes = [models.Index(fields=["org", "uid", "active"])]

    def __str__(self):
        return f"{self.uid} -> {self.student or 'unassigned'}"


class Venue(TenantModel):
    code     = models.CharField(max_length=16)
    name     = models.CharField(max_length=128)
    capacity = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["org", "code"], name="uniq_venue_per_org")]

    def __str__(self):
        return self.code


class Course(TenantModel):
    code     = models.CharField(max_length=12)
    title    = models.CharField(max_length=128)
    lecturer = models.ForeignKey(User, null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name="courses")

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["org", "code"], name="uniq_course_per_org")]

    def __str__(self):
        return self.code


class Enrollment(TenantModel):
    student = models.ForeignKey(Student, on_delete=models.CASCADE,
                                related_name="enrollments")
    course  = models.ForeignKey(Course, on_delete=models.CASCADE,
                                related_name="enrollments")
    term    = models.CharField(max_length=16)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["org", "student", "course", "term"],
            name="uniq_enrollment_per_org")]
        indexes = [models.Index(fields=["org", "course"])]


class Device(TenantModel):
    name        = models.CharField(max_length=64)
    # The reader's own identity: its chip's MAC address, fixed at the
    # factory. Unique across every organisation, so one physical reader
    # can only belong to one account at a time. Cleared when the reader
    # is removed, which frees it to be added somewhere else.
    hardware_id = models.CharField(max_length=17, unique=True, null=True,
                                   blank=True)
    # Token stays globally unique - it is the lookup key for an
    # unauthenticated device, so it must resolve to exactly one org.
    token       = models.CharField(max_length=64, unique=True, blank=True)
    venue       = models.ForeignKey(Venue, null=True, blank=True,
                                    on_delete=models.SET_NULL,
                                    related_name="devices")
    enroll_mode = models.BooleanField(default=False)
    active      = models.BooleanField(default=True)
    last_seen   = models.DateTimeField(null=True, blank=True)
    firmware    = models.CharField(max_length=32, blank=True)
    queue_depth = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["org", "name"], name="uniq_device_per_org")]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class TimetableSlot(TenantModel):
    WEEKDAYS = [(0, "Mon"), (1, "Tue"), (2, "Wed"),
                (3, "Thu"), (4, "Fri"), (5, "Sat"), (6, "Sun")]
    course        = models.ForeignKey(Course, on_delete=models.CASCADE,
                                      related_name="slots")
    venue         = models.ForeignKey(Venue, on_delete=models.CASCADE)
    weekday       = models.IntegerField(choices=WEEKDAYS)
    start_time    = models.TimeField()
    end_time      = models.TimeField()
    grace_minutes = models.PositiveIntegerField(default=15)
    term          = models.CharField(max_length=16)
    active        = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["org", "venue", "weekday", "active"])]


class ClassSession(TenantModel):
    STATUS = [("scheduled", "Scheduled"), ("open", "Open"),
              ("closed", "Closed"), ("cancelled", "Cancelled")]
    slot           = models.ForeignKey(TimetableSlot, null=True, blank=True,
                                       on_delete=models.SET_NULL)
    course         = models.ForeignKey(Course, on_delete=models.PROTECT)
    venue          = models.ForeignKey(Venue, on_delete=models.PROTECT)
    starts_at      = models.DateTimeField()
    ends_at        = models.DateTimeField()
    grace_minutes  = models.PositiveIntegerField(default=15)
    status         = models.CharField(max_length=12, choices=STATUS,
                                      default="scheduled")
    opened_by      = models.ForeignKey(User, null=True, blank=True,
                                       on_delete=models.SET_NULL)
    roster_version = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [models.Index(fields=["org", "venue", "starts_at"]),
                   models.Index(fields=["org", "status", "starts_at"])]

    def __str__(self):
        return f"{self.course.code} {self.starts_at:%Y-%m-%d %H:%M}"


class TapEvent(TenantModel):
    device      = models.ForeignKey(Device, on_delete=models.CASCADE,
                                    related_name="taps")
    uid         = models.CharField(max_length=20)
    student     = models.ForeignKey(Student, null=True, blank=True,
                                    on_delete=models.SET_NULL)
    session     = models.ForeignKey(ClassSession, null=True, blank=True,
                                    on_delete=models.SET_NULL)
    # outcome is the server's verdict, judged against the timetable.
    # device_outcome is what the reader showed the student at the time,
    # kept so a disagreement between the two can be investigated.
    outcome        = models.CharField(max_length=16)
    device_outcome = models.CharField(max_length=16, blank=True)
    tapped_at   = models.DateTimeField()
    time_conf   = models.CharField(max_length=8, default="synced")
    client_id   = models.BigIntegerField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["device", "client_id"], name="uniq_tap_per_device")]
        indexes = [models.Index(fields=["org", "-received_at"]),
                   models.Index(fields=["org", "uid", "-received_at"]),
                   models.Index(fields=["org", "outcome", "-received_at"])]


class AttendanceRecord(TenantModel):
    STATUS = [("present", "Present"), ("late", "Late"), ("absent", "Absent")]
    session   = models.ForeignKey(ClassSession, on_delete=models.CASCADE,
                                  related_name="records")
    student   = models.ForeignKey(Student, on_delete=models.CASCADE,
                                  related_name="records")
    status    = models.CharField(max_length=8, choices=STATUS)
    tapped_at = models.DateTimeField()
    device    = models.ForeignKey(Device, null=True, blank=True,
                                  on_delete=models.SET_NULL)
    verified  = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["session", "student"], name="uniq_attendance")]
        indexes = [models.Index(fields=["org", "student", "session"])]


class AuditLog(TenantModel):
    actor      = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action     = models.CharField(max_length=32)
    detail     = models.TextField(blank=True)
    ip         = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["org", "-created_at"])]
