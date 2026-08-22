import re

from django.core.exceptions import ValidationError


class PinValidator:
    """Password validator repurposed for the 4-digit login PIN."""

    pin_re = re.compile(r"^\d{4}$")

    def validate(self, password, user=None):
        if not self.pin_re.match(password):
            raise ValidationError(
                "Le code PIN doit contenir exactement 4 chiffres.",
                code="pin_invalid",
            )

    def get_help_text(self):
        return "Le code PIN doit contenir exactement 4 chiffres."
