"""
Django settings for the credas_verification project.

All sensitive / environment-specific configuration is loaded from the .env
file via python-dotenv. Nothing secret is hardcoded in this module.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# ─── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from the .env file located at the project root.
load_dotenv(BASE_DIR / ".env")

# ─── Core security settings (from .env) ───────────────────────────────────
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-default-change-me")

# DEBUG comes in as a string from the environment; normalise to a boolean.
DEBUG = os.getenv("DEBUG", "False").strip().lower() in ("1", "true", "yes")

# Comma-separated list of allowed hosts, e.g. "localhost,127.0.0.1".
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "*").split(",")
    if host.strip()
]

# ─── Credas integration settings (from .env) ──────────────────────────────
# These are read by the CredasService; never hardcode them elsewhere.
CREDAS_BASE_URL = os.getenv("CREDAS_BASE_URL")
CREDAS_API_KEY = os.getenv("CREDAS_API_KEY")
CREDAS_JOURNEY_ID = os.getenv("CREDAS_JOURNEY_ID")
CREDAS_ACTOR_ID = os.getenv("CREDAS_ACTOR_ID")
CREDAS_WEBHOOK_URL = os.getenv("CREDAS_WEBHOOK_URL")

# ─── Application definition ────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    # Local
    "verification",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "credas_verification.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "credas_verification.wsgi.application"

# ─── Database ──────────────────────────────────────────────────────────────
# SQLite is used for simplicity; swap to Postgres/MySQL via .env for prod.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ─── Password validation ───────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── Internationalization ──────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ─── Static files ──────────────────────────────────────────────────────────
STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Django REST Framework ─────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# ─── Logging ───────────────────────────────────────────────────────────────
# Logs go to both the console and a rotating-friendly file. Every Credas call,
# DB save, webhook and error is logged via the "verification" logger.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "credas_verification.log",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "verification": {
            "handlers": ["console", "file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}
