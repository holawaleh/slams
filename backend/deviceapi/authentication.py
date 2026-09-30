from django.utils import timezone
from rest_framework import authentication, exceptions
from core.models import Device


class DeviceTokenAuthentication(authentication.BaseAuthentication):
    """Authenticates a device by its own token, sent as:

        Authorization: Device <token>

    The device is not a Django user. request.user stays anonymous and
    request.device carries the hardware identity, which also means a
    stolen device token can never reach the dashboard API."""

    keyword = "Device"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith(self.keyword + " "):
            return None
        token = header[len(self.keyword) + 1:].strip()
        if not token:
            raise exceptions.AuthenticationFailed("Empty device token.")

        try:
            device = Device.objects.select_related("org", "venue").get(
                token=token)
        except Device.DoesNotExist:
            raise exceptions.AuthenticationFailed("Unknown device token.")

        if not device.active:
            raise exceptions.AuthenticationFailed("Device is deactivated.")
        if not device.org.active:
            raise exceptions.AuthenticationFailed("Organization is inactive.")

        self.check_hardware(request, device)
        request.device = device
        return (None, device)

    def check_hardware(self, request, device):
        """A token only works from the reader it was issued to.

        The reader sends its MAC address with every request. Registered
        readers must match it exactly, so a token copied onto another
        reader is refused. A device row created before readers had an
        identity claims the first reader that uses it, unless that
        reader is already registered, here or in another account."""
        raw = request.headers.get("X-Device-Id", "")
        hw = "".join(c for c in raw.upper() if c in "0123456789ABCDEF")
        hw = ":".join(hw[i:i + 2] for i in range(0, 12, 2)) if len(hw) == 12 else ""

        if device.hardware_id:
            if hw != device.hardware_id:
                raise exceptions.AuthenticationFailed(
                    "This token belongs to a different reader.")
            return
        if not hw:
            return                      # older firmware, unregistered row
        if Device.objects.filter(hardware_id=hw).exclude(pk=device.pk).exists():
            raise exceptions.AuthenticationFailed(
                "This reader is registered to another device entry. Remove "
                "it there first.")
        Device.objects.filter(pk=device.pk, hardware_id__isnull=True).update(
            hardware_id=hw)
        device.hardware_id = hw

    def authenticate_header(self, request):
        return self.keyword
