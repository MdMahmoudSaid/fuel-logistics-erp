from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, phone, pin, **extra_fields):
        if not phone:
            raise ValueError("Les utilisateurs doivent avoir un numéro de téléphone")
        user = self.model(phone=phone, **extra_fields)
        user.set_password(pin)
        user.save(using=self._db)
        return user

    def create_user(self, phone, pin=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone, pin, **extra_fields)

    def create_superuser(self, phone, pin=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(phone, pin, **extra_fields)
