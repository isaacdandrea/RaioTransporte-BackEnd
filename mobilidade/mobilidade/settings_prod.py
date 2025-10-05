from .settings import *
import os

DEBUG = False
ALLOWED_HOSTS = ["your.api.domain", "localhost"]  # don't use "*"
SECRET_KEY = os.environ.get("SECRET_KEY")  # read from env in prod

# Use explicit origins in prod (see section 3)
CORS_ALLOW_ALL_ORIGINS = False

# Static
STATIC_ROOT = BASE_DIR / "staticfiles"

# Ensure WhiteNoise comes RIGHT AFTER SecurityMiddleware
# Rebuild the list explicitly for clarity:
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
