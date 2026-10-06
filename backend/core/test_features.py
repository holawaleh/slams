from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (AttendanceRecord, Card, ClassSession, Course, Device,
                     Enrollment, Student, TapEvent, Venue)
from .tenancy import Membership, Organization


def owner_of(slug):
    org = Organization.objects.create(name=slug, slug=slug)
    u = User.objects.create_user(f"o-{slug}", password="x")
    Membership.objects.create(user=u, org=org, role=Membership.OWNER)
    api = APIClient()
    api.force_authenticate(u)
    return org, api


class StudentFormTests(TestCase):
    def setUp(self):
        self.org, self.api = owner_of("uni")
        self.reader = Device.objects.create(org=self.org, name="R1")
        self.n = 0
        self.matric = 0

    def seen(self, uid):
        """A reader in this school has just read the card."""
        self.n += 1
        TapEvent.objects.create(org=self.org, device=self.reader, uid=uid,
                                outcome="unknown", tapped_at=timezone.now(),
                                client_id=self.n)

    def add(self, **kw):
        self.matric += 1
        body = {"full_name": "Adeyemi  Holawale", "phone": "0803 123 4567",
                "department": "Computer Engineering", "level": "400",
                "email": "Ade@Example.com", "matric_no": f"m{self.matric}", **kw}
        return self.api.post("/api/students/", body, format="json")

    def test_add_with_captured_card_binds_it(self):
        self.seen("0A3F05B2")
        r = self.add(card_uid="0a:3f:05:b2")
        self.assertEqual(r.status_code, 201, r.content)
        s = Student.objects.get()
        self.assertEqual((s.full_name, s.phone, s.email, s.matric_no),
                         ("Adeyemi Holawale", "08031234567", "ade@example.com", "M1"))
        self.assertEqual(Card.objects.get().student, s)

    def test_typed_card_number_is_refused(self):
        r = self.add(card_uid="0A3F05B2")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Scan the card", str(r.json()))
        self.assertFalse(Student.objects.exists())

    def test_card_seen_only_by_another_school_is_refused(self):
        other, _ = owner_of("other")
        dev = Device.objects.create(org=other, name="X")
        TapEvent.objects.create(org=other, device=dev, uid="0A3F05B2",
                                outcome="unknown", tapped_at=timezone.now(),
                                client_id=1)
        self.assertEqual(self.add(card_uid="0A3F05B2").status_code, 400)

    def test_old_sighting_is_not_enough(self):
        self.seen("0A3F05B2")
        TapEvent.objects.update(received_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.add(card_uid="0A3F05B2").status_code, 400)

    def test_matric_is_required_and_unique(self):
        self.assertEqual(self.add(matric_no="").status_code, 400)
        self.assertEqual(self.add(matric_no="M100").status_code, 201)
        self.assertEqual(self.add(full_name="Other", matric_no="m100").status_code, 400)

    def test_student_without_card_can_get_one_later(self):
        sid = self.add().json()["id"]
        self.seen("0A3F05B2")
        r = self.api.patch(f"/api/students/{sid}/", {"card_uid": "0A3F05B2"},
                           format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Card.objects.get().student_id, sid)

    def test_card_already_taken_is_refused_and_student_not_created(self):
        self.seen("0A3F05B2")
        self.add(card_uid="0A3F05B2")
        r = self.add(full_name="Other Student", card_uid="0A3F05B2")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Adeyemi Holawale", str(r.json()))
        self.assertEqual(Student.objects.count(), 1)

    def test_bad_phone_rejected(self):
        self.assertEqual(self.add(phone="call me").status_code, 400)

    def test_new_card_on_edit_replaces_the_old(self):
        self.seen("0A3F05B2")
        sid = self.add(card_uid="0A3F05B2").json()["id"]
        self.seen("11223344")
        r = self.api.patch(f"/api/students/{sid}/", {"card_uid": "11223344"},
                           format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(Card.objects.get(uid="0A3F05B2").active)
        self.assertTrue(Card.objects.get(uid="11223344").active)

    def test_saving_without_changing_card_is_fine_later(self):
        self.seen("0A3F05B2")
        sid = self.add(card_uid="0A3F05B2").json()["id"]
        TapEvent.objects.all().delete()
        r = self.api.patch(f"/api/students/{sid}/", {"card_uid": "0A3F05B2",
                                                     "level": "500"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_search_and_filter_by_level(self):
        self.add(level="200", full_name="Level Two")
        self.add(level="400", full_name="Level Four")
        rows = self.api.get("/api/students/", {"level": "200"}).json()["results"]
        self.assertEqual([r["full_name"] for r in rows], ["Level Two"])
        rows = self.api.get("/api/students/", {"search": "400"}).json()["results"]
        self.assertEqual([r["full_name"] for r in rows], ["Level Four"])
        self.assertEqual(self.api.get("/api/students/levels/").json(), ["200", "400"])


class CaptureTests(TestCase):
    def setUp(self):
        self.org, self.api = owner_of("uni")
        self.device = Device.objects.create(org=self.org, name="R1")

    def tap(self, uid, cid):
        TapEvent.objects.create(org=self.org, device=self.device, uid=uid,
                                outcome="unknown", tapped_at=timezone.now(),
                                client_id=cid)

    def capture(self, since):
        return self.api.get("/api/cards/capture/", {
            "device": self.device.pk, "since": since.isoformat()}).json()

    def test_waits_then_returns_the_next_card(self):
        start = timezone.now()
        self.tap("AAAA0001", 1)                        # before: ignored?
        TapEvent.objects.filter(client_id=1).update(
            received_at=start - timedelta(seconds=5))
        self.assertIsNone(self.capture(start)["uid"])
        self.tap("0A3F05B2", 2)
        out = self.capture(start)
        self.assertEqual((out["uid"], out["state"]), ("0A3F05B2", "new"))

    def test_reports_a_card_that_is_already_someone_elses(self):
        s = Student.objects.create(org=self.org, full_name="Taken Person",
                                   matric_no="T1")
        Card.objects.create(org=self.org, uid="0A3F05B2", student=s)
        start = timezone.now() - timedelta(seconds=1)
        self.tap("0A3F05B2", 3)
        out = self.capture(start)
        self.assertEqual((out["state"], out["student"]), ("taken", "Taken Person"))

    def test_other_schools_reader_is_not_usable(self):
        other, _ = owner_of("other")
        dev = Device.objects.create(org=other, name="X")
        r = self.api.get("/api/cards/capture/", {
            "device": dev.pk, "since": timezone.now().isoformat()})
        self.assertEqual(r.status_code, 400)


class CardSummaryTests(TestCase):
    def setUp(self):
        self.org, self.api = owner_of("uni")
        self.device = Device.objects.create(org=self.org, name="R1")
        self.n = 0

    def card(self, uid, taps_recent=0, taps_old=0, **kw):
        s = Student.objects.create(org=self.org, full_name=f"S {uid}",
                                   matric_no=uid)
        c = Card.objects.create(org=self.org, uid=uid, student=s, **kw)
        Card.objects.filter(pk=c.pk).update(
            issued_at=timezone.now() - timedelta(days=90))
        for days, n in ((1, taps_recent), (60, taps_old)):
            for _ in range(n):
                self.n += 1
                TapEvent.objects.create(
                    org=self.org, device=self.device, uid=uid, outcome="present",
                    tapped_at=timezone.now() - timedelta(days=days),
                    client_id=self.n)
        return c

    def test_summary_and_usage_filters(self):
        self.card("00000001")                          # never used
        self.card("00000002", taps_old=5)              # rarely used lately
        self.card("00000003", taps_recent=1)           # rarely used
        self.card("00000004", taps_recent=6)           # regular
        self.card("00000005", active=False)            # revoked
        out = self.api.get("/api/cards/summary/").json()
        self.assertEqual(
            {k: out[k] for k in ("total", "active", "revoked", "never_used",
                                 "rarely_used", "regular")},
            {"total": 5, "active": 4, "revoked": 1, "never_used": 1,
             "rarely_used": 2, "regular": 1})

        def uids(**q):
            return sorted(r["uid"] for r in
                          self.api.get("/api/cards/", q).json()["results"])
        self.assertEqual(uids(usage="never", status="active"), ["00000001"])
        self.assertEqual(uids(usage="rare"), ["00000002", "00000003"])
        self.assertEqual(uids(status="revoked"), ["00000005"])
        row = self.api.get("/api/cards/", {"search": "00000004"}).json()["results"][0]
        self.assertEqual((row["uses_30d"], row["uses_total"]), (6, 6))

    def test_revoke_then_restore(self):
        c = self.card("00000009")
        self.api.delete(f"/api/cards/{c.pk}/")
        c.refresh_from_db()
        self.assertFalse(c.active)
        self.assertIsNotNone(c.revoked_at)
        self.api.patch(f"/api/cards/{c.pk}/", {"active": True}, format="json")
        c.refresh_from_db()
        self.assertTrue(c.active)
        self.assertIsNone(c.revoked_at)


class ReaderOwnershipTests(TestCase):
    HW = "A4:CF:12:34:56:78"

    def setUp(self):
        self.org_a, self.a = owner_of("alpha")
        self.org_b, self.b = owner_of("beta")

    def add(self, api, hw=HW, name="Hall reader"):
        return api.post("/api/devices/", {"name": name, "hardware_id": hw},
                        format="json")

    def test_one_reader_one_account(self):
        r = self.add(self.a, hw="a4cf12345678")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["hardware_id"], self.HW)

        r = self.add(self.b)
        self.assertEqual(r.status_code, 400)
        msg = str(r.json())
        self.assertIn("another account", msg)
        self.assertNotIn("alpha", msg)

        r = self.add(self.a, name="Again")
        self.assertIn("already registered here", str(r.json()))

    def test_removing_frees_the_reader_and_keeps_history(self):
        dev_id = self.add(self.a).json()["id"]
        dev = Device.objects.get(pk=dev_id)
        TapEvent.objects.create(org=self.org_a, device=dev, uid="0A0B0C0D",
                                outcome="unknown", tapped_at=timezone.now(),
                                client_id=1)
        old_token = dev.token
        self.assertEqual(self.a.delete(f"/api/devices/{dev_id}/").status_code, 204)
        dev.refresh_from_db()
        self.assertFalse(dev.active)
        self.assertIsNone(dev.hardware_id)
        self.assertNotEqual(dev.token, old_token)
        self.assertEqual(TapEvent.objects.count(), 1)
        self.assertEqual(self.add(self.b).status_code, 201)

    def hello(self, token, hw):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Device {token}",
                      HTTP_X_DEVICE_ID=hw)
        return c.post("/api/device/hello/", {}, format="json")

    def test_token_only_works_from_its_own_reader(self):
        dev = Device.objects.get(pk=self.add(self.a).json()["id"])
        self.assertEqual(self.hello(dev.token, self.HW).status_code, 200)
        self.assertEqual(self.hello(dev.token, "11:22:33:44:55:66").status_code, 403)
        self.assertEqual(self.hello(dev.token, "").status_code, 403)

    def test_refused_token_has_no_auth_challenge(self):
        # ESP-IDF's HTTP client chokes on "WWW-Authenticate: Device" and
        # hides the status, so a removed reader never went back to pairing.
        r = self.hello("no-such-token", self.HW)
        self.assertEqual(r.status_code, 403)
        self.assertNotIn("WWW-Authenticate", r.headers)

    def test_old_entry_claims_its_reader_unless_registered_elsewhere(self):
        legacy = Device.objects.create(org=self.org_b, name="Old")
        self.add(self.a)                                 # HW now belongs to A
        self.assertEqual(self.hello(legacy.token, self.HW).status_code, 403)
        self.assertEqual(self.hello(legacy.token, "11:22:33:44:55:66").status_code, 200)
        legacy.refresh_from_db()
        self.assertEqual(legacy.hardware_id, "11:22:33:44:55:66")


class ReportTests(TestCase):
    def setUp(self):
        self.org, self.api = owner_of("uni")
        self.venue = Venue.objects.create(org=self.org, code="LT1", name="LT1")
        self.course = Course.objects.create(org=self.org, code="CSC101", title="x")
        self.s = [Student.objects.create(org=self.org, full_name=f"Student {i}",
                                         matric_no=f"M{i}")
                  for i in range(3)]
        for s in self.s:
            Enrollment.objects.create(org=self.org, student=s, course=self.course,
                                      term=self.org.term)
        now = timezone.now()
        self.lectures = [ClassSession.objects.create(
            org=self.org, course=self.course, venue=self.venue,
            starts_at=now - timedelta(days=d), ends_at=now - timedelta(days=d, hours=-1))
            for d in (3, 2, 1)]
        ClassSession.objects.create(               # future: not held yet
            org=self.org, course=self.course, venue=self.venue,
            starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, hours=1))
        ClassSession.objects.create(               # cancelled: never counts
            org=self.org, course=self.course, venue=self.venue, status="cancelled",
            starts_at=now - timedelta(days=4), ends_at=now - timedelta(days=4, hours=-1))
        # Student 0 attends all three, student 1 one (late), student 2 none.
        for lec in self.lectures:
            AttendanceRecord.objects.create(org=self.org, session=lec,
                                            student=self.s[0], status="present",
                                            tapped_at=lec.starts_at)
        AttendanceRecord.objects.create(org=self.org, session=self.lectures[0],
                                        student=self.s[1], status="late",
                                        tapped_at=self.lectures[0].starts_at)

    def test_course_register(self):
        out = self.api.get(f"/api/reports/course/{self.course.pk}/").json()
        self.assertEqual(out["held"], 3)
        rows = {r["full_name"]: r for r in out["students"]}
        self.assertEqual((rows["Student 0"]["percentage"], rows["Student 0"]["at_risk"]),
                         (100.0, False))
        self.assertEqual((rows["Student 1"]["late"], rows["Student 1"]["absent"]), (1, 2))
        self.assertTrue(rows["Student 2"]["at_risk"])

    def test_overview(self):
        row = self.api.get("/api/reports/overview/").json()["courses"][0]
        self.assertEqual((row["held"], row["enrolled"], row["at_risk"]), (3, 3, 2))
        self.assertEqual(row["attendance_rate"], round(100 * 4 / 9, 1))

    def test_csv_export(self):
        r = self.api.get(f"/api/reports/course/{self.course.pk}/", {"export": "csv"})
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        body = r.content.decode("utf-8-sig")
        self.assertIn("Student 0", body)
        self.assertIn(",P,P,P,3,0,0,100.0", body)

    def test_lecturer_only_sees_own_courses(self):
        lect = User.objects.create_user("lect", password="x")
        Membership.objects.create(user=lect, org=self.org, role=Membership.LECTURER)
        c = APIClient()
        c.force_authenticate(lect)
        self.assertEqual(c.get("/api/reports/overview/").json()["courses"], [])
        self.assertEqual(c.get(f"/api/reports/course/{self.course.pk}/").status_code, 404)

    def test_other_school_cannot_read_report(self):
        _, other = owner_of("other")
        self.assertEqual(other.get(f"/api/reports/course/{self.course.pk}/").status_code, 404)


class RecheckTests(TestCase):
    """Taps that did not count because the setup was wrong at the time
    are counted once it is fixed - exactly what happened on the bench:
    a reader used for a whole lecture before it was given a venue."""

    def setUp(self):
        self.org, self.api = owner_of("uni")
        self.venue = Venue.objects.create(org=self.org, code="LT1", name="LT1")
        self.course = Course.objects.create(org=self.org, code="CSC101", title="x")
        self.student = Student.objects.create(org=self.org, full_name="Ada Obi",
                                              matric_no="M1")
        Card.objects.create(org=self.org, uid="0A0B0C0D", student=self.student)
        Enrollment.objects.create(org=self.org, student=self.student,
                                  course=self.course, term=self.org.term)
        now = timezone.now()
        self.session = ClassSession.objects.create(
            org=self.org, course=self.course, venue=self.venue,
            starts_at=now - timedelta(hours=2), ends_at=now - timedelta(minutes=30))
        self.device = Device.objects.create(org=self.org, name="R1")   # no venue
        for i, minutes in enumerate((100, 95)):
            TapEvent.objects.create(
                org=self.org, device=self.device, uid="0A0B0C0D",
                student=self.student, outcome="no_session",
                tapped_at=now - timedelta(minutes=minutes), client_id=i)

    def test_first_placement_counts_the_earlier_taps(self):
        r = self.api.patch(f"/api/devices/{self.device.pk}/",
                           {"venue": self.venue.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        rec = AttendanceRecord.objects.get()
        self.assertEqual((rec.session, rec.status), (self.session, "late"))
        self.assertEqual(set(TapEvent.objects.values_list("outcome", flat=True)), {"late"})

    def test_moving_a_placed_reader_does_not_rejudge(self):
        other = Venue.objects.create(org=self.org, code="LT2", name="LT2")
        Device.objects.filter(pk=self.device.pk).update(venue=other)
        self.api.patch(f"/api/devices/{self.device.pk}/", {"venue": self.venue.pk},
                       format="json")
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_manual_recheck_after_late_enrolment(self):
        Device.objects.filter(pk=self.device.pk).update(venue=self.venue)
        Enrollment.objects.all().delete()
        r = self.api.post("/api/reports/recheck/", {}, format="json")
        self.assertEqual(r.json()["counted"], 0)
        self.assertEqual(TapEvent.objects.first().outcome, "not_enrolled")
        Enrollment.objects.create(org=self.org, student=self.student,
                                  course=self.course, term=self.org.term)
        r = self.api.post("/api/reports/recheck/", {}, format="json")
        self.assertEqual((r.json()["checked"], r.json()["counted"]), (2, 2))
        self.assertEqual(AttendanceRecord.objects.count(), 1)       # one per lecture
        again = self.api.post("/api/reports/recheck/", {}, format="json").json()
        self.assertEqual(again["checked"], 0)                        # nothing left to fix

    def test_recheck_is_admin_only(self):
        u = User.objects.create_user("lect", password="x")
        Membership.objects.create(user=u, org=self.org, role=Membership.LECTURER)
        c = APIClient()
        c.force_authenticate(u)
        self.assertEqual(c.post("/api/reports/recheck/", {}, format="json").status_code, 403)
