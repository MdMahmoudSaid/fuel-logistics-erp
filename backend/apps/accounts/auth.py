from datetime import timedelta

from django.utils import timezone
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import PasswordField, TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import User

MAX_FAILED_PIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


class PhonePinTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["password"]
        self.fields["pin"] = PasswordField()

    def validate(self, attrs):
        phone = attrs.get(self.username_field)
        pin = attrs.get("pin")

        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            raise AuthenticationFailed("Numéro de téléphone ou code PIN invalide.")

        if user.is_locked():
            raise AuthenticationFailed("Compte verrouillé. Réessayez dans quelques minutes.")

        if not user.is_active or not user.check_password(pin):
            user.failed_pin_attempts += 1
            if user.failed_pin_attempts >= MAX_FAILED_PIN_ATTEMPTS:
                user.locked_until = timezone.now() + LOCKOUT_DURATION
            user.save(update_fields=["failed_pin_attempts", "locked_until"])
            raise AuthenticationFailed("Numéro de téléphone ou code PIN invalide.")

        if user.failed_pin_attempts or user.locked_until:
            user.failed_pin_attempts = 0
            user.locked_until = None
            user.save(update_fields=["failed_pin_attempts", "locked_until"])

        refresh = self.get_token(user)
        return {"refresh": str(refresh), "access": str(refresh.access_token)}


class PhonePinTokenObtainPairView(TokenObtainPairView):
    serializer_class = PhonePinTokenObtainPairSerializer
