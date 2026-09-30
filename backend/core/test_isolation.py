"""Two schools on the same server must not be able to see, change or
even detect each other's data. Every test here is from owner A's side,
aimed at something belonging to owner B."""

from datetime import time, timedelta
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (AttendanceRecord, Card, ClassSession, Course, Device,
                     Enrollment, Student, TapEvent, TimetableSlot, Venue)
from .tenancy import Membership, Organization


def school(slug):
    org = Organization.objects.create(name=slug.upper(), slug=slug)
    owner = User.objects.create_user(f"owner-{slug}", password="x",
                                     first_name="Owner", last_name=slug.upper())
    Membership.objects.create(user=owner, org=org, role=Membership.OWNER)
    api = APIClient()
    api.force_authenticate(owner)
    venue = Venue.objects.create(org=org, code="LT1", name="Hall")
    course = Course.objects.create(org=org, code="CSC101", title="Intro",
                                   lecturer=owner)
    student = Student.objects.create(org=org, matric_no="M001",
                                     full_name=f"S {slug.upper()}")
    Enrollment.objects.create(org=org, student=student, course=course,
                              term=org.term)
    card = Card.objects.create(org=org, uid="0A0B0C0D", student=student)
    device = Device.objects.create(org=org, name=f"R-{slug}", venue=venue)
    slot = TimetableSlot.objects.create(
        org=org, course=course, venue=venue, weekday=0,
        start_time=time(9), end_time=time(11), term=org.term)
    now = timezone.now()
    session = ClassSession.objects.create(
        org=org, course=course, venue=venue, starts_at=now,
        ends_at=now + timedelta(hours=1))
    AttendanceRecord.objects.create(org=org, session=session, student=student,
                                    status="present", tapped_at=now)
    TapEvent.objects.create(org=org, device=device, uid=f"DEAD{slug[:4].upper()}",
                            outcome="unknown", tapped_at=now, client_id=1)
    return SimpleNamespace(
        org=org, owner=owner, api=api, venue=venue, course=course,
        student=student, card=card, device=device, slot=slot, session=session)


class IsolationTests(TestCase):
    def setUp(self):
        self.a = school("alpha")
        self.b = school("beta")

    def rows(self, url, **params):
        r = self.a.api.get(url, params)
        self.assertEqual(r.status_code, 200, url)
        data = r.json()
        return data.get("results", data) if isinstance(data, dict) else data

    def test_lists_only_show_own_rows(self):
        own = {
            "students": self.a.student.pk, "cards": self.a.card.pk,
            "venues": self.a.venue.pk, "courses": self.a.course.pk,
            "devices": self.a.device.pk, "slots": self.a.slot.pk,
            "sessions": self.a.session.pk,
        }
        for name, pk in own.items():
            ids = [r["id"] for r in self.rows(f"/api/{name}/")]
            self.assertEqual(ids, [pk], name)
        for name in ("enrollments", "taps", "attendance", "members"):
            self.assertEqual(len(self.rows(f"/api/{name}/")), 1, name)

    def test_cannot_read_change_or_delete_the_other_schools_rows(self):
        targets = {"students": self.b.student, "courses": self.b.course,
                   "venues": self.b.venue, "slots": self.b.slot,
                   "devices": self.b.device, "cards": self.b.card,
                   "sessions": self.b.session}
        for name, obj in targets.items():
            url = f"/api/{name}/{obj.pk}/"
            self.assertEqual(self.a.api.get(url).status_code, 404, name)
            self.assertEqual(self.a.api.patch(url, {}).status_code, 404, name)
            self.assertEqual(self.a.api.delete(url).status_code, 404, name)
        self.assertTrue(Student.objects.filter(pk=self.b.student.pk).exists())
        self.assertTrue(Card.objects.get(pk=self.b.card.pk).active)

    def test_device_token_is_not_revealed_across_schools(self):
        r = self.a.api.post(f"/api/devices/{self.b.device.pk}/reveal_token/")
        self.assertEqual(r.status_code, 404)

    def test_unknown_cards_worklist_is_per_school(self):
        rows = self.rows("/api/taps/unregistered/")
        self.assertEqual([r["uid"] for r in rows], ["DEADALPH"])
        self.assertEqual(rows[0]["last_device"], "R-alpha")

    def test_cannot_link_own_rows_to_the_other_schools_rows(self):
        cases = [
            ("/api/enrollments/", {"student": self.b.student.pk,
                                   "course": self.a.course.pk, "term": "t"}),
            ("/api/enrollments/", {"student": self.a.student.pk,
                                   "course": self.b.course.pk, "term": "t"}),
            ("/api/slots/", {"course": self.a.course.pk,
                             "venue": self.b.venue.pk, "weekday": 1,
                             "start_time": "09:00", "end_time": "10:00",
                             "term": "t"}),
            ("/api/devices/", {"name": "X", "venue": self.b.venue.pk}),
        ]
        for url, body in cases:
            r = self.a.api.post(url, body, format="json")
            self.assertEqual(r.status_code, 400, (url, r.content))

    def test_other_schools_ids_look_exactly_like_missing_ids(self):
        """A foreign id must get the same answer as an id that does not
        exist at all, or the error itself confirms the row is there."""
        def err(student_id):
            r = self.a.api.post("/api/enrollments/", {
                "student": student_id, "course": self.a.course.pk,
                "term": "t"}, format="json")
            return str(r.json()).replace(str(student_id), "N")
        self.assertEqual(err(self.b.student.pk), err(999999))

    def test_lecturer_must_belong_to_the_school(self):
        r = self.a.api.post("/api/courses/", {
            "code": "MTH101", "title": "Maths", "lecturer": self.b.owner.pk},
            format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_card_holder_must_belong_to_the_school(self):
        r = self.a.api.post("/api/cards/", {
            "uid": "11223344", "holder": self.b.owner.pk, "is_admin": True},
            format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_bulk_enrol_ignores_other_schools_students(self):
        r = self.a.api.post("/api/enrollments/bulk/", {
            "course": self.a.course.pk,
            "student_ids": [self.b.student.pk]}, format="json")
        self.assertEqual(r.json()["created"], 0)
        r = self.a.api.post("/api/enrollments/bulk/", {
            "course": self.b.course.pk,
            "student_ids": [self.a.student.pk]}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_bind_cannot_target_other_schools_student(self):
        r = self.a.api.post("/api/cards/bind/", {
            "uid": "55667788", "student_id": self.b.student.pk}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_same_card_uid_in_both_schools_stays_separate(self):
        rows = self.rows("/api/cards/", search="0A0B0C0D")
        self.assertEqual([c["student"] for c in rows], [self.a.student.pk])

    def test_org_header_cannot_switch_into_another_school(self):
        self.a.api.credentials(HTTP_X_ORG="beta")
        r = self.a.api.get("/api/students/")
        self.assertNotEqual(r.status_code, 200)

    def test_organization_endpoint_shows_only_own(self):
        r = self.a.api.get("/api/organization/")
        self.assertEqual(r.json()["slug"], "alpha")

    def test_device_resolves_cards_within_its_own_school(self):
        dev = APIClient()
        dev.credentials(HTTP_AUTHORIZATION=f"Device {self.a.device.token}")
        r = dev.post("/api/device/attendance/", {"records": [
            {"client_id": 5, "uid": "0A0B0C0D", "age_ms": 0}]}, format="json")
        self.assertEqual(r.status_code, 200)
        tap = TapEvent.objects.get(client_id=5)
        self.assertEqual((tap.org_id, tap.student_id),
                         (self.a.org.id, self.a.student.id))
