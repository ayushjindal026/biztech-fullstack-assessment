import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "local-development-only-not-for-deployment"
)
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver", "web"]
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "silk",
    "orders",
    "mailjobs",
]
MIDDLEWARE = ["silk.middleware.SilkyMiddleware"]
ROOT_URLCONF = "config.urls"
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": 30},
    }
}
if os.environ.get("DB_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ["DB_HOST"],
            "NAME": os.environ.get("POSTGRES_DB", "assessment"),
            "USER": os.environ.get("POSTGRES_USER", "assessment"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "local-development-only"),
            "PORT": "5432",
        }
    }
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
CELERY_VISIBILITY_TIMEOUT = 3600
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_BEAT_SCHEDULE = {"recover": {"task": "mailjobs.tasks.recover", "schedule": 30.0}}
EMAIL_LIMIT = int(os.environ.get("EMAIL_LIMIT", "200"))
EMAIL_WINDOW_MS = int(os.environ.get("EMAIL_WINDOW_MS", "60000"))
EMAIL_LIMIT_KEY = os.environ.get("EMAIL_LIMIT_KEY", "email:provider:global")
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "mailjobs.providers.console_provider")
SILKY_PYTHON_PROFILER = False
TEMPLATES = [
    {"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}
]
SILKY_ANALYZE_QUERIES = False

EMAIL_LEASE_SECONDS = int(os.environ.get("EMAIL_LEASE_SECONDS", "45"))
CELERY_TASK_DEFAULT_QUEUE = os.environ.get("EMAIL_QUEUE", "celery")
