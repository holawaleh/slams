from django.contrib import admin
from .tenancy import Organization, Membership, Invitation
from .models import (Student, Card, Venue, Course, Enrollment, Device,
                     TimetableSlot, ClassSession, TapEvent,
                     AttendanceRecord, AuditLog)


class OrgScopedAdmin(admin.ModelAdmin):
    """Django admin is for you as operator, not for tenants. Org is shown
    on every list so cross-tenant confusion is impossible."""
    list_select_related = ("org",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display  = ("name", "slug", "country", "term", "active", "created_at")
    search_fields = ("name", "slug")
    list_filter   = ("active", "country")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display  = ("user", "org", "role", "is_default", "joined_at")
    list_filter   = ("role", "org")
    search_fields = ("user__username", "org__name")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "org", "role", "accepted", "expires_at")
    list_filter  = ("accepted", "org")


@admin.register(Student)
class StudentAdmin(OrgScopedAdmin):
    list_display  = ("matric_no", "last_name", "first_name", "short_name",
                     "org", "active")
    search_fields = ("matric_no", "last_name", "first_name")
    list_filter   = ("org", "active", "department", "level")


@admin.register(Card)
class CardAdmin(OrgScopedAdmin):
    list_display  = ("uid", "org", "student", "is_admin", "active", "issued_at")
    search_fields = ("uid", "student__matric_no")
    list_filter   = ("org", "active", "is_admin")


@admin.register(Device)
class DeviceAdmin(OrgScopedAdmin):
    list_display    = ("name", "org", "venue", "active", "enroll_mode",
                       "last_seen", "queue_depth", "firmware")
    list_filter     = ("org", "active")
    readonly_fields = ("token",)


@admin.register(ClassSession)
class ClassSessionAdmin(OrgScopedAdmin):
    list_display = ("course", "org", "venue", "starts_at", "status")
    list_filter  = ("org", "status")


@admin.register(TapEvent)
class TapEventAdmin(OrgScopedAdmin):
    list_display  = ("received_at", "org", "device", "uid", "student", "outcome")
    list_filter   = ("org", "outcome", "time_conf")
    search_fields = ("uid",)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(OrgScopedAdmin):
    list_display = ("session", "org", "student", "status", "tapped_at", "verified")
    list_filter  = ("org", "status", "verified")


admin.site.register([Venue, Course, Enrollment, TimetableSlot, AuditLog])
admin.site.site_header = "SLAM Administration"
