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

        request.device = device
        return (None, device)

    def authenticate_header(self, request):
        return self.keyword
