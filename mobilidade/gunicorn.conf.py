"""Gunicorn configuration for Cloud Run deployments."""

import multiprocessing
import os


def _int_env(name: str, default: int) -> int:
    """Safely parse integer environment variables with a fallback."""

    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
default_workers = max(1, multiprocessing.cpu_count())
workers = _int_env("WEB_CONCURRENCY", default_workers)
threads = _int_env("GUNICORN_THREADS", 4)
timeout = _int_env("GUNICORN_TIMEOUT", 120)
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")

# Forward access logs to stdout for Cloud Logging aggregation
accesslog = "-"
errorlog = "-"
