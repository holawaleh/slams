"""Attendance reports. Everything here reads; nothing writes.

A lecture counts as held once its start time has passed and it was not
cancelled. Whether a lecturer remembered to press "close" does not
matter - most never will - so reports do not depend on it."""

import csv
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AttendanceRecord, ClassSession, Course, Student
from .permissions import IsOrgMember, get_membership
from .tenancy import Membership

# Below this share of lectures attended, a student is flagged.
AT_RISK_PERCENT = 75


def held_sessions(org, now=None):
    now = now or timezone.now()
    return ClassSession.objects.filter(org=org, starts_at__lte=now).exclude(
        status="cancelled")


def local_day_range(org, first, last):
    """[start of first day, start of the day after last) in the org's
    timezone, as aware datetimes."""
    from deviceapi.services import org_tz
    tz = org_tz(org)
    return (datetime.combine(first, time.min, tzinfo=tz),
            datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz))


def parse_range(request):
    """?from=YYYY-MM-DD&to=YYYY-MM-DD, either optional."""
    def day(name):
        raw = request.query_params.get(name)
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return "bad"
    first, last = day("from"), day("to")
    if "bad" in (first, last):
        return None, None, "Dates must be YYYY-MM-DD."
    if first and last and last < first:
        return None, None, "The end date is before the start date."
    return first, last, None


def within(qs, org, first, last, field="starts_at"):
    if first:
        qs = qs.filter(**{f"{field}__gte": local_day_range(org, first, first)[0]})
    if last:
        qs = qs.filter(**{f"{field}__lt": local_day_range(org, last, last)[1]})
    return qs


def pct(part, whole):
    return round(100 * part / whole, 1) if whole else None


class ReportView(APIView):
    permission_classes = [IsOrgMember]

    def courses(self, request):
        """Admins and viewers (registry, heads of department) see every
        course; a lecturer only the courses they teach."""
        m = get_membership(request)
        qs = Course.objects.filter(org=m.org)
        if m.role == Membership.LECTURER:
            return qs.filter(lecturer=request.user)
        return qs


class RecheckTaps(APIView):
    """POST /api/reports/recheck/ {from, to} - judge again the taps in a
    date range that did not count, after the timetable, enrolments or a
    reader's venue have been corrected. Admins only; always audited."""
    permission_classes = [IsOrgMember]

    def post(self, request):
        from deviceapi.services import recheck_taps, RECHECKABLE
        from .models import TapEvent
        from .views import audit
        m = get_membership(request)
        if not m.can_administer:
            return Response({"detail": "Administrator privileges are required."},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            first = date.fromisoformat(request.data["from"]) if request.data.get("from") else None
            last = date.fromisoformat(request.data["to"]) if request.data.get("to") else None
        except (TypeError, ValueError):
            return Response({"detail": "Dates must be YYYY-MM-DD."},
                            status=status.HTTP_400_BAD_REQUEST)
        if first is None:          # default: the last two weeks
            first = timezone.localdate() - timedelta(days=14)
        taps = within(TapEvent.objects.filter(org=m.org, outcome__in=RECHECKABLE),
                      m.org, first, last, field="tapped_at")
        checked, counted = recheck_taps(taps)
        audit(request, "taps_recheck",
              f"{first} to {last or 'today'}: {checked} checked, {counted} now counted")
        return Response({"checked": checked, "counted": counted,
                         "from": first, "to": last})


class OverviewReport(ReportView):
    """One row per course: how many lectures were held, and how well
    they were attended."""

    def get(self, request):
        org = get_membership(request).org
        first, last, err = parse_range(request)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

        courses = list(self.courses(request).select_related("lecturer")
                       .order_by("code"))
        ids = [c.id for c in courses]
        sessions = within(held_sessions(org).filter(course_id__in=ids),
                          org, first, last)
        held = dict(sessions.values("course_id").annotate(n=Count("id"))
                    .values_list("course_id", "n"))
        enrolled = defaultdict(set)
        for sid, cid in Student.objects.filter(
                org=org, enrollments__course_id__in=ids,
                enrollments__term=org.term).values_list(
                "id", "enrollments__course_id"):
            enrolled[cid].add(sid)

        attended = defaultdict(lambda: defaultdict(int))
        for cid, sid, n in (AttendanceRecord.objects
                            .filter(session__in=sessions)
                            .values("session__course_id", "student_id")
                            .annotate(n=Count("id"))
                            .values_list("session__course_id", "student_id", "n")):
            attended[cid][sid] = n

        rows = []
        for c in courses:
            h = held.get(c.id, 0)
            students = enrolled[c.id]
            total = sum(attended[c.id][s] for s in students)
            rows.append({
                "course_id": c.id, "code": c.code, "title": c.title,
                "lecturer": c.lecturer.get_full_name() if c.lecturer else "",
                "enrolled": len(students), "held": h,
                "attendance_rate": pct(total, h * len(students)),
                "at_risk": sum(1 for s in students
                               if h and pct(attended[c.id][s], h) < AT_RISK_PERCENT),
            })
        return Response({"from": first, "to": last, "term": org.term,
                         "at_risk_percent": AT_RISK_PERCENT, "courses": rows})


class CourseReport(ReportView):
    """The register for one course: every lecture held, and every
    student's record across them. ?export=csv downloads it."""

    def get(self, request, pk):
        org = get_membership(request).org
        course = self.courses(request).filter(pk=pk).select_related(
            "lecturer").first()
        if course is None:
            return Response({"detail": "Not found."},
                            status=status.HTTP_404_NOT_FOUND)
        first, last, err = parse_range(request)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

        sessions = list(within(held_sessions(org).filter(course=course),
                               org, first, last)
                        .select_related("venue").order_by("starts_at"))
        marks = defaultdict(dict)
        for sid, sess, st in AttendanceRecord.objects.filter(
                session__in=sessions).values_list(
                "student_id", "session_id", "status"):
            marks[sid][sess] = st

        # Everyone enrolled now, plus anyone who attended and has since
        # been removed from the course, so no attendance goes missing.
        students = list(Student.objects.filter(org=org).filter(
            Q(enrollments__course=course, enrollments__term=org.term)
            | Q(id__in=list(marks))).distinct().order_by("full_name"))

        held = len(sessions)
        rows = []
        for s in students:
            m = marks.get(s.id, {})
            present = sum(1 for v in m.values() if v == "present")
            late = sum(1 for v in m.values() if v == "late")
            rows.append({
                "student_id": s.id, "full_name": s.full_name,
                "matric_no": s.matric_no, "level": s.level,
                "present": present, "late": late,
                "absent": held - present - late,
                "percentage": pct(present + late, held),
                "at_risk": bool(held) and pct(present + late, held) < AT_RISK_PERCENT,
                "marks": {str(k): v for k, v in m.items()},
            })

        from deviceapi.services import org_tz
        tz = org_tz(org)
        lectures = []
        for x in sessions:
            p = sum(1 for r in rows if r["marks"].get(str(x.id)) == "present")
            l = sum(1 for r in rows if r["marks"].get(str(x.id)) == "late")
            lectures.append({
                "id": x.id, "venue": x.venue.code,
                "starts_at": x.starts_at, "ends_at": x.ends_at,
                "label": x.starts_at.astimezone(tz).strftime("%a %d %b %H:%M"),
                "present": p, "late": l, "absent": len(rows) - p - l,
            })

        if request.query_params.get("export") == "csv":
            return self.csv(org, course, first, last, lectures, rows)
        return Response({
            "course": {"id": course.id, "code": course.code,
                       "title": course.title,
                       "lecturer": course.lecturer.get_full_name()
                       if course.lecturer else ""},
            "from": first, "to": last, "held": held,
            "at_risk_percent": AT_RISK_PERCENT,
            "lectures": lectures, "students": rows,
        })

    def csv(self, org, course, first, last, lectures, rows):
        span = f"{first or 'start'}_to_{last or 'today'}"
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = (
            f'attachment; filename="{course.code}_attendance_{span}.csv"')
        resp.write("﻿")        # so Excel reads the names as UTF-8
        w = csv.writer(resp)
        w.writerow([f"{course.code} - {course.title}", f"Term {org.term}",
                    f"{len(lectures)} lectures", f"{first or ''} to {last or ''}"])
        w.writerow([])
        w.writerow(["Name", "Matric no", "Level"]
                   + [l["label"] for l in lectures]
                   + ["Present", "Late", "Absent", "Attendance %"])
        code = {"present": "P", "late": "L"}
        for r in rows:
            w.writerow([r["full_name"], r["matric_no"], r["level"]]
                       + [code.get(r["marks"].get(str(l["id"])), "A")
                          for l in lectures]
                       + [r["present"], r["late"], r["absent"],
                          "" if r["percentage"] is None else r["percentage"]])
        return resp
