from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import ClassSession, Course, Enrollment, Student, Venue
from .tenancy import Membership, Organization


class StudentCourseApiTests(TestCase):
    """What the Students and Courses pages rely on."""

    def setUp(self):
        self.org = Organization.objects.create(name="Uni", slug="uni")
        self.admin = self.member("admin", Membership.ADMIN)
        self.lecturer = self.member("lect", Membership.LECTURER)

    def member(self, name, role):
        u = User.objects.create_user(name, password="x")
        Membership.objects.create(user=u, org=self.org, role=role)
        c = APIClient()
        c.force_authenticate(u)
        return c

    def student(self, matric="M1"):
        return Student.objects.create(org=self.org, matric_no=matric,
                                      full_name="A B")

    def test_duplicate_matric_is_a_form_error_not_a_crash(self):
        self.student("M1")
        r = self.admin.post("/api/students/", {
            "matric_no": " m1 ", "full_name": "C D"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("matric_no", r.json())

    def test_same_matric_allowed_in_another_org(self):
        other = Organization.objects.create(name="Other", slug="other")
        Student.objects.create(org=other, matric_no="M1",
                               full_name="X Y")
        r = self.admin.post("/api/students/", {
            "matric_no": "M1", "full_name": "C D"})
        self.assertEqual(r.status_code, 201, r.content)

    def test_duplicate_course_code_is_a_form_error(self):
        Course.objects.create(org=self.org, code="CSC101", title="x")
        r = self.admin.post("/api/courses/", {"code": "csc101", "title": "y"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("code", r.json())

    def test_editing_a_course_keeps_its_own_code(self):
        c = Course.objects.create(org=self.org, code="CSC101", title="x")
        r = self.admin.patch(f"/api/courses/{c.id}/",
                             {"code": "CSC101", "title": "renamed"})
        self.assertEqual(r.status_code, 200, r.content)

    def test_bulk_enrol_defaults_to_org_term(self):
        c = Course.objects.create(org=self.org, code="CSC101", title="x")
        s = self.student()
        r = self.admin.post("/api/enrollments/bulk/",
                            {"course": c.id, "student_ids": [s.id]},
                            format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Enrollment.objects.get().term, self.org.term)

    def test_lecturer_can_read_but_not_change_enrolments(self):
        c = Course.objects.create(org=self.org, code="CSC101", title="x")
        s = self.student()
        e = Enrollment.objects.create(org=self.org, student=s, course=c,
                                      term=self.org.term)
        r = self.lecturer.get("/api/enrollments/", {"course": c.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"][0]["matric_no"], "M1")
        r = self.lecturer.delete(f"/api/enrollments/{e.id}/")
        self.assertEqual(r.status_code, 403)

    def test_course_with_lectures_cannot_be_deleted(self):
        c = Course.objects.create(org=self.org, code="CSC101", title="x")
        v = Venue.objects.create(org=self.org, code="LT1", name="LT1")
        now = timezone.now()
        ClassSession.objects.create(org=self.org, course=c, venue=v,
                                    starts_at=now, ends_at=now + timedelta(hours=1))
        r = self.admin.delete(f"/api/courses/{c.id}/")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(Course.objects.filter(pk=c.id).exists())


class RegisterTests(TestCase):
    BODY = {"org_name": "Test School", "first_name": "A", "last_name": "B",
            "username": "newowner", "email": "", "password": "Xk9!mQ2#vLp7"}

    def test_register_works(self):
        r = APIClient().post("/api/auth/register/", self.BODY, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def test_register_ignores_a_stale_token(self):
        # A browser that was logged in before still sends its old token.
        # Sign-up must not reject it as 401 - the frontend treats a 401 as
        # "session expired" and bounces to the login page.
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer stale.expired.token")
        r = c.post("/api/auth/register/", self.BODY, format="json")
        self.assertEqual(r.status_code, 201, r.content)


class TimetableTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Uni", slug="uni")
        u = User.objects.create_user("admin", password="x")
        Membership.objects.create(user=u, org=self.org, role=Membership.ADMIN)
        self.api = APIClient()
        self.api.force_authenticate(u)
        self.venue = Venue.objects.create(org=self.org, code="LT1", name="LT1")
        self.c1 = Course.objects.create(org=self.org, code="CSC101", title="A")
        self.c2 = Course.objects.create(org=self.org, code="MTH101", title="B")

    def slot(self, course, day=0, start="09:00", end="11:00", **kw):
        body = {"course": course.pk, "venue": self.venue.pk, "weekday": day,
                "start_time": start, "end_time": end, **kw}
        return self.api.post("/api/slots/", body, format="json")

    def test_slot_defaults_to_org_term(self):
        r = self.slot(self.c1)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["term"], self.org.term)

    def test_saturday_allowed_sunday_refused(self):
        self.assertEqual(self.slot(self.c1, day=5).status_code, 201)
        self.assertEqual(self.slot(self.c1, day=6).status_code, 400)

    def test_teaching_hours_are_7_to_18(self):
        self.assertEqual(self.slot(self.c1, start="07:00", end="08:30").status_code, 201)
        self.assertEqual(self.slot(self.c1, day=1, start="16:15", end="18:00").status_code, 201)
        self.assertEqual(self.slot(self.c1, day=2, start="06:30", end="08:00").status_code, 400)
        self.assertEqual(self.slot(self.c1, day=2, start="17:00", end="18:30").status_code, 400)

    def test_room_clash_refused_touching_allowed(self):
        self.assertEqual(self.slot(self.c1).status_code, 201)
        r = self.slot(self.c2, start="10:00", end="12:00")
        self.assertEqual(r.status_code, 400)
        self.assertIn("CSC101", str(r.json()))
        self.assertEqual(self.slot(self.c2, start="11:00", end="12:00").status_code, 201)

    def test_moving_a_slot_does_not_clash_with_itself(self):
        sid = self.slot(self.c1).json()["id"]
        r = self.api.patch(f"/api/slots/{sid}/", {"start_time": "10:00",
                                                  "end_time": "12:00"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_editing_a_slot_regenerates_its_future_session(self):
        from .models import TimetableSlot
        sid = self.slot(self.c1).json()["id"]
        slot = TimetableSlot.objects.get(pk=sid)
        now = timezone.now()
        future = ClassSession.objects.create(
            org=self.org, slot=slot, course=self.c1, venue=self.venue,
            starts_at=now + timedelta(hours=2), ends_at=now + timedelta(hours=3))
        running = ClassSession.objects.create(
            org=self.org, slot=slot, course=self.c1, venue=self.venue,
            starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(hours=1))
        self.api.patch(f"/api/slots/{sid}/", {"end_time": "10:30"}, format="json")
        self.assertFalse(ClassSession.objects.filter(pk=future.pk).exists())
        self.assertTrue(ClassSession.objects.filter(pk=running.pk).exists())
