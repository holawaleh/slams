from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .models import AuditLog, Course, Student, Venue
from .tenancy import Membership, Organization

PW = "Xk9!mQ2#vLp7"


class AuditTests(TestCase):
    """Every entry says who did it (name, username, role) and who or what
    it was done to."""

    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="Uni", slug="uni")
        self.admin = User.objects.create_user("bola", password=PW,
                                              first_name="Bola", last_name="Ade")
        Membership.objects.create(user=self.admin, org=self.org, role="admin")
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def last(self):
        return AuditLog.objects.latest("id")

    def test_student_actions_name_actor_and_student(self):
        sid = self.api.post("/api/students/", {"full_name": "Ada Obi", "matric_no": "M1"},
                            format="json").json()["id"]
        e = self.last()
        self.assertEqual((e.action, e.actor_label, e.subject),
                         ("student_create", "Bola Ade (bola, admin)", "Ada Obi (M1)"))
        self.api.patch(f"/api/students/{sid}/", {"level": "200"}, format="json")
        self.assertEqual((self.last().action, self.last().detail), ("student_update", "changed: level"))
        self.api.delete(f"/api/students/{sid}/")
        self.assertEqual((self.last().action, self.last().subject), ("student_delete", "Ada Obi (M1)"))

    def test_course_venue_and_enrolment(self):
        cid = self.api.post("/api/courses/", {"code": "csc101", "title": "Intro"},
                            format="json").json()["id"]
        self.assertEqual((self.last().action, self.last().subject), ("course_create", "course CSC101"))
        self.api.post("/api/venues/", {"code": "lt1", "name": "Hall"}, format="json")
        self.assertEqual(self.last().subject, "venue LT1")
        s = Student.objects.create(org=self.org, full_name="Ada Obi", matric_no="M1")
        eid = self.api.post("/api/enrollments/", {"student": s.pk, "course": cid,
                                                  "term": self.org.term}, format="json").json()["id"]
        self.assertEqual((self.last().action, self.last().subject), ("enroll_add", "Ada Obi (M1)"))
        self.api.delete(f"/api/enrollments/{eid}/")
        self.assertEqual((self.last().action, self.last().detail),
                         ("enroll_remove", f"course CSC101 ({self.org.term})"))
        self.api.post("/api/enrollments/bulk/", {"course": cid, "student_ids": [s.pk]}, format="json")
        self.assertEqual((self.last().subject, self.last().detail),
                         ("course CSC101", f"1 student(s): Ada Obi ({self.org.term})"))

    def test_staff_actions_name_both_people(self):
        owner = User.objects.create_user("own", password=PW, first_name="Ola", last_name="Owner")
        Membership.objects.create(user=owner, org=self.org, role="owner")
        c = APIClient(); c.force_authenticate(owner)
        c.post("/api/members/", {"full_name": "Ngozi Eze", "username": "ngozi",
                                 "role": "lecturer", "password": PW}, format="json")
        e = self.last()
        self.assertEqual((e.action, e.actor_label, e.subject, e.detail),
                         ("staff_add", "Ola Owner (own, owner)", "Ngozi Eze (ngozi)", "as lecturer"))

    def test_sign_in_and_failed_sign_in(self):
        anon = APIClient()
        anon.post("/api/auth/login/", {"username": "BOLA", "password": "wrong-Pass1"})
        e = self.last()
        self.assertEqual((e.action, e.actor_id, e.subject), ("sign_in_failed", None, "Bola Ade (bola, admin)"))
        anon.post("/api/auth/login/", {"username": "bola", "password": PW})
        e = self.last()
        self.assertEqual((e.action, e.actor_label), ("sign_in", "Bola Ade (bola, admin)"))
        n = AuditLog.objects.count()
        anon.post("/api/auth/login/", {"username": "nobody", "password": PW})
        self.assertEqual(AuditLog.objects.count(), n)

    def test_name_survives_the_account_being_deleted(self):
        self.api.post("/api/courses/", {"code": "x1", "title": "X"}, format="json")
        self.admin.delete()
        e = self.last()
        self.assertIsNone(e.actor_id)
        self.assertEqual(e.actor_label, "Bola Ade (bola, admin)")

    def test_audit_screen_shows_and_searches_people(self):
        self.api.post("/api/students/", {"full_name": "Ada Obi", "matric_no": "M1"}, format="json")
        row = self.api.get("/api/audit/", {"search": "Ada"}).json()["results"][0]
        self.assertEqual((row["actor_name"], row["subject"]), ("Bola Ade (bola, admin)", "Ada Obi (M1)"))


class AuditSentenceTests(AuditTests):
    """The Audit log shows each entry as the action taken, in words."""

    def sentences(self):
        return [r["description"] for r in self.api.get("/api/audit/").json()["results"]]

    def test_actions_read_as_sentences(self):
        sid = self.api.post("/api/students/", {"full_name": "Ada Obi", "matric_no": "M1",
                                               "department": "CSC", "level": "200"},
                            format="json").json()["id"]
        cid = self.api.post("/api/courses/", {"code": "csc101", "title": "Intro"},
                            format="json").json()["id"]
        self.api.post("/api/enrollments/", {"student": sid, "course": cid,
                                            "term": self.org.term}, format="json")
        self.api.delete(f"/api/students/{sid}/")
        got = self.sentences()
        self.assertIn("Added student Ada Obi (M1), CSC, level 200", got)
        self.assertIn("Added course CSC101 - Intro; no lecturer", got)
        self.assertIn(f"Enrolled Ada Obi (M1) on course CSC101 ({self.org.term})", got)
        self.assertIn("Deleted student Ada Obi (M1)", got)

    def test_staff_role_sentence(self):
        owner = User.objects.create_user("own", password=PW, first_name="Ola", last_name="Owner")
        Membership.objects.create(user=owner, org=self.org, role="owner")
        c = APIClient(); c.force_authenticate(owner)
        m = Membership.objects.get(user=self.admin)
        c.patch(f"/api/members/{m.pk}/", {"role": "lecturer"}, format="json")
        row = c.get("/api/audit/").json()["results"][0]
        self.assertEqual((row["actor_name"], row["description"]),
                         ("Ola Owner (own, owner)", "Changed the role of Bola Ade (bola) from admin to lecturer"))
