"""Seeds one complete organization so the device API can be exercised
end to end. Safe to re-run: --reset wipes the demo org first.

    python manage.py seed_demo
    python manage.py seed_demo --reset
    python manage.py seed_demo --uid E4794F2A
"""

from datetime import timedelta
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.tenancy import Organization, Membership
from core.models import (Student, Card, Venue, Course, Enrollment, Device,
                         TimetableSlot, ClassSession)

SLUG = "demo-university"
TERM = "2025/2026-1"

# Names are obviously fictional so seeded rows are never mistaken for real
# records if this is ever run against a shared database.
STUDENTS = [
    ("DEMO/001", "Test", "Alpha"),
    ("DEMO/002", "Test", "Bravo"),
    ("DEMO/003", "Test", "Charlie"),
    ("DEMO/004", "Test", "Delta"),
    ("DEMO/005", "Test", "Echo"),
]

# Card UIDs for the seeded students. The first is overridden by --uid so
# your own card maps to a real student.
UIDS = ["AAAA0001", "AAAA0002", "AAAA0003", "AAAA0004", "AAAA0005"]
ADMIN_UID = "DEADBEEF"


class Command(BaseCommand):
    help = "Create a demo organization with a device, course and timetable."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete the demo organization first")
        parser.add_argument("--uid", type=str, default=None,
                            help="Your real card UID, bound to student 1")
        parser.add_argument("--password", type=str, default="DemoPass123!",
                            help="Password for the demo accounts")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            deleted = Organization.objects.filter(slug=SLUG).delete()
            User.objects.filter(username__in=["demo_admin",
                                              "demo_lecturer"]).delete()
            self.stdout.write(self.style.WARNING(
                f"Removed previous demo data ({deleted[0]} rows)."))

        if Organization.objects.filter(slug=SLUG).exists():
            self.stdout.write(self.style.ERROR(
                "Demo organization already exists. Use --reset to rebuild."))
            return

        pw = opts["password"]
        org = Organization.objects.create(
            name="Demo University", slug=SLUG, country="Nigeria",
            term=TERM, timezone="Africa/Lagos")

        admin = User.objects.create_user(
            username="demo_admin", email="admin@demo.test", password=pw,
            first_name="Demo", last_name="Admin")
        lecturer = User.objects.create_user(
            username="demo_lecturer", email="lecturer@demo.test", password=pw,
            first_name="Demo", last_name="Lecturer")
        Membership.objects.create(user=admin, org=org,
                                  role=Membership.OWNER, is_default=True)
        Membership.objects.create(user=lecturer, org=org,
                                  role=Membership.LECTURER, is_default=True)

        venue = Venue.objects.create(org=org, code="LT1",
                                     name="Lecture Theatre 1", capacity=200)
        course = Course.objects.create(org=org, code="CPE401",
                                       title="Embedded Systems",
                                       lecturer=lecturer)
        device = Device.objects.create(org=org, name="SLAM-LT1", venue=venue)

        students = []
        for matric, first, last in STUDENTS:
            students.append(Student.objects.create(
                org=org, matric_no=matric, first_name=first, last_name=last,
                department="Computer Engineering", level="400"))

        uids = list(UIDS)
        if opts["uid"]:
            uids[0] = opts["uid"].upper().strip()
        for student, uid in zip(students, uids):
            Card.objects.create(org=org, uid=uid, student=student)
        Card.objects.create(org=org, uid=ADMIN_UID, holder=admin,
                            is_admin=True)

        # Only the first four are enrolled, so student five gives you a
        # live "not enrolled" case to test against.
        for student in students[:4]:
            Enrollment.objects.create(org=org, student=student,
                                      course=course, term=TERM)

        # A slot on every weekday, spanning now, so a session always exists
        # whenever you happen to be testing.
        now = timezone.localtime(timezone.now())
        start = (now - timedelta(minutes=5)).time().replace(microsecond=0)
        end = (now + timedelta(hours=2)).time().replace(microsecond=0)
        for weekday in range(7):
            TimetableSlot.objects.create(
                org=org, course=course, venue=venue, weekday=weekday,
                start_time=start, end_time=end, grace_minutes=15, term=TERM)

        self._report(org, device, course, venue, students, uids, pw)

    def _report(self, org, device, course, venue, students, uids, pw):
        w = self.stdout.write
        w("")
        w(self.style.SUCCESS("Demo organization created."))
        w("")
        w(f"  Organization   {org.name}  (slug: {org.slug})")
        w(f"  Term           {org.term}")
        w(f"  Venue          {venue.code}")
        w(f"  Course         {course.code} - {course.title}")
        w(f"  Device         {device.name}")
        w("")
        w(self.style.HTTP_INFO("  Device token (paste into Postman):"))
        w(f"  {device.token}")
        w("")
        w("  Dashboard logins:")
        w(f"    demo_admin     / {pw}    (owner)")
        w(f"    demo_lecturer  / {pw}    (lecturer)")
        w("")
        w("  Cards:")
        for s, uid in zip(students, uids):
            mark = "enrolled" if s.enrollments.exists() else "NOT enrolled"
            w(f"    {uid:<10} {s.short_name:<16} {s.matric_no:<10} {mark}")
        w(f"    {ADMIN_UID:<10} {'(admin card)':<16}")
        w("")
        w("  A lecture is running now, so taps will be accepted.")
        w("  Card 5 is deliberately unenrolled, for the rejection case.")
        w("")
