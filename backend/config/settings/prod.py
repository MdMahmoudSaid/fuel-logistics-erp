from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = ["https://azurenergie.hasel.food", "https://hasel.food", "https://www.hasel.food"]
SECURE_SSL_HOST = "azurenergie.hasel.food"
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^api/healthz$"]
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
DATABASES["default"]["CONN_MAX_AGE"] = 60
