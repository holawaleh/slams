import secrets
from django.db import models
from django.contrib.auth.models import User


class Organization(models.Model):
    """One institution. The tenant boundary. Every other row belongs to
    exactly one of these and is never visible outside it."""
    name       = models.CharField(max_length=128)
    slug       = models.SlugField(max_length=48, unique=True,
                                  help_text="Short code used in invites")
    address    = models.CharField(max_length=255, blank=True)
    country    = models.CharField(max_length=64, blank=True)
    term       = models.CharField(max_length=16, default="2025/2026-1",
                                  help_text="Current academic term")
    timezone   = models.CharField(max_length=48, default="Africa/Lagos")
    active     = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Limits, so one signup cannot exhaust shared resources.
    max_devices  = models.PositiveIntegerField(default=10)
    max_students = models.PositiveIntegerField(default=5000)

    def __str__(self):
        return self.name


class Membership(models.Model):
    """Links a user to an organization with a role. Roles are per-org,
    not global, so the same person can hold different roles elsewhere."""
    OWNER, ADMIN, LECTURER, VIEWER = "owner", "admin", "lecturer", "viewer"
    ROLES = [(OWNER, "Owner"), (ADMIN, "Admin"),
             (LECTURER, "Lecturer"), (VIEWER, "Viewer")]

    user       = models.ForeignKey(User, on_delete=models.CASCADE,
                                   related_name="memberships")
    org        = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                   related_name="memberships")
    role       = models.CharField(max_length=12, choices=ROLES, default=VIEWER)
    is_default = models.BooleanField(default=True,
                                     help_text="Org selected at login")
    joined_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "org"],
                                    name="uniq_user_per_org"),
        ]
        indexes = [models.Index(fields=["user", "is_default"])]

    @property
    def can_administer(self):
        return self.role in (self.OWNER, self.ADMIN)

    def __str__(self):
        return f"{self.user.username}@{self.org.slug} ({self.role})"


class Invitation(models.Model):
    """How a second user joins an existing org instead of creating one."""
    org        = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                   related_name="invitations")
    email      = models.EmailField()
    role       = models.CharField(max_length=12, choices=Membership.ROLES,
                                  default=Membership.LECTURER)
    code       = models.CharField(max_length=64, unique=True, blank=True)
    invited_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    accepted   = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)


class TenantManager(models.Manager):
    """Forces callers to name an org. Using .all() on a tenant model is
    a bug, so the manager makes the scoped call the obvious one."""
    def for_org(self, org):
        return self.get_queryset().filter(org=org)


class TenantModel(models.Model):
    """Base for every row that belongs to an institution."""
    org = models.ForeignKey(Organization, on_delete=models.CASCADE,
                            related_name="%(class)ss")
    objects = TenantManager()

    class Meta:
        abstract = True
