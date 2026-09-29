from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (AttendanceRecord, Card, ClassSession, Course, Device,
                         Enrollment, Student, TapEvent, TimetableSlot, Venue)
from core.tenancy import Organization
from .services import ensure_sessions_for_venue


class TimingTests(TestCase):
    """The server decides whether a tap counts, from its own clock and the
    session's start and end. The device's verdict is advisory."""

    def setUp(self):
        self.org = Organization.objects.create(
            name="Test Uni", slug="test-uni", timezone="Africa/Lagos")
        self.venue = Venue.objects.create(org=self.org, code="LT1", name="LT1")
        self.course = Course.objects.create(org=self.org, code="CSC101",
                                            title="Intro")
        self.student = Student.objects.create(
            org=self.org, matric_no="M001", first_name="Ada", last_name="Obi")
        Enrollment.objects.create(org=self.org, student=self.student,
                                  course=self.course, term=self.org.term)
        Card.objects.create(org=self.org, uid="0A3F05B2", student=self.student)
        self.device = Device.objects.create(org=self.org, name="R1",
                                            venue=self.venue)
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Device {self.device.token}")

    def session(self, start_offset_min, length_min=60, grace=15):
        now = timezone.now()
        starts = now + timedelta(minutes=start_offset_min)
        return ClassSession.objects.create(
            org=self.org, course=self.course, venue=self.venue,
            starts_at=starts, ends_at=starts + timedelta(minutes=length_min),
            grace_minutes=grace)

    def upload(self, *records):
        r = self.api.post("/api/device/attendance/",
                          {"records": list(records)}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def rec(self, cid, **kw):
        base = {"client_id": cid, "uid": "0A3F05B2", "outcome": "present"}
        base.update(kw)
        return base

    def test_tap_inside_window_counts_present(self):
        s = self.session(-5)
        out = self.upload(self.rec(1, age_ms=0))
        self.assertEqual(out["results"][0]["outcome"], "present")
        a = AttendanceRecord.objects.get()
        self.assertEqual((a.session_id, a.status, a.verified), (s.id, "present", True))

    def test_tap_after_grace_is_late(self):
        self.session(-30, grace=15)
        out = self.upload(self.rec(1, age_ms=0))
        self.assertEqual(out["results"][0]["outcome"], "late")
        self.assertEqual(AttendanceRecord.objects.get().status, "late")

    def test_tap_before_start_does_not_count(self):
        # The device may already hold the roster (it is sent early), and
        # may have said "present". The server still refuses it.
        self.session(+10)
        out = self.upload(self.rec(1, age_ms=0))
        self.assertEqual(out["results"][0]["outcome"], "no_session")
        self.assertFalse(AttendanceRecord.objects.exists())
        tap = TapEvent.objects.get()
        self.assertEqual((tap.outcome, tap.device_outcome), ("no_session", "present"))

    def test_tap_after_end_does_not_count(self):
        self.session(-70, length_min=60)
        out = self.upload(self.rec(1, age_ms=0))
        self.assertEqual(out["results"][0]["outcome"], "no_session")
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_offline_tap_is_placed_by_its_age_not_upload_time(self):
        # Lecture ran 3h ago to 2h ago. The tap was made 2.5h ago and is
        # only uploaded now: it must land inside that lecture.
        s = self.session(-180, length_min=60)
        out = self.upload(self.rec(1, age_ms=150 * 60 * 1000,
                                   ts_utc=0, time_conf="unknown"))
        self.assertEqual(out["results"][0]["outcome"], "late")
        self.assertEqual(AttendanceRecord.objects.get().session_id, s.id)

    def test_device_clock_is_ignored_when_age_is_present(self):
        self.session(-5)
        wrong = int((timezone.now() - timedelta(days=3)).timestamp())
        out = self.upload(self.rec(1, age_ms=0, ts_utc=wrong,
                                   time_conf="synced"))
        self.assertEqual(out["results"][0]["outcome"], "present")

    def test_unknown_time_never_counts(self):
        self.session(-5)
        out = self.upload(self.rec(1, ts_utc=0, time_conf="unknown"))
        self.assertEqual(out["results"][0]["outcome"], "time_unknown")
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_drifting_clock_counts_but_unverified(self):
        self.session(-5)
        ts = int(timezone.now().timestamp())
        self.upload(self.rec(1, ts_utc=ts, time_conf="drift"))
        self.assertFalse(AttendanceRecord.objects.get().verified)

    def test_not_enrolled_is_decided_by_server(self):
        Enrollment.objects.all().delete()
        self.session(-5)
        out = self.upload(self.rec(1, age_ms=0))
        self.assertEqual(out["results"][0]["outcome"], "not_enrolled")
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_cancelled_session_does_not_count(self):
        s = self.session(-5)
        s.status = "cancelled"
        s.save()
        out = self.upload(self.rec(1, age_ms=0))
        self.assertEqual(out["results"][0]["outcome"], "no_session")

    def test_revoked_card_does_not_count(self):
        Card.objects.update(active=False)
        self.session(-5)
        out = self.upload(self.rec(1, age_ms=0))
        self.assertEqual(out["results"][0]["outcome"], "unknown")
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_replay_is_harmless(self):
        self.session(-5)
        self.upload(self.rec(7, age_ms=0))
        self.upload(self.rec(7, age_ms=0))
        self.assertEqual(TapEvent.objects.count(), 1)
        self.assertEqual(AttendanceRecord.objects.count(), 1)

    def test_hello_returns_millisecond_time(self):
        before = timezone.now().timestamp() * 1000
        r = self.api.post("/api/device/hello/", {}, format="json").json()
        self.assertGreaterEqual(r["server_utc_ms"], before - 1)
        self.assertLess(r["server_utc_ms"] - before, 5000)

    def test_timetable_uses_org_timezone(self):
        # 09:00 on the timetable means 09:00 in Lagos (UTC+1), i.e. 08:00Z.
        lagos = ZoneInfo("Africa/Lagos")
        day = timezone.now().astimezone(lagos).date()
        TimetableSlot.objects.create(
            org=self.org, course=self.course, venue=self.venue,
            weekday=day.weekday(), start_time=time(9), end_time=time(11),
            term=self.org.term)
        ensure_sessions_for_venue(self.org, self.venue, day=day)
        s = ClassSession.objects.get()
        self.assertEqual(s.starts_at, datetime.combine(day, time(9), tzinfo=lagos))
        self.assertEqual(s.starts_at.astimezone(ZoneInfo("UTC")).hour, 8)

    def test_opened_session_wins_over_scheduled(self):
        from .services import active_session_for
        self.session(-5)
        opened = self.session(-5)
        opened.status = "open"
        opened.save()
        self.assertEqual(active_session_for(self.device).id, opened.id)
