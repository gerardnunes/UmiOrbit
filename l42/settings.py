
"""Configurações do sistema de gestão operacional do L42."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# =========================================================
# SEGURANÇA E AMBIENTE
# =========================================================

DEBUG = os.environ.get("DJANGO_DEBUG", "1").strip() == "1"

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-inseguro-troque-em-producao",
)

if not DEBUG and SECRET_KEY == "dev-inseguro-troque-em-producao":
    raise ImproperlyConfigured(
        "Configure DJANGO_SECRET_KEY no ambiente de produção."
    )

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1",
    ).split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "DJANGO_CSRF_ORIGINS", ""
    ).split(",")
    if origin.strip()
]

# =========================================================
# APLICATIVOS
# =========================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "storages",
    "operacao.apps.OperacaoConfig",
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

ROOT_URLCONF = "l42.urls"

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
                "operacao.context_processors.contexto",
            ],
        },
    },
]

WSGI_APPLICATION = "l42.wsgi.application"

# =========================================================
# BANCO DE DADOS
# Mantém SQLite para desenvolvimento local.
# =========================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# =========================================================
# AWS S3 — ARQUIVOS ENVIADOS PELO SISTEMA
# Ativado quando AWS_STORAGE_BUCKET_NAME está configurado.
# =========================================================

AWS_STORAGE_BUCKET_NAME = os.environ.get(
    "AWS_STORAGE_BUCKET_NAME", ""
).strip()

AWS_S3_REGION_NAME = os.environ.get(
    "AWS_S3_REGION_NAME", ""
).strip()

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

AWS_S3_CUSTOM_DOMAIN = os.environ.get(
    "AWS_S3_CUSTOM_DOMAIN", ""
).strip() or None

AWS_S3_ENDPOINT_URL = os.environ.get(
    "AWS_S3_ENDPOINT_URL", ""
).strip() or None

USE_S3 = bool(AWS_STORAGE_BUCKET_NAME)

if USE_S3 and not AWS_S3_REGION_NAME:
    raise ImproperlyConfigured(
        "Configure AWS_S3_REGION_NAME para o bucket S3."
    )

if USE_S3:
    # Arquivos privados por padrão; URLs assinadas para acesso.
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True
    AWS_QUERYSTRING_EXPIRE = 3600
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }

# =========================================================
# IDIOMA E FUSO HORÁRIO
# =========================================================

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# =========================================================
# ARQUIVOS ESTÁTICOS E MÍDIA
# CSS/JS: WhiteNoise.
# Uploads: S3 quando configurado; disco local caso contrário.
# =========================================================

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": (
            "storages.backends.s3.S3Storage"
            if USE_S3
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if not DEBUG
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}

# =========================================================
# AUTENTICAÇÃO E SESSÕES
# =========================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
