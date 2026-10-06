from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (AttendanceRecord, AuditLog, Card, ClassSession, Course,
                     Device, Student, TapEvent, Venue)
from .tenancy import Membership, Organization

GOOD = "Xk9!mQ2#vLp7"


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class PlatformTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser("root", password=GOOD)
        self.api = client_for(self.root)
        self.a = Organization.objects.create(name="Alpha Uni", slug="alpha")
        self.b = Organization.objects.create(name="Beta Poly", slug="beta")
        self.owner_a = self.member("ann", self.a, Membership.OWNER)
        self.owner_b = self.member("bob", self.b, Membership.OWNER)
        self.lect_a = self.member("lee", self.a, Membership.LECTURER)

    def member(self, name, org, role):
        u = User.objects.create_user(name, password=GOOD, first_name=name.title())
        Membership.objects.create(user=u, org=org, role=role)
        return u

    def fill(self, org):
        """A school with a lecture, a tap and an attendance record."""
        st = Student.objects.create(org=org, full_name="Ada", matric_no=f"M-{org.slug}")
        Card.objects.create(org=org, uid=f"AA{org.pk}", student=st)
        v = Venue.objects.create(org=org, code="LT1", name="LT1")
        c = Course.objects.create(org=org, code="CSC201", title="Data")
        now = timezone.now()
        s = ClassSession.objects.create(org=org, course=c, venue=v,
                                        starts_at=now - timedelta(minutes=10),
                                        ends_at=now + timedelta(minutes=50))
        d = Device.objects.create(org=org, name="R1", hardware_id=f"00:00:00:00:00:0{org.pk}",
                                  venue=v, last_seen=now)
        TapEvent.objects.create(org=org, device=d, uid=f"AA{org.pk}", student=st,
                                session=s, outcome="present", tapped_at=now, client_id=1)
        AttendanceRecord.objects.create(org=org, session=s, student=st,
                                        status="present", tapped_at=now, device=d)
        return d

    # ---- who gets in ----
    def test_only_superusers(self):
        for path in ("/api/platform/summary/", "/api/platform/orgs/",
                     "/api/platform/users/", "/api/platform/devices/",
                     "/api/platform/activity/"):
            self.assertEqual(client_for(self.owner_a).get(path).status_code, 403, path)
            self.assertEqual(APIClient().get(path).status_code, 401, path)
            self.assertEqual(self.api.get(path).status_code, 200, path)

    # ---- seeing everything ----
    def test_summary_and_school_usage(self):
        self.fill(self.a)
        r = self.api.get("/api/platform/summary/").json()
        self.assertEqual(r["schools"]["total"], 2)
        self.assertEqual(r["taps"]["today"], 1)
        self.assertEqual(r["readers"]["online"], 1)
        self.assertEqual(len(r["daily"]), 30)
        self.assertEqual(r["top_schools"][0]["name"], "Alpha Uni")

        rows = {o["slug"]: o for o in self.api.get("/api/platform/orgs/").json()["results"]}
        self.assertEqual(rows["alpha"]["taps_30d"], 1)
        self.assertEqual(rows["alpha"]["member_count"], 2)
        self.assertEqual(rows["alpha"]["student_count"], 1)
        self.assertEqual(rows["beta"]["taps_30d"], 0)

        detail = self.api.get(f"/api/platform/orgs/{self.a.pk}/").json()
        self.assertEqual({m["username"] for m in detail["members"]}, {"ann", "lee"})
        self.assertTrue(detail["readers"][0]["online"])

    def test_activity_spans_schools(self):
        AuditLog.objects.create(org=self.a, action="sign_in", subject="ann")
        AuditLog.objects.create(org=self.b, action="sign_in", subject="bob")
        rows = self.api.get("/api/platform/activity/").json()["results"]
        self.assertEqual({r["org_name"] for r in rows}, {"Alpha Uni", "Beta Poly"})
        rows = self.api.get("/api/platform/activity/", {"org": self.b.pk}).json()["results"]
        self.assertEqual([r["org_name"] for r in rows], ["Beta Poly"])

    # ---- schools ----
    def test_disable_school_locks_its_staff_out(self):
        r = self.api.patch(f"/api/platform/orgs/{self.a.pk}/", {"active": False}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client_for(self.owner_a).get("/api/students/").status_code, 403)
        self.assertEqual(client_for(self.owner_b).get("/api/students/").status_code, 200)
        log = AuditLog.objects.get(org=self.a, action="org_disable")
        self.assertIn("platform admin", log.actor_label)

    def test_delete_school_needs_confirmation_and_frees_readers(self):
        d = self.fill(self.a)
        hw = d.hardware_id
        r = self.api.delete(f"/api/platform/orgs/{self.a.pk}/")
        self.assertEqual(r.status_code, 400)
        r = self.api.delete(f"/api/platform/orgs/{self.a.pk}/?confirm=alpha")
        self.assertEqual(r.status_code, 204, r.content)
        self.assertFalse(Organization.objects.filter(pk=self.a.pk).exists())
        self.assertFalse(Student.objects.filter(org_id=self.a.pk).exists())
        self.assertFalse(Device.objects.filter(hardware_id=hw).exists())
        self.assertTrue(Organization.objects.filter(pk=self.b.pk).exists())

    # ---- users ----
    def test_disable_user_blocks_sign_in(self):
        r = self.api.patch(f"/api/platform/users/{self.lect_a.pk}/",
                           {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 200)
        login = APIClient().post("/api/auth/login/", {"username": "lee", "password": GOOD})
        self.assertEqual(login.status_code, 401)
        self.assertTrue(AuditLog.objects.filter(org=self.a, action="user_disable").exists())

    def test_edit_user_and_set_password(self):
        r = self.api.patch(f"/api/platform/users/{self.lect_a.pk}/",
                           {"first_name": "Lee", "last_name": "Ade", "email": "LEE@X.COM"},
                           format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["email"], "lee@x.com")
        r = self.api.patch(f"/api/platform/users/{self.lect_a.pk}/",
                           {"username": "BOB"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post(f"/api/platform/users/{self.lect_a.pk}/set_password/",
                          {"password": "short"})
        self.assertEqual(r.status_code, 400)
        r = self.api.post(f"/api/platform/users/{self.lect_a.pk}/set_password/",
                          {"password": "Nw9!aaaaaaaa"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.get(pk=self.lect_a.pk).check_password("Nw9!aaaaaaaa"))

    def test_cannot_lock_out_yourself_or_last_superuser(self):
        r = self.api.patch(f"/api/platform/users/{self.root.pk}/",
                           {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.api.delete(f"/api/platform/users/{self.root.pk}/").status_code, 400)
        r = self.api.patch(f"/api/platform/users/{self.root.pk}/",
                           {"is_superuser": False}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_delete_user_but_not_a_sole_owner(self):
        r = self.api.delete(f"/api/platform/users/{self.owner_a.pk}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("only owner", str(r.json()))
        r = self.api.delete(f"/api/platform/users/{self.lect_a.pk}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(User.objects.filter(username="lee").exists())
        self.assertTrue(AuditLog.objects.filter(org=self.a, action="user_delete").exists())

    def test_memberships(self):
        r = self.api.post(f"/api/platform/users/{self.lect_a.pk}/add_membership/",
                          {"org": self.b.pk, "role": "viewer"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        m = Membership.objects.get(user=self.lect_a, org=self.b)
        r = self.api.patch(f"/api/platform/memberships/{m.pk}/", {"role": "admin"}, format="json")
        self.assertEqual(r.status_code, 200)
        own = Membership.objects.get(user=self.owner_b, org=self.b)
        r = self.api.patch(f"/api/platform/memberships/{own.pk}/", {"role": "admin"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.api.delete(f"/api/platform/memberships/{own.pk}/").status_code, 400)
        self.assertEqual(self.api.delete(f"/api/platform/memberships/{m.pk}/").status_code, 204)

    # ---- readers ----
    def test_remove_reader_from_any_school(self):
        d = self.fill(self.b)
        rows = self.api.get("/api/platform/devices/").json()["results"]
        self.assertEqual(rows[0]["org_name"], "Beta Poly")
        self.assertEqual(rows[0]["taps_30d"], 1)
        self.assertEqual(self.api.delete(f"/api/platform/devices/{d.pk}/").status_code, 204)
        d.refresh_from_db()
        self.assertFalse(d.active)
        self.assertIsNone(d.hardware_id)
