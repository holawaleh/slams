import secrets

from django.db import models


def new_pair_code():
    return f"{secrets.randbelow(1_000_000):06d}"


class DiscoveredReader(models.Model):
    """A reader that is on the network but not registered to anyone yet.

    Unregistered readers announce themselves every few seconds. An admin
    on the same network sees them under "Search for readers", picks one,
    and types in the pairing code the reader shows on its screen. That
    code proves the admin is standing at that reader; the list alone is
    never enough to claim one.

    A row is keyed by the hardware id *and* a secret the reader generated
    at its first boot. MAC addresses can be copied, so the token is only
    ever handed to whoever holds the secret that announced the code the
    admin typed - which is the physical reader."""

    hardware_id = models.CharField(max_length=17, db_index=True)
    secret_hash = models.CharField(max_length=64)
    code        = models.CharField(max_length=6, default=new_pair_code)
    public_ip   = models.GenericIPAddressField(null=True, blank=True)
    local_ip    = models.CharField(max_length=45, blank=True)
    firmware    = models.CharField(max_length=32, blank=True)
    first_seen  = models.DateTimeField(auto_now_add=True)
    last_seen   = models.DateTimeField()
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    # Set when an admin claims it; the token waits here until the reader
    # collects it on its next announce, then the row is deleted.
    device      = models.ForeignKey("core.Device", null=True, blank=True,
                                    on_delete=models.CASCADE)
    token       = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["hardware_id", "secret_hash"], name="uniq_reader_secret")]
        indexes = [models.Index(fields=["last_seen"])]

    def __str__(self):
        return f"{self.hardware_id} ({'claimed' if self.device_id else 'waiting'})"
