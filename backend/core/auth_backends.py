from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveUsernameBackend(ModelBackend):
    """Usernames are stored lowercase. People type them any way they like,
    so match without regard to case rather than rejecting the login."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            return None
        User = get_user_model()
        try:
            user = User.objects.get(username__iexact=username.strip())
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            # Hash anyway, so a missing username takes the same time as a
            # wrong password and cannot be detected by timing.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
