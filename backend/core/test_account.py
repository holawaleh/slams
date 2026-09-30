from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .tenancy import Membership, Organization

GOOD = "Xk9!mQ2#vLp7"


class AccountTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Uni", slug="uni")
        self.owner = self.member("boss", Membership.OWNER)
        self.admin = self.member("admin", Membership.ADMIN)
        self.lect = self.member("lect", Membership.LECTURER)

    def member(self, name, role):
        u = User.objects.create_user(name, password=GOOD, first_name=name.title())
        m = Membership.objects.create(user=u, org=self.org, role=role)
        c = APIClient()
        c.force_authenticate(u)
        c.m = m
        return c

    def add(self, client, role, username="newstaff"):
        return client.post("/api/members/", {
            "full_name": "Ngozi Eze", "username": username, "email": "N@x.com",
            "role": role, "password": GOOD}, format="json")

    # ---- own account ----
    def test_change_password_needs_current_one(self):
        r = self.lect.post("/api/me/password/", {"current_password": "wrong",
                                                 "new_password": "Nw9!aaaaaaaa"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("current_password", r.json())
        r = self.lect.post("/api/me/password/", {"current_password": GOOD,
                                                 "new_password": "short"})
        self.assertIn("new_password", r.json())
        r = self.lect.post("/api/me/password/", {"current_password": GOOD,
                                                 "new_password": "Nw9!aaaaaaaa"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.get(username="lect").check_password("Nw9!aaaaaaaa"))

    def test_profile_update(self):
        r = self.lect.patch("/api/me/profile/", {"full_name": " Ada  Obi ",
                                                 "email": "ADA@X.COM"})
        self.assertEqual(r.status_code, 200)
        u = User.objects.get(username="lect")
        self.assertEqual((u.first_name, u.last_name, u.email), ("Ada", "Obi", "ada@x.com"))

    # ---- adding staff ----
    def test_admin_adds_lecturer_who_can_log_in(self):
        r = self.add(self.admin, "lecturer")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["role"], "lecturer")
        login = APIClient().post("/api/auth/login/", {"username": "newstaff",
                                                      "password": GOOD})
        self.assertEqual(login.status_code, 200)

    def test_admin_cannot_create_admins_or_owners(self):
        self.assertEqual(self.add(self.admin, "admin").status_code, 403)
        self.assertEqual(self.add(self.admin, "owner").status_code, 403)
        self.assertEqual(self.add(self.owner, "admin").status_code, 201)

    def test_lecturer_cannot_add_staff(self):
        self.assertEqual(self.add(self.lect, "viewer").status_code, 403)

    def test_weak_password_and_taken_username_refused(self):
        r = self.admin.post("/api/members/", {
            "full_name": "X Y", "username": "lect", "role": "viewer",
            "password": GOOD}, format="json")
        self.assertIn("username", r.json())
        r = self.admin.post("/api/members/", {
            "full_name": "X Y", "username": "fresh", "role": "viewer",
            "password": "password"}, format="json")
        self.assertIn("password", r.json())

    # ---- roles ----
    def test_role_rules(self):
        url = lambda c: f"/api/members/{c.m.pk}/"
        # Admin may promote a lecturer to viewer and back, not to admin.
        self.assertEqual(self.admin.patch(url(self.lect), {"role": "viewer"}).status_code, 200)
        self.assertEqual(self.admin.patch(url(self.lect), {"role": "admin"}).status_code, 403)
        # Admin may not demote the owner; owner may promote the admin.
        self.assertEqual(self.admin.patch(url(self.owner), {"role": "viewer"}).status_code, 403)
        self.assertEqual(self.owner.patch(url(self.admin), {"role": "owner"}).status_code, 200)

    def test_last_owner_is_protected(self):
        r = self.owner.patch(f"/api/members/{self.owner.m.pk}/", {"role": "admin"})
        self.assertEqual(r.status_code, 400)
        second = self.member("boss2", Membership.OWNER)
        r = second.delete(f"/api/members/{self.owner.m.pk}/")
        self.assertEqual(r.status_code, 204)
        r = second.patch(f"/api/members/{second.m.pk}/", {"role": "admin"})
        self.assertEqual(r.status_code, 400)

    def test_cannot_remove_yourself(self):
        r = self.admin.delete(f"/api/members/{self.admin.m.pk}/")
        self.assertEqual(r.status_code, 400)

    def test_reset_staff_password(self):
        r = self.admin.post(f"/api/members/{self.lect.m.pk}/set_password/",
                            {"password": "Nw9!bbbbbbbb"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.get(username="lect").check_password("Nw9!bbbbbbbb"))
        r = self.admin.post(f"/api/members/{self.owner.m.pk}/set_password/",
                            {"password": "Nw9!bbbbbbbb"})
        self.assertEqual(r.status_code, 403)

    def test_other_schools_staff_are_invisible(self):
        other = Organization.objects.create(name="O", slug="o")
        u = User.objects.create_user("outsider", password=GOOD)
        m = Membership.objects.create(user=u, org=other, role=Membership.OWNER)
        self.assertEqual(self.owner.patch(f"/api/members/{m.pk}/",
                                          {"role": "viewer"}).status_code, 404)
        names = [x["username"] for x in self.owner.get("/api/members/").json()["results"]]
        self.assertNotIn("outsider", names)
