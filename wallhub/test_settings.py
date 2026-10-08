"""Settings for the test suite: wallhub.settings with test-only overrides."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-secret")

from wallhub.settings import *  # noqa: E402, F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_BROKER_URL = "memory://"
# No collectstatic in tests: no manifest of hashed names, and no STATIC_ROOT for
# WhiteNoise to index at startup (autorefresh looks files up per request instead).
WHITENOISE_AUTOREFRESH = True
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
