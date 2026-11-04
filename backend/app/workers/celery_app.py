"""Celery application. Run with: uv run celery -A app.workers.celery_app worker -B -l info

The beat schedule is empty in Phase 1. Phase 5 adds (docs/02-technical-spec.md §7):
  nightly-run          nightly_run_task(run_date)  23:30 IST daily
  approval-deadlines   approval_deadline_task()    every 15 minutes
"""

from typing import Any

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("retailpilot", broker=settings.redis_url, backend=settings.redis_url)

BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    "nightly-run": {
        "task": "nightly_run_task",
        "schedule": crontab(hour=23, minute=30),
    },
    "approval-deadlines": {
        "task": "approval_deadline_task",
        "schedule": 900.0,  # every 15 minutes
    },
    "partition-maintenance": {
        "task": "partition_maintenance_task",
        "schedule": crontab(hour=0, minute=0),
    },
}

celery_app.conf.update(
    timezone=settings.app_timezone,
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    beat_schedule=BEAT_SCHEDULE,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.workers"])

# `celery -A app.workers.celery_app` looks for an attribute named `app` or `celery`.
app = celery_app
