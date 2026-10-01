"""The requests each dashboard page makes, exactly as the frontend sends
them, for every role that can open that page.

When a page and the API drift apart - a renamed field, a permission that
does not match the menu - this is the test that fails, instead of a user
meeting an error screen."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (AttendanceRecord, Card, ClassSession, Course, Device,
                     Enrollment, Student, TapEvent, TimetableSlot, Venue)
from .tenancy import Membership, Organization

PW = "Xk9!mQ2#vLp7"


class FrontendContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        org = cls.org = Organization.objects.create(name="Uni", slug="uni")
        cls.users = {}
        for role in ("owner", "admin", "lecturer", "viewer"):
            u = User.objects.create_user(role, password=PW, first_name=role.title())
            Membership.objects.create(user=u, org=org, role=role)
            cls.users[role] = u
        venue = Venue.objects.create(org=org, code="LT1", name="Hall")
        cls.course = Course.objects.create(org=org, code="CSC101", title="Intro",
                                           lecturer=cls.users["lecturer"])
        cls.student = Student.objects.create(org=org, full_name="Ada Obi",
                                             matric_no="M1", level="200")
        Enrollment.objects.create(org=org, student=cls.student, course=cls.course,
                                  term=org.term)
        Card.objects.create(org=org, uid="0A0B0C0D", student=cls.student)
        cls.device = Device.objects.create(org=org, name="R1", venue=venue,
                                           hardware_id="A4:CF:12:34:56:78")
        TimetableSlot.objects.create(org=org, course=cls.course, venue=venue,
                                     weekday=0, start_time="09:00",
                                     end_time="11:00", term=org.term)
        now = timezone.now()
        s = ClassSession.objects.create(org=org, course=cls.course, venue=venue,
                                        starts_at=now - timedelta(minutes=10),
                                        ends_at=now + timedelta(minutes=50))
        AttendanceRecord.objects.create(org=org, session=s, student=cls.student,
                                        status="present", tapped_at=now)
        TapEvent.objects.create(org=org, device=cls.device, uid="0A0B0C0D",
                                student=cls.student, session=s, outcome="present",
                                tapped_at=now, client_id=1)

    def as_(self, role):
        c = APIClient()
        c.force_authenticate(self.users[role])
        return c

    def ok(self, client, url, params=None, keys=()):
        r = client.get(url, params or {})
        self.assertEqual(r.status_code, 200, f"{url} {params}: {r.content[:200]}")
        data = r.json()
        body = data["results"][0] if isinstance(data, dict) and data.get("results") else data
        for k in keys:
            self.assertIn(k, body, f"{url} is missing '{k}'")
        return data

    # ---- pages every signed-in person has ----
    def test_pages_for_every_role(self):
        sid, cid = self.student.pk, self.course.pk
        for role in ("owner", "admin", "lecturer", "viewer"):
            with self.subTest(role=role):
                c = self.as_(role)
                me = self.ok(c, "/api/me/", keys=("user", "current_org"))
                self.assertEqual(set(me["current_org"]) >= {"role", "term", "timezone", "name"}, True)
                self.ok(c, "/api/organization/", keys=("student_count", "member_count", "term"))
                # Students
                self.ok(c, "/api/students/", {"page": 1, "search": "", "active": "true",
                                              "level": "200", "has_card": "true"},
                        keys=("full_name", "matric_no", "phone", "email", "level", "cards"))
                self.ok(c, "/api/students/levels/")
                self.ok(c, "/api/enrollments/", {"student": sid, "term": self.org.term})
                self.ok(c, f"/api/students/{sid}/attendance/")
                # Courses
                self.ok(c, "/api/courses/", {"page": 1, "search": ""},
                        keys=("code", "title", "lecturer_name", "enrolled_count"))
                self.ok(c, f"/api/courses/{cid}/")
                self.ok(c, "/api/enrollments/", {"page": 1, "course": cid,
                                                 "term": self.org.term, "search": ""},
                        keys=("full_name", "matric_no"))
                # Timetable
                self.ok(c, "/api/slots/", {"term": self.org.term, "active": "true",
                                           "page_size": 1000},
                        keys=("course_code", "venue_code", "weekday", "start_time"))
                self.ok(c, "/api/courses/", {"page_size": 200})
                self.ok(c, "/api/venues/", {"page_size": 1000})
                # Reports
                self.ok(c, "/api/reports/overview/", keys=("courses", "term"))
                # Settings: staff list is readable by all (names only)
                self.ok(c, "/api/members/", {"page_size": 200},
                        keys=("full_name", "role", "username"))

    def test_reports_follow_role(self):
        for role in ("owner", "admin", "viewer", "lecturer"):
            data = self.ok(self.as_(role), f"/api/reports/course/{self.course.pk}/",
                           keys=("students", "lectures", "held"))
            self.assertEqual(data["students"][0]["full_name"], "Ada Obi")

    def test_overview_page(self):
        for role in ("owner", "admin", "lecturer"):
            self.ok(self.as_(role), "/api/sessions/", {"running": "true", "page_size": 20},
                    keys=("course", "course_code", "venue_code", "present_count"))
        for role in ("owner", "admin"):
            c = self.as_(role)
            self.ok(c, "/api/devices/", {"active": "true"}, keys=("online", "hardware_id"))
            self.ok(c, "/api/cards/summary/", keys=("never_used", "active", "revoked"))

    # ---- admin-only pages ----
    def test_admin_pages(self):
        for role in ("owner", "admin"):
            with self.subTest(role=role):
                c = self.as_(role)
                self.ok(c, "/api/cards/", {"page": 1, "status": "active", "search": ""},
                        keys=("uid", "student_name", "last_used", "uses_30d", "uses_total"))
                self.ok(c, "/api/cards/", {"status": "active", "usage": "never"})
                self.ok(c, "/api/taps/", {"page": 1, "search": "", "outcome": "present",
                                          "device": self.device.pk,
                                          "date_from": "2020-01-01", "date_to": "2099-01-01"},
                        keys=("student_name", "course_code", "device_name", "outcome",
                              "device_outcome", "time_conf", "tapped_at"))
                self.ok(c, "/api/audit/", {"page": 1, "search": ""})
                self.ok(c, "/api/cards/capture/", {
                    "device": self.device.pk,
                    "since": (timezone.now() - timedelta(minutes=5)).isoformat()},
                    keys=("uid", "state"))
                r = c.post(f"/api/devices/{self.device.pk}/reveal_token/")
                self.assertEqual(r.status_code, 200)
                r = c.get(f"/api/reports/course/{self.course.pk}/", {"export": "csv"})
                self.assertEqual(r.status_code, 200)

    def test_hidden_pages_are_refused_not_crashing(self):
        for role in ("lecturer", "viewer"):
            c = self.as_(role)
            for url in ("/api/cards/", "/api/cards/summary/", "/api/devices/", "/api/audit/"):
                self.assertEqual(c.get(url).status_code, 403, (role, url))

    def test_login_then_me_with_the_token(self):
        """The real handshake: sign in, then use the token the way the
        frontend does, including the org header it stores."""
        anon = APIClient()
        r = anon.post("/api/auth/login/", {"username": "Lecturer", "password": PW})
        self.assertEqual(r.status_code, 200, r.content)
        tokens = r.json()
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}", HTTP_X_ORG="uni")
        self.assertEqual(c.get("/api/me/").json()["user"]["username"], "lecturer")
        r = anon.post("/api/auth/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.json())


class CorsHandshakeTests(TestCase):
    """The browser asks before sending the auth and org headers across
    origins. If this preflight fails, every page fails with a CORS error
    and nothing reaches the views at all."""

    def test_preflight_allows_the_headers_the_frontend_sends(self):
        from django.test import override_settings
        origin = "https://slams-chi.vercel.app"
        with override_settings(CORS_ALLOW_ALL_ORIGINS=False,
                               CORS_ALLOWED_ORIGINS=[origin]):
            r = self.client.options(
                "/api/students/", HTTP_ORIGIN=origin,
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="PATCH",
                HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type,x-org")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["access-control-allow-origin"], origin)
            allowed = r["access-control-allow-headers"].lower()
            for h in ("authorization", "content-type", "x-org"):
                self.assertIn(h, allowed)
            self.assertIn("PATCH", r["access-control-allow-methods"])

            r = self.client.options("/api/students/", HTTP_ORIGIN="https://evil.example",
                                    HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET")
            self.assertNotIn("access-control-allow-origin", r)


class CapacitorOriginTests(TestCase):
    def test_android_app_origin_is_allowed(self):
        from django.test import override_settings
        from django.conf import settings
        with override_settings(CORS_ALLOW_ALL_ORIGINS=False,
                               CORS_ALLOWED_ORIGINS=settings.CORS_ALLOWED_ORIGINS):
            r = self.client.options(
                "/api/me/", HTTP_ORIGIN="https://localhost",
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
                HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,x-org")
            self.assertEqual(r["access-control-allow-origin"], "https://localhost")
