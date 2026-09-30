"""Works out which lecture a device should be recording right now, judges
uploaded taps against the timetable, and packs the data the device needs
into the smallest form that works."""

import struct
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone
from core.models import (Card, Student, Enrollment, ClassSession,
                         TimetableSlot)

# The device is handed the roster a little before the lecture starts, so
# it is ready when the first student walks in. This is only about when
# the roster is delivered - it does not widen the window in which a tap
# counts. That window is judged here, on the server, by judge_taps().
LEAD_IN  = timedelta(minutes=20)
LEAD_OUT = timedelta(minutes=15)

# How early before the scheduled start a tap still counts. Zero means a
# tap only counts between the session's start and end times.
COUNT_FROM_BEFORE_START = timedelta(minutes=0)

# A tap older than this cannot be trusted to belong to any lecture we
# can still reconstruct, so it is stored but never counted.
MAX_TAP_AGE = timedelta(days=30)


def org_tz(org):
    """The institution's own timezone. Timetables are written in local
    time, so '09:00 Monday' means 09:00 in Lagos, not 09:00 UTC."""
    try:
        return ZoneInfo(org.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return dt_timezone.utc


def ensure_sessions_for_venue(org, venue, now=None, day=None):
    """Create a day's scheduled sessions from the timetable, if missing.
    Called lazily on device contact rather than by a scheduled job, so
    there is nothing extra to deploy. Pass day to fill in a past date,
    which is how taps from an offline lecture find their session."""
    if venue is None:
        return
    tz = org_tz(org)
    if day is None:
        day = (now or timezone.now()).astimezone(tz).date()

    slots = TimetableSlot.objects.filter(
        org=org, venue=venue, weekday=day.weekday(), active=True,
        term=org.term)

    for slot in slots.select_related("course"):
        starts = datetime.combine(day, slot.start_time, tzinfo=tz)
        if ClassSession.objects.filter(
                org=org, slot=slot, starts_at=starts).exists():
            continue
        ends = datetime.combine(day, slot.end_time, tzinfo=tz)
        ClassSession.objects.create(
            org=org, slot=slot, course=slot.course, venue=venue,
            starts_at=starts, ends_at=ends,
            grace_minutes=slot.grace_minutes, status="scheduled")


# A session a lecturer opened wins over a merely scheduled one, because
# an opened session is a deliberate act and handles reschedules. Sorting
# on the raw status string would put "scheduled" first.
_OPEN_FIRST = Case(When(status="open", then=Value(0)), default=Value(1),
                   output_field=IntegerField())


def active_session_for(device, now=None):
    """The lecture this device should hold a roster for, or None."""
    if device.venue_id is None:
        return None
    now = now or timezone.now()
    ensure_sessions_for_venue(device.org, device.venue, now)

    qs = ClassSession.objects.filter(
        org=device.org, venue=device.venue,
        starts_at__lte=now + LEAD_IN,
        ends_at__gte=now - LEAD_OUT,
    ).exclude(status__in=["closed", "cancelled"]).select_related("course")

    return qs.annotate(_rank=_OPEN_FIRST).order_by("_rank", "starts_at").first()


def judge_taps(device, taps):
    """Decide, from the server's clock and timetable, what each tap means.

    taps is a list of dicts with 'card' (an active Card or None) and
    'tapped_at' (an aware datetime, or None when the time is unknown).
    Returns a list of (outcome, session) in the same order.

    The device makes its own call so the student gets a beep at once, but
    that call is advisory. Its clock can be wrong and its roster stale;
    this is the decision that goes on the record."""
    org = device.org
    now = timezone.now()
    known = [t["tapped_at"] for t in taps if t["tapped_at"]]

    sessions = []
    if known and device.venue_id:
        # Offline taps may be from a day nobody has looked at yet, so
        # that day's timetable sessions may not exist. Create them first.
        tz = org_tz(org)
        for day in sorted({t.astimezone(tz).date() for t in known}):
            if day <= now.astimezone(tz).date():
                ensure_sessions_for_venue(org, device.venue, day=day)

        sessions = list(ClassSession.objects.filter(
            org=org, venue_id=device.venue_id,
            starts_at__lte=max(known) + COUNT_FROM_BEFORE_START,
            ends_at__gte=min(known),
        ).exclude(status="cancelled")
         .annotate(_rank=_OPEN_FIRST).order_by("_rank", "starts_at"))

    # One query for every enrolment these taps could need.
    student_ids = {t["card"].student_id for t in taps
                   if t["card"] and t["card"].student_id}
    course_ids = {s.course_id for s in sessions}
    enrolled = set(Enrollment.objects.filter(
        org=org, term=org.term, student_id__in=student_ids,
        course_id__in=course_ids).values_list("student_id", "course_id"))

    out = []
    for t in taps:
        card, when = t["card"], t["tapped_at"]
        if card is None:
            out.append(("unknown", None))
            continue
        if card.is_admin:
            out.append(("admin", None))
            continue
        if not card.student_id:
            out.append(("unknown", None))
            continue
        if when is None or when > now + timedelta(minutes=5) \
                or when < now - MAX_TAP_AGE:
            out.append(("time_unknown", None))
            continue

        session = next((s for s in sessions
                        if s.starts_at - COUNT_FROM_BEFORE_START
                        <= when <= s.ends_at), None)
        if session is None:
            out.append(("no_session", None))
            continue
        if (card.student_id, session.course_id) not in enrolled:
            out.append(("not_enrolled", session))
            continue
        grace_end = session.starts_at + timedelta(minutes=session.grace_minutes)
        out.append(("late" if when > grace_end else "present", session))
    return out


# A tap that did not count only because the setup was wrong at the time:
# no lecture found (reader not placed, lecture added to the timetable
# late) or the student not enrolled yet. "unknown" (card not registered)
# and "time_unknown" cannot change by being judged again.
RECHECKABLE = ("no_session", "not_enrolled")


def recheck_taps(taps):
    """Judge stored taps again against the timetable, enrolments and
    reader venues as they are now, and count the ones that now qualify.

    For after a mistake is fixed: a reader placed in its room late, a
    lecture added to the timetable after it happened, a student enrolled
    after they started attending. Returns (checked, newly_counted).
    Running it twice changes nothing the second time."""
    from core.models import AttendanceRecord, TapEvent
    taps = list(taps.select_related("device", "device__org", "device__venue")
                    .order_by("tapped_at"))
    checked = counted = 0
    by_device = {}
    for t in taps:
        by_device.setdefault(t.device_id, []).append(t)

    for group in by_device.values():
        device = group[0].device
        cards = {c.uid: c for c in Card.objects.filter(
            org=device.org, active=True, uid__in={t.uid for t in group})}
        pending = [{"card": cards.get(t.uid),
                    "tapped_at": None if t.time_conf == "unknown" else t.tapped_at}
                   for t in group]
        rows = []
        for t, (outcome, session) in zip(group, judge_taps(device, pending)):
            checked += 1
            card = cards.get(t.uid)
            if outcome == t.outcome and (session.id if session else None) == t.session_id:
                continue
            t.outcome, t.session = outcome, session
            t.student = card.student if card else t.student
            TapEvent.objects.filter(pk=t.pk).update(
                outcome=outcome, session=session, student=t.student)
            if outcome in ("present", "late"):
                counted += 1
                rows.append(AttendanceRecord(
                    org=t.org, session=session, student_id=t.student_id,
                    status=outcome, tapped_at=t.tapped_at, device=device,
                    verified=(t.time_conf == "synced")))
        # Earliest tap first, so a student's first tap in a lecture is the
        # one that sets present or late.
        if rows:
            AttendanceRecord.objects.bulk_create(rows, ignore_conflicts=True)
    return checked, counted


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
# width records rather than JSON: 14 bytes instead of roughly 40.
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


# Format 2: the same records plus the holder's name for the reader's
# display, served in pages.
#
#   header:  magic 'SLM2' | version u32 | total u32 | offset u32 | count u32
#   record:  uid[10] | len u8 | student_id u16 | flags u8 | name[16]
#
# 400 records x 30 bytes = 12 KB, inside the reader's 16 KB buffer.

DIR2_MAGIC = b"SLM2"
DIR2_HDR   = struct.Struct("<4sIIII")
DIR2_REC   = struct.Struct("<10sBHB16s")
DIR2_PAGE  = 400


def display_name(text):
    """What fits on one line of the reader's 16-character display. The
    display only has ASCII, so accents are dropped rather than garbled."""
    import unicodedata
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(plain.split()).upper()[:16].encode("ascii")


def pack_directory_v2(org, offset=0, limit=DIR2_PAGE):
    cards = (Card.objects.filter(org=org, active=True)
             .select_related("student", "holder")
             .only("uid", "student_id", "is_admin", "student__short_name",
                   "student__full_name", "holder__first_name", "holder__last_name"))
    rows = []
    for c in cards:
        if len(c.uid) % 2 or len(c.uid) > 20:
            continue
        raw = bytes.fromhex(c.uid)
        if c.student_id:
            name = c.student.short_name or c.student.full_name
        elif c.holder_id:
            name = c.holder.get_full_name()
        else:
            name = ""
        rows.append((raw, len(raw), (c.student_id or 0) % 65536,
                     1 if c.is_admin else 0, display_name(name)))
    # Same order as format 1, so the reader can binary search it as-is.
    rows.sort(key=lambda r: (r[0][:r[1]], r[1]))

    version = _directory_version(org)
    page = rows[offset:offset + limit]
    out = bytearray(DIR2_HDR.pack(DIR2_MAGIC, version, len(rows), offset, len(page)))
    for raw, length, sid, flags, name in page:
        out += DIR2_REC.pack(raw.ljust(10, b"\x00"), length, sid, flags,
                             name.ljust(16, b"\x00"))
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
