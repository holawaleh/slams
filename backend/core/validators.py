import re
from django.core.exceptions import ValidationError

# Kept in step with PASSWORD_RULES in frontend/src/lib/password.js.
RULES = [
    (r"[a-z]", "a lowercase letter"),
    (r"[A-Z]", "an uppercase letter"),
    (r"[0-9]", "a number"),
    (r"[^A-Za-z0-9]", "a symbol"),
]


class StrongPasswordValidator:
    def validate(self, password, user=None):
        missing = [label for rx, label in RULES if not re.search(rx, password)]
        if re.search(r"\s", password):
            raise ValidationError("Password must not contain spaces.",
                                  code="password_has_space")
        if missing:
            raise ValidationError(
                "Password must contain " + ", ".join(missing) + ".",
                code="password_too_weak")

    def get_help_text(self):
        return ("Your password must contain upper and lowercase letters, "
                "a number and a symbol.")
