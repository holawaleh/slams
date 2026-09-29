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
                                      first_name="A", last_name="B")

    def test_duplicate_matric_is_a_form_error_not_a_crash(self):
        self.student("M1")
        r = self.admin.post("/api/students/", {
            "matric_no": " m1 ", "first_name": "C", "last_name": "D"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("matric_no", r.json())

    def test_same_matric_allowed_in_another_org(self):
        other = Organization.objects.create(name="Other", slug="other")
        Student.objects.create(org=other, matric_no="M1",
                               first_name="X", last_name="Y")
        r = self.admin.post("/api/students/", {
            "matric_no": "M1", "first_name": "C", "last_name": "D"})
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
