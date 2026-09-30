from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from datetime import datetime, timedelta, timezone as dt_timezone

from core.models import Card, Device, TapEvent, AttendanceRecord
from .authentication import DeviceTokenAuthentication
from .permissions import IsDevice
from .services import (active_session_for, roster_for, bundle_version,
                       pack_directory, pack_directory_v2, DIR2_PAGE,
                       judge_taps)

FIRMWARE_LATEST = "0.1.0"


def server_ms():
    return int(timezone.now().timestamp() * 1000)


class DeviceView(APIView):
    """Base: token auth, no pagination, no browsable renderer overhead."""
    authentication_classes = [DeviceTokenAuthentication]
    permission_classes = [IsDevice]

    def touch(self, request):
        """Record contact without a full model save on every field."""
        d = request.device
        fields = {"last_seen": timezone.now()}
        fw = request.data.get("firmware") if hasattr(request, "data") else None
        if isinstance(fw, str) and fw[:32] != d.firmware:
            fields["firmware"] = fw[:32]
        qd = request.data.get("queue_depth") if hasattr(request, "data") else None
        if isinstance(qd, int) and 0 <= qd < 100000:
            fields["queue_depth"] = qd
        Device.objects.filter(pk=d.pk).update(**fields)


class HelloView(DeviceView):
    """Heartbeat. One request carries everything the device would
    otherwise poll for separately: time, versions, config, OTA."""

    def post(self, request):
        self.touch(request)
        device = request.device
        now = timezone.now()
        session = active_session_for(device, now)
        _, dir_version, dir_count = pack_directory(device.org)

        payload = {
            "server_utc": int(now.timestamp()),
            "device": device.name,
            "org": device.org.slug,
            "venue": device.venue.code if device.venue else None,
            "enroll_mode": device.enroll_mode,
            "directory_version": dir_version,
            "directory_count": dir_count,
            "bundle_version": bundle_version(session, device.org),
            "firmware_latest": FIRMWARE_LATEST,
            "session": None,
        }
        if session:
            payload["session"] = {
                "id": session.id,
                "course": session.course.code[:12],
                "starts_utc": int(session.starts_at.timestamp()),
                "ends_utc": int(session.ends_at.timestamp()),
                "grace_minutes": session.grace_minutes,
                "status": session.status,
            }
        # Stamped last, after the queries above, so the device anchors its
        # clock to a time as close as possible to when it reads the reply.
        payload["server_utc_ms"] = server_ms()
        return Response(payload)


class BundleView(DeviceView):
    """The current session and its roster. Answers 304 when the device
    already holds the right version, which is most of the time."""

    def get(self, request):
        self.touch(request)
        device = request.device
        session = active_session_for(device)
        version = bundle_version(session, device.org)

        try:
            have = int(request.query_params.get("version", -1))
        except (TypeError, ValueError):
            have = -1
        if have == version:
            return Response(status=status.HTTP_304_NOT_MODIFIED)

        if session is None:
            return Response({"version": 0, "session": None, "roster": []})

        return Response({
            "version": version,
            "session": {
                "id": session.id,
                "course": session.course.code[:12],
                "starts_utc": int(session.starts_at.timestamp()),
                "ends_utc": int(session.ends_at.timestamp()),
                "grace_minutes": session.grace_minutes,
            },
            "roster": [{"id": r["id"], "name": r["short_name"][:16]}
                       for r in roster_for(session)],
        })


class DirectoryView(DeviceView):
    """Every active card, as packed binary. The device stores it sorted
    and looks a UID up by binary search."""

    def get(self, request):
        self.touch(request)
        try:
            have = int(request.query_params.get("version", -1))
        except (TypeError, ValueError):
            have = -1

        # Layout 2 carries each holder's name for the display, and comes in
        # pages so a large school fits the reader's receive buffer. It is
        # ?layout=2 because DRF reserves ?format= for content negotiation.
        # Readers that do not ask for it get layout 1 unchanged.
        if request.query_params.get("layout") == "2":
            try:
                offset = max(0, int(request.query_params.get("offset", 0)))
                limit = int(request.query_params.get("limit", DIR2_PAGE))
            except (TypeError, ValueError):
                offset, limit = 0, DIR2_PAGE
            limit = min(max(limit, 1), DIR2_PAGE)
            blob, version, total = pack_directory_v2(request.device.org, offset, limit)
            if have == version and offset == 0:
                return HttpResponse(status=304)
            resp = HttpResponse(blob, content_type="application/octet-stream")
            resp["X-Directory-Version"] = str(version)
            resp["X-Directory-Count"] = str(total)
            return resp

        blob, version, count = pack_directory(request.device.org)
        if have == version:
            return HttpResponse(status=304)

        resp = HttpResponse(blob, content_type="application/octet-stream")
        resp["X-Directory-Version"] = str(version)
        resp["X-Directory-Count"] = str(count)
        return resp


class AttendanceUploadView(DeviceView):
    """Batch upload. Each record carries a client id; combined with the
    unique constraint, a retry after a dropped connection can never
    create a duplicate row.

    The server, not the device, decides whether a tap counts. The device
    reports what it saw and how long ago; the time is rebuilt from the
    server's own clock and the tap is judged against the timetable here.
    A tap outside a session's start and end is stored for the record but
    never becomes attendance."""

    MAX_BATCH = 100
    TIME_CONF = ("synced", "drift", "unknown")

    def tap_time(self, r, received):
        """When the tap happened, and how far that can be trusted.

        age_ms is the preferred source: the device measures how long ago
        the tap was on its own uptime counter, which needs no clock at
        all, and the server subtracts that from its own time. It is only
        sent for taps made since the device last booted. Older taps fall
        back to the device's wall clock, if it had one."""
        age = r.get("age_ms")
        if isinstance(age, int) and not isinstance(age, bool) and age >= 0:
            return received - timedelta(milliseconds=age), "synced"

        ts = r.get("ts_utc")
        conf = str(r.get("time_conf", "unknown"))
        if conf not in self.TIME_CONF:
            conf = "unknown"
        if isinstance(ts, int) and ts > 0 and conf != "unknown":
            return datetime.fromtimestamp(ts, tz=dt_timezone.utc), conf
        return None, "unknown"

    def post(self, request):
        received = timezone.now()
        self.touch(request)
        device = request.device
        records = request.data.get("records")
        if not isinstance(records, list):
            return Response({"detail": "records must be a list."},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(records) > self.MAX_BATCH:
            return Response({"detail": f"At most {self.MAX_BATCH} records."},
                            status=status.HTTP_400_BAD_REQUEST)

        results = []
        pending = []

        # Only active cards identify a student. A revoked card is still
        # logged, but it no longer speaks for anyone.
        uids = {str(r.get("uid", "")).upper() for r in records
                if isinstance(r, dict) and r.get("uid")}
        cards = {c.uid: c for c in Card.objects.filter(
            org=device.org, uid__in=uids, active=True).select_related("student")}

        for r in records:
            if not isinstance(r, dict):
                results.append({"client_id": None, "status": "invalid",
                                "detail": "record must be an object"})
                continue
            cid = r.get("client_id")
            if not isinstance(cid, int) or isinstance(cid, bool) or cid < 0:
                results.append({"client_id": cid, "status": "invalid",
                                "detail": "client_id must be an integer"})
                continue

            uid = str(r.get("uid", "")).upper()[:20]
            if not uid:
                results.append({"client_id": cid, "status": "invalid",
                                "detail": "uid required"})
                continue

            tapped_at, conf = self.tap_time(r, received)
            pending.append({
                "cid": cid, "uid": uid, "card": cards.get(uid),
                "tapped_at": tapped_at, "conf": conf,
                "device_outcome": str(r.get("outcome", ""))[:16],
            })

        verdicts = judge_taps(device, pending)
        taps = []
        for p, (outcome, session) in zip(pending, verdicts):
            card = p["card"]
            taps.append(TapEvent(
                org=device.org, device=device, uid=p["uid"],
                student=card.student if card else None,
                session=session, outcome=outcome,
                device_outcome=p["device_outcome"],
                tapped_at=p["tapped_at"] or received,
                time_conf=p["conf"], client_id=p["cid"]))
            results.append({"client_id": p["cid"], "status": "accepted",
                            "outcome": outcome})

        with transaction.atomic():
            # ignore_conflicts makes a replayed batch harmless.
            TapEvent.objects.bulk_create(taps, ignore_conflicts=True)
            self._derive_attendance(device, taps)

        return Response({
            "received": len(records),
            "accepted": len(taps),
            "server_utc": int(timezone.now().timestamp()),
            "server_utc_ms": server_ms(),
            "results": results,
        })

    def _derive_attendance(self, device, taps):
        """Turn counted taps into attendance rows. Only judge_taps() can
        produce present or late, and only for a tap inside a session's
        window. A tap timed by a drifting device clock is counted but
        flagged, so a lecturer can confirm it rather than it being
        silently trusted."""
        rows = []
        for t in taps:
            if t.outcome not in ("present", "late"):
                continue
            rows.append(AttendanceRecord(
                org=t.org, session_id=t.session_id, student_id=t.student_id,
                status=t.outcome, tapped_at=t.tapped_at, device=device,
                verified=(t.time_conf == "synced")))
        if rows:
            AttendanceRecord.objects.bulk_create(rows, ignore_conflicts=True)


class EnrollView(DeviceView):
    """Reports a card seen while the device is in enrolment mode.

    The device never creates a student or binds a card - it only reports
    a sighting. Binding always happens in the dashboard, by an
    authenticated admin, so a stolen device cannot forge a student."""

    def post(self, request):
        self.touch(request)
        device = request.device
        uid = str(request.data.get("uid", "")).upper().strip()
        if not uid or len(uid) not in (8, 14, 20):
            return Response({"detail": "Invalid UID."},
                            status=status.HTTP_400_BAD_REQUEST)

        card = Card.objects.filter(org=device.org, uid=uid).first()
        cid = request.data.get("client_id")
        TapEvent.objects.get_or_create(
            device=device, client_id=cid if isinstance(cid, int) else 0,
            defaults={
                "org": device.org, "uid": uid,
                "student": card.student if card else None,
                "outcome": "enroll_scan", "tapped_at": timezone.now(),
                "time_conf": "synced"})

        if card and card.student:
            return Response({"known": True, "student": card.student.short_name,
                             "matric_no": card.student.matric_no})
        return Response({"known": False, "uid": uid,
                         "detail": "Logged for an administrator to bind."})
