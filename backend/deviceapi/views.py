from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import (Card, Student, Device, TapEvent, AttendanceRecord,
                         ClassSession)
from .authentication import DeviceTokenAuthentication
from .permissions import IsDevice
from .services import (active_session_for, roster_for, bundle_version,
                       pack_directory)

FIRMWARE_LATEST = "0.1.0"


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
        blob, version, count = pack_directory(request.device.org)

        try:
            have = int(request.query_params.get("version", -1))
        except (TypeError, ValueError):
            have = -1
        if have == version:
            return HttpResponse(status=304)

        resp = HttpResponse(blob, content_type="application/octet-stream")
        resp["X-Directory-Version"] = str(version)
        resp["X-Directory-Count"] = str(count)
        return resp


class AttendanceUploadView(DeviceView):
    """Batch upload. Each record carries a client id; combined with the
    unique constraint, a retry after a dropped connection can never
    create a duplicate row."""

    MAX_BATCH = 100

    def post(self, request):
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
        accepted_ids = []
        taps = []

        # Resolve every UID and session in two queries, not two per record.
        uids = {str(r.get("uid", "")).upper() for r in records if r.get("uid")}
        cards = {c.uid: c for c in Card.objects.filter(
            org=device.org, uid__in=uids).select_related("student")}
        sids = {r.get("session_id") for r in records if r.get("session_id")}
        sessions = {s.id: s for s in ClassSession.objects.filter(
            org=device.org, id__in=[s for s in sids if s])}

        for r in records:
            cid = r.get("client_id")
            if not isinstance(cid, int):
                results.append({"client_id": cid, "status": "invalid",
                                "detail": "client_id must be an integer"})
                continue

            uid = str(r.get("uid", "")).upper()
            outcome = str(r.get("outcome", ""))[:16]
            ts = r.get("ts_utc")
            conf = str(r.get("time_conf", "synced"))[:8]
            sid = r.get("session_id") or None

            if not uid or not outcome or not isinstance(ts, int):
                results.append({"client_id": cid, "status": "invalid",
                                "detail": "uid, outcome and ts_utc required"})
                continue

            card = cards.get(uid)
            session = sessions.get(sid) if sid else None
            tapped_at = timezone.datetime.fromtimestamp(
                ts, tz=timezone.utc) if ts > 0 else timezone.now()

            taps.append(TapEvent(
                org=device.org, device=device, uid=uid,
                student=card.student if card else None,
                session=session, outcome=outcome,
                tapped_at=tapped_at, time_conf=conf, client_id=cid))
            accepted_ids.append(cid)
            results.append({"client_id": cid, "status": "accepted"})

        with transaction.atomic():
            # ignore_conflicts makes a replayed batch harmless.
            TapEvent.objects.bulk_create(taps, ignore_conflicts=True)
            self._derive_attendance(device, taps)

        return Response({
            "received": len(records),
            "accepted": len(accepted_ids),
            "server_utc": int(timezone.now().timestamp()),
            "results": results,
        })

    def _derive_attendance(self, device, taps):
        """Turn accepted taps into attendance rows. A tap recorded while
        the device clock was unreliable is stored but flagged, so a
        lecturer can confirm it rather than it being silently trusted."""
        rows = []
        for t in taps:
            if t.outcome not in ("present", "late"):
                continue
            if not t.student_id or not t.session_id:
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
