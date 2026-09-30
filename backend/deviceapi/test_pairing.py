from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Device
from core.tenancy import Membership, Organization
from .models import DiscoveredReader

HW = "A0:DD:6C:10:80:40"
SECRET = "0123456789abcdef0123456789abcdef"
SCHOOL_IP = "102.89.1.10"


def admin_of(slug, ip=SCHOOL_IP):
    org = Organization.objects.create(name=slug, slug=slug)
    u = User.objects.create_user(f"a-{slug}", password="x")
    Membership.objects.create(user=u, org=org, role=Membership.OWNER)
    c = APIClient(REMOTE_ADDR=ip)
    c.force_authenticate(u)
    return org, c


def reader(hw=HW, secret=SECRET, ip=SCHOOL_IP):
    c = APIClient(REMOTE_ADDR=ip)

    def announce():
        return c.post("/api/device/announce/", {"secret": secret, "firmware": "0.2.0",
                                                "local_ip": "192.168.100.43"},
                      format="json", HTTP_X_DEVICE_ID=hw).json()
    return announce


class PairingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org, self.admin = admin_of("alpha")
        self.announce = reader()

    def claim(self, client, code, hw=HW, name="Hall reader"):
        return client.post("/api/devices/claim/", {
            "hardware_id": hw, "code": code, "name": name}, format="json")

    def test_full_pairing(self):
        first = self.announce()
        self.assertEqual(first["status"], "waiting")
        self.assertRegex(first["code"], r"^\d{6}$")
        self.assertEqual(self.announce()["code"], first["code"])   # stable

        found = self.admin.get("/api/devices/discover/").json()
        self.assertEqual([r["hardware_id"] for r in found], [HW])
        self.assertNotIn("code", found[0])                         # never listed

        r = self.claim(self.admin, first["code"][:3] + " " + first["code"][3:])
        self.assertEqual(r.status_code, 201, r.content)
        device = Device.objects.get(hardware_id=HW)
        self.assertEqual(device.org, self.org)

        got = self.announce()
        self.assertEqual((got["status"], got["token"]), ("paired", device.token))
        self.assertFalse(DiscoveredReader.objects.exists())        # token handed over once
        self.assertEqual(self.announce()["status"], "registered")

        # The token now works, from this reader only.
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Device {device.token}", HTTP_X_DEVICE_ID=HW)
        self.assertEqual(c.post("/api/device/hello/", {}, format="json").status_code, 200)

    def test_wrong_code_is_refused_and_code_rotates(self):
        code = self.announce()["code"]
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(4):
            self.assertIn("code", self.claim(self.admin, wrong).json())
        self.assertEqual(self.announce()["code"], code)
        self.claim(self.admin, wrong)                              # fifth
        self.assertNotEqual(self.announce()["code"], code)
        self.assertFalse(Device.objects.exists())

    def test_readers_on_another_network_are_not_listed(self):
        reader(hw="11:22:33:44:55:66", secret="f" * 32, ip="41.58.9.9")()
        self.announce()
        found = self.admin.get("/api/devices/discover/").json()
        self.assertEqual([r["hardware_id"] for r in found], [HW])

    def test_but_can_be_claimed_by_id_and_code(self):
        code = reader(hw="11:22:33:44:55:66", secret="f" * 32, ip="41.58.9.9")()["code"]
        r = self.claim(self.admin, code, hw="11:22:33:44:55:66")
        self.assertEqual(r.status_code, 201, r.content)

    def test_local_network_setup_counts_as_nearby(self):
        _, lan_admin = admin_of("lan", ip="127.0.0.1")
        reader(hw="22:22:33:44:55:66", secret="e" * 32, ip="192.168.100.43")()
        found = lan_admin.get("/api/devices/discover/").json()
        self.assertIn("22:22:33:44:55:66", [r["hardware_id"] for r in found])

    def test_registered_reader_is_invisible_and_unclaimable_elsewhere(self):
        code = self.announce()["code"]
        self.claim(self.admin, code)
        self.announce()                                           # collects token
        _, other = admin_of("beta")
        self.assertEqual(other.get("/api/devices/discover/").json(), [])
        self.assertEqual(self.claim(other, code).status_code, 400)
        self.assertEqual(Device.objects.count(), 1)

    def test_removed_reader_can_be_paired_elsewhere(self):
        self.claim(self.admin, self.announce()["code"])
        self.announce()
        device = Device.objects.get()
        self.admin.delete(f"/api/devices/{device.pk}/")
        again = self.announce()
        self.assertEqual(again["status"], "waiting")
        _, other = admin_of("beta")
        self.assertEqual(self.claim(other, again["code"]).status_code, 201)

    def test_copied_mac_cannot_collect_the_token(self):
        code = self.announce()["code"]
        impostor = reader(secret="9" * 32)
        fake = impostor()
        self.assertNotEqual(fake["code"], code)          # its own row, own code
        self.claim(self.admin, code)                     # admin types the real one
        self.assertNotEqual(impostor()["status"], "paired")
        self.assertEqual(self.announce()["status"], "paired")

    def test_bad_announces_rejected(self):
        c = APIClient()
        r = c.post("/api/device/announce/", {"secret": "short"}, format="json",
                   HTTP_X_DEVICE_ID=HW)
        self.assertEqual(r.status_code, 400)
        r = c.post("/api/device/announce/", {"secret": SECRET}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_stale_announcements_disappear(self):
        self.announce()
        DiscoveredReader.objects.update(last_seen=timezone.now() - timedelta(minutes=5))
        self.assertEqual(self.admin.get("/api/devices/discover/").json(), [])

    def test_lecturer_cannot_search_or_claim(self):
        u = User.objects.create_user("lect", password="x")
        Membership.objects.create(user=u, org=self.org, role=Membership.LECTURER)
        c = APIClient()
        c.force_authenticate(u)
        self.assertEqual(c.get("/api/devices/discover/").status_code, 403)
        self.assertEqual(self.claim(c, self.announce()["code"]).status_code, 403)


class RepairTests(TestCase):
    """A registered reader lost its token (storage wiped, firmware
    reinstalled). Its own account reconnects it; nobody else can."""

    def setUp(self):
        cache.clear()
        self.org, self.admin = admin_of("alpha")
        announce = reader()
        self.admin.post("/api/devices/claim/", {
            "hardware_id": HW, "code": announce()["code"], "name": "LR1"}, format="json")
        announce()                                     # collects its token
        self.device = Device.objects.get()
        self.old_token = self.device.token
        # Lost everything, including its secret.
        self.announce = reader(secret="a" * 32)

    def test_lost_token_reader_is_not_offered_a_code_without_repair(self):
        self.assertEqual(self.announce()["status"], "registered")

    def test_repair_reconnects_the_same_entry(self):
        r = self.admin.post(f"/api/devices/{self.device.pk}/repair/")
        self.assertEqual(r.status_code, 200, r.content)
        code = self.announce()["code"]
        # Still not listed in anyone's search.
        self.assertEqual(self.admin.get("/api/devices/discover/").json(), [])
        r = self.admin.post(f"/api/devices/{self.device.pk}/repair_confirm/",
                            {"code": code}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        got = self.announce()
        self.assertEqual(got["status"], "paired")
        self.device.refresh_from_db()
        self.assertEqual(got["token"], self.device.token)
        self.assertNotEqual(self.device.token, self.old_token)   # old copy dead
        self.assertIsNone(self.device.repair_until)
        self.assertEqual((Device.objects.count(), self.device.name), (1, "LR1"))

    def test_wrong_code_and_expired_window(self):
        self.admin.post(f"/api/devices/{self.device.pk}/repair/")
        code = self.announce()["code"]
        wrong = "000000" if code != "000000" else "111111"
        r = self.admin.post(f"/api/devices/{self.device.pk}/repair_confirm/",
                            {"code": wrong}, format="json")
        self.assertEqual(r.status_code, 400)
        Device.objects.update(repair_until=timezone.now() - timedelta(minutes=1))
        r = self.admin.post(f"/api/devices/{self.device.pk}/repair_confirm/",
                            {"code": code}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_other_account_cannot_repair_or_claim(self):
        _, other = admin_of("beta")
        self.assertEqual(other.post(f"/api/devices/{self.device.pk}/repair/").status_code, 404)
        self.admin.post(f"/api/devices/{self.device.pk}/repair/")
        code = self.announce()["code"]
        r = other.post("/api/devices/claim/", {"hardware_id": HW, "code": code,
                                               "name": "stolen"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Device.objects.count(), 1)
