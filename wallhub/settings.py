"""Django settings for wall-hub.

Everything that differs between a laptop, CI and the VM comes from environment
variables; see .env.example for the full list.
"""

import os
from pathlib import Path

from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"environment variable {name} is required")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG")
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-not-secret" if DEBUG else None)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "inventory",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "wallhub.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "wallhub.wsgi.application"

# PostgreSQL when POSTGRES_DB is set (Docker, CI); SQLite otherwise (quick local runs).
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER"),
            "PASSWORD": env("POSTGRES_PASSWORD"),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "device-list"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = env("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# Celery: tasks that run the wall-* tools. The broker is Redis.
CELERY_BROKER_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# wall-scan: how the worker runs it.
WALL_SCAN_COMMAND = env("WALL_SCAN_COMMAND", "wall-scan")
WALL_SCAN_PRIVILEGED = env_bool("WALL_SCAN_PRIVILEGED")
WALL_SCAN_TIMEOUT_S = int(env("WALL_SCAN_TIMEOUT_S", "600"))
WALL_DEFAULT_TARGETS = env("WALL_DEFAULT_TARGETS", "")

# wall-healthcheck: monitoring of devices marked "monitored", started by Celery beat.
WALL_HEALTHCHECK_COMMAND = env("WALL_HEALTHCHECK_COMMAND", "wall-healthcheck")
WALL_HEALTHCHECK_INTERVAL_S = int(env("WALL_HEALTHCHECK_INTERVAL_S", "60"))
WALL_HEALTHCHECK_ATTEMPTS = int(env("WALL_HEALTHCHECK_ATTEMPTS", "3"))
WALL_HEALTHCHECK_TIMEOUT_MS = int(env("WALL_HEALTHCHECK_TIMEOUT_MS", "1000"))
# Consecutive failed checks before a device counts as down and an alert is sent.
WALL_ALERT_AFTER_FAILURES = int(env("WALL_ALERT_AFTER_FAILURES", "2"))
WALL_ALERT_EMAILS = env_list("WALL_ALERT_EMAILS")
# Base URL of the hub, for links in alert emails, e.g. http://192.168.1.10:8000
WALL_HUB_URL = env("WALL_HUB_URL", "")

# Warranty and licence reminders: days before the date, and the hour (in TIME_ZONE).
WALL_EXPIRY_REMINDER_DAYS = [int(d) for d in env_list("WALL_EXPIRY_REMINDER_DAYS", "30,7,1,0")]
WALL_EXPIRY_REMINDER_HOUR = int(env("WALL_EXPIRY_REMINDER_HOUR", "8"))

CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "healthchecks": {
        "task": "inventory.tasks.run_healthchecks",
        "schedule": WALL_HEALTHCHECK_INTERVAL_S,
        # A run still queued when the next is due is dropped, so a backlog
        # cannot build up while no worker is running.
        "options": {"expires": WALL_HEALTHCHECK_INTERVAL_S},
    },
    "expiry-reminders": {
        "task": "inventory.tasks.send_expiry_reminders",
        "schedule": crontab(hour=WALL_EXPIRY_REMINDER_HOUR, minute=0),
    },
}

# Email for alerts: SMTP when EMAIL_HOST is set, otherwise printed to the log.
EMAIL_HOST = env("EMAIL_HOST", "")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(env("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
    EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
    EMAIL_TIMEOUT = 15
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "wall-hub@localhost")
