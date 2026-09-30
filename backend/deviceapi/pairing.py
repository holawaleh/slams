"""Finding and adding readers without typing IDs or copying tokens.

  1. An unregistered reader announces itself every few seconds
     (AnnounceView) and shows the 6-digit pairing code it is given.
  2. An admin searches (discover): readers that announced recently from
     the same network as the admin's browser.
  3. The admin picks one and types the code from its screen (claim).
     The server creates the device and holds its token for the reader.
  4. The reader collects the token on its next announce and carries on
     as a normal registered reader.

A reader registered to any account never appears in a search and cannot
be claimed again until that account removes it.
"""

import hashlib
import ipaddress
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from core.models import Device
from .models import DiscoveredReader, new_pair_code

SEEN_WITHIN = timedelta(minutes=2)       # how recent counts as "nearby now"
FORGET_AFTER = timedelta(minutes=15)     # unclaimed rows are dropped after
MAX_WRONG_CODES = 5                      # then the reader gets a new code

HW_RX = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
SECRET_RX = re.compile(r"^[0-9a-f]{32,64}$")


def request_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    ip = fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")
    try:
        return str(ipaddress.ip_address(ip))
    except (TypeError, ValueError):
        return None


def same_network(a, b):
    """Whether two requests came from the same place. Behind one internet
    connection every device shares a public address. On a development
    setup (a server on the office LAN) both are private addresses."""
    if not a or not b:
        return False
    if a == b:
        return True
    ia, ib = ipaddress.ip_address(a), ipaddress.ip_address(b)
    local = lambda ip: ip.is_private or ip.is_loopback
    return local(ia) and local(ib)


def hardware_id_from(request):
    raw = request.headers.get("X-Device-Id", "") or str(request.data.get("hardware_id", ""))
    hexs = "".join(c for c in raw.upper() if c in "0123456789ABCDEF")
    hw = ":".join(hexs[i:i + 2] for i in range(0, 12, 2)) if len(hexs) == 12 else ""
    return hw if HW_RX.match(hw) else None


def forget_stale():
    now = timezone.now()
    DiscoveredReader.objects.filter(device__isnull=True,
                                    last_seen__lt=now - FORGET_AFTER).delete()
    # A claimed token nobody collected in a day is not coming back.
    DiscoveredReader.objects.filter(device__isnull=False,
                                    last_seen__lt=now - timedelta(days=1)).delete()


class AnnounceThrottle(AnonRateThrottle):
    scope = "announce"
    # Per public IP. A reader announces 12 times a minute, and a whole
    # school's readers share one address on setup day.
    rate = "300/min"


class AnnounceView(APIView):
    """POST /api/device/announce/ - an unregistered reader saying hello.

    Answers one of:
      waiting     show this pairing code on the screen
      paired      here is your token, you are now registered
      registered  this reader belongs to an account already"""
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnnounceThrottle]

    def post(self, request):
        hw = hardware_id_from(request)
        secret = str(request.data.get("secret", "")).lower()
        if not hw or not SECRET_RX.match(secret):
            return Response({"detail": "hardware id and secret required."},
                            status=status.HTTP_400_BAD_REQUEST)
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        now = timezone.now()
        forget_stale()

        mine = DiscoveredReader.objects.filter(hardware_id=hw,
                                               secret_hash=secret_hash).first()
        if mine and mine.device_id and mine.token:
            token = mine.token
            DiscoveredReader.objects.filter(hardware_id=hw).delete()
            return Response({"status": "paired", "token": token,
                             "device": mine.device.name,
                             "server_utc_ms": int(now.timestamp() * 1000)})

        if Device.objects.filter(hardware_id=hw).exists():
            return Response({"status": "registered"})

        if mine is None:
            mine = DiscoveredReader(hardware_id=hw, secret_hash=secret_hash)
        mine.last_seen = now
        mine.public_ip = request_ip(request)
        mine.local_ip = str(request.data.get("local_ip", ""))[:45]
        mine.firmware = str(request.data.get("firmware", ""))[:32]
        mine.save()
        return Response({"status": "waiting", "code": mine.code,
                         "server_utc_ms": int(now.timestamp() * 1000)})


def discover(request, org):
    """Unregistered readers announcing from the admin's network now."""
    here = request_ip(request)
    registered = Device.objects.exclude(hardware_id__isnull=True).values_list(
        "hardware_id", flat=True)
    rows = (DiscoveredReader.objects
            .filter(device__isnull=True, last_seen__gte=timezone.now() - SEEN_WITHIN)
            .exclude(hardware_id__in=registered)
            .order_by("hardware_id", "-last_seen"))
    seen, out = set(), []
    for r in rows:
        if r.hardware_id in seen or not same_network(here, r.public_ip):
            continue
        seen.add(r.hardware_id)
        out.append({"hardware_id": r.hardware_id, "local_ip": r.local_ip,
                    "firmware": r.firmware, "last_seen": r.last_seen})
    return out


class ClaimSerializer(serializers.Serializer):
    hardware_id = serializers.CharField()
    code = serializers.RegexField(r"^\s*\d{3}\s?\d{3}\s*$", error_messages={
        "invalid": "Enter the 6-digit code shown on the reader."})


def claim(request, org, device_serializer):
    """Check the pairing code, then create the device. device_serializer
    is already validated (name, venue, hardware id not registered)."""
    s = ClaimSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    hw = device_serializer.validated_data["hardware_id"]
    code = s.validated_data["code"].replace(" ", "").strip()

    candidates = DiscoveredReader.objects.filter(
        hardware_id=hw, device__isnull=True,
        last_seen__gte=timezone.now() - FORGET_AFTER)
    if not candidates.exists():
        raise serializers.ValidationError({"hardware_id":
            "That reader is not announcing itself. Check it is powered on and "
            "online, then search again."})

    match = candidates.filter(code=code).first()
    if match is None:
        for r in candidates:
            r.failed_attempts += 1
            if r.failed_attempts >= MAX_WRONG_CODES:
                r.code, r.failed_attempts = new_pair_code(), 0
            r.save(update_fields=["failed_attempts", "code"])
        raise serializers.ValidationError({"code":
            "That is not the code on the reader's screen. After 5 wrong tries "
            "the reader shows a new code."})

    with transaction.atomic():
        device = device_serializer.save()
        match.device, match.token = device, device.token
        match.save(update_fields=["device", "token"])
        candidates.exclude(pk=match.pk).delete()
    return device
