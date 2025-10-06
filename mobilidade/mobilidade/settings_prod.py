from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F401,F403
from .settings import _list_setting

DEBUG = False

if not SECRET_KEY or SECRET_KEY == "unsafe-development-secret":
    raise ImproperlyConfigured("SECRET_KEY must be set for production environments.")

ALLOWED_HOSTS = _list_setting("ALLOWED_HOSTS", default=[])
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must include at least one host in production.")

CORS_ALLOWED_ORIGINS = _list_setting("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOWED_ORIGIN_REGEXES = _list_setting(
    "CORS_ALLOWED_ORIGIN_REGEXES", default=CORS_ALLOWED_ORIGIN_REGEXES
)
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)

if not (CORS_ALLOWED_ORIGINS or CORS_ALLOWED_ORIGIN_REGEXES or CORS_ALLOW_ALL_ORIGINS):
    raise ImproperlyConfigured(
        "Configure at least one of CORS_ALLOWED_ORIGINS, CORS_ALLOWED_ORIGIN_REGEXES, "
        "or explicitly enable CORS_ALLOW_ALL_ORIGINS for production."
    )

CSRF_TRUSTED_ORIGINS = _list_setting("CSRF_TRUSTED_ORIGINS", default=CSRF_TRUSTED_ORIGINS)
if not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
WHITENOISE_MAX_AGE = env.int("WHITENOISE_MAX_AGE", default=60 * 60 * 24 * 30)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
