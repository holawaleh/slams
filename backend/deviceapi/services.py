"""Works out which lecture a device should be recording right now, and
packs the data the device needs into the smallest form that works."""

import struct
from datetime import timedelta
from django.db.models import Q
from django.utils import timezone
from core.models import (Card, Student, Enrollment, ClassSession,
                         TimetableSlot)

# Devices accept a session that has not quite started or has just ended,
# so a student tapping on the way in is not rejected by a minute.
LEAD_IN  = timedelta(minutes=20)
LEAD_OUT = timedelta(minutes=15)


def ensure_sessions_for_venue(org, venue, now=None):
    """Create today's scheduled sessions from the timetable, if missing.
    Called lazily on device contact rather than by a scheduled job, so
    there is nothing extra to deploy."""
    if venue is None:
        return
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    weekday = today.weekday()

    slots = TimetableSlot.objects.filter(
        org=org, venue=venue, weekday=weekday, active=True, term=org.term)

    for slot in slots.select_related("course"):
        starts = timezone.make_aware(
            timezone.datetime.combine(today, slot.start_time),
            timezone.get_current_timezone())
        if ClassSession.objects.filter(
                org=org, slot=slot, starts_at=starts).exists():
            continue
        ends = timezone.make_aware(
            timezone.datetime.combine(today, slot.end_time),
            timezone.get_current_timezone())
        ClassSession.objects.create(
            org=org, slot=slot, course=slot.course, venue=venue,
            starts_at=starts, ends_at=ends,
            grace_minutes=slot.grace_minutes, status="scheduled")


def active_session_for(device, now=None):
    """The lecture this device should record for, or None.

    A session a lecturer opened wins over a merely scheduled one, because
    an opened session is a deliberate act and handles reschedules."""
    if device.venue_id is None:
        return None
    now = now or timezone.now()
    ensure_sessions_for_venue(device.org, device.venue, now)

    qs = ClassSession.objects.filter(
        org=device.org, venue=device.venue,
        starts_at__lte=now + LEAD_IN,
        ends_at__gte=now - LEAD_OUT,
    ).exclude(status__in=["closed", "cancelled"]).select_related("course")

    return qs.order_by("-status", "starts_at").first()


def roster_for(session):
    """Students enrolled on the session's course, with display names."""
    if session is None:
        return []
    return list(
        Student.objects.filter(
            org=session.org, active=True,
            enrollments__course=session.course,
            enrollments__term=session.org.term,
        ).values("id", "short_name").order_by("id").distinct())


def bundle_version(session, org):
    """Changes whenever anything the device caches changes, so the device
    can ask 'is this still current?' with one integer."""
    if session is None:
        return 0
    enrolled = Enrollment.objects.filter(
        org=org, course=session.course, term=org.term).count()
    return (session.id * 1000000) + (session.roster_version * 1000) + enrolled


# ---- binary packing ----
# The directory is the large payload, so it goes over the wire as fixed
# width records rather than JSON: 11 bytes instead of roughly 40.
#
#   header:  magic 'SLMD' | version u32 | count u32
#   record:  uid[10] | len u8 | student_id u16 | flags u8

DIR_MAGIC = b"SLMD"
DIR_REC   = struct.Struct("<10sBHB")
DIR_HDR   = struct.Struct("<4sII")


def pack_directory(org):
    """All active cards for this org, as one compact block."""
    cards = (Card.objects.filter(org=org, active=True)
             .values("uid", "student_id", "is_admin"))

    rows = []
    for c in cards:
        hexstr = c["uid"]
        if len(hexstr) % 2 or len(hexstr) > 20:
            continue
        raw = bytes.fromhex(hexstr)
        rows.append((raw, len(raw),
                     (c["student_id"] or 0) % 65536,
                     1 if c["is_admin"] else 0))

    # Sorted here so the device can binary search without sorting itself.
    rows.sort(key=lambda r: (r[0][:r[1]], r[1]))

    version = _directory_version(org)
    out = bytearray(DIR_HDR.pack(DIR_MAGIC, version, len(rows)))
    for raw, length, sid, flags in rows:
        out += DIR_REC.pack(raw.ljust(10, b"\x00"), length, sid, flags)
    return bytes(out), version, len(rows)


def _directory_version(org):
    """Derived from the newest card change, so no extra column is needed."""
    from django.db.models import Max
    agg = Card.objects.filter(org=org).aggregate(
        last_issue=Max("issued_at"), last_revoke=Max("revoked_at"))
    stamps = [t for t in (agg["last_issue"], agg["last_revoke"]) if t]
    if not stamps:
        return 0
    newest = max(stamps)
    count = Card.objects.filter(org=org, active=True).count()
    return int(newest.timestamp()) ^ (count << 16)
