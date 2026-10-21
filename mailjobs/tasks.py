import logging
import random
import uuid
from datetime import timedelta
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q, F
from django.utils import timezone
from django.utils.module_loading import import_string
from redis.exceptions import RedisError
from .limiter import SlidingWindow
from .models import EmailJob, SendAttempt, DeadLetter
from .providers import PermanentFailure

log = logging.getLogger(__name__)
MAX_FAILURES = 5
LEASE_SECONDS = settings.EMAIL_LEASE_SECONDS


def backoff(failures):
    return min(300, 2**failures) + random.uniform(0, 1)


def available(now):
    return Q(status="pending", due_at__lte=now) | Q(
        status="processing", lease_until__lte=now
    )


def process(job_id):
    """Return countdown for deferral/failure, or None for terminal/busy/not due."""
    now = timezone.now()
    owner = uuid.uuid4()
    claimed = (
        EmailJob.objects.filter(pk=job_id)
        .filter(available(now))
        .update(
            status="processing",
            lease_token=owner,
            lease_until=now + timedelta(seconds=LEASE_SECONDS),
        )
    )
    if not claimed:
        return None
    job = EmailJob.objects.get(pk=job_id)
    owned = EmailJob.objects.filter(pk=job_id, lease_token=owner, status="processing")
    limiter = SlidingWindow()
    try:
        slot, wait_ms = limiter.acquire()
    except RedisError:
        owned.update(
            status="pending",
            due_at=timezone.now() + timedelta(seconds=5),
            last_error="Redis unavailable; no provider call",
        )
        return 5
    if slot is None:
        delay = wait_ms / 1000 + random.uniform(0.01, 0.1)
        owned.update(
            status="pending",
            due_at=timezone.now() + timedelta(seconds=delay),
            deferrals=F("deferrals") + 1,
        )
        return delay
    try:
        # Written before external IO: a crash leaves an explicit uncertain attempt.
        attempt = SendAttempt.objects.create(id=slot, job=job)
        try:
            import_string(settings.EMAIL_PROVIDER)(job)
        except Exception as exc:
            failures = job.failures + 1
            terminal = isinstance(exc, PermanentFailure) or failures >= MAX_FAILURES
            delay = backoff(failures)
            # Store type only: provider errors can contain recipient/credential data.
            reason = type(exc).__name__
            with transaction.atomic():
                updated = owned.update(
                    status="dead" if terminal else "pending",
                    failures=failures,
                    last_error=reason,
                    due_at=timezone.now() + timedelta(seconds=delay),
                )
                if updated and terminal:
                    DeadLetter.objects.get_or_create(
                        job=job, defaults={"reason": reason}
                    )
                SendAttempt.objects.filter(pk=attempt.pk).update(
                    outcome="permanent" if terminal else "transient"
                )
            return None if terminal else delay
        else:
            with transaction.atomic():
                owned.update(status="sent", last_error="")
                SendAttempt.objects.filter(pk=attempt.pk).update(outcome="accepted")
            return None
    finally:
        # Retain slot for a full window AFTER completion. Redis loss fails closed.
        try:
            limiter.finish(slot)
        except RedisError:
            log.exception(
                "Slot remains active; operator reconciliation required slot=%s", slot
            )


@shared_task(bind=True, max_retries=None)
def deliver(self, job_id):
    delay = process(job_id)
    if delay is not None:
        # Celery retry count is NOT the durable provider failure budget.
        raise self.retry(countdown=delay, max_retries=None)


@shared_task
def recover():
    now = timezone.now()
    # Database outbox repairs commit/publish gaps and expired execution leases.
    ids = (
        EmailJob.objects.filter(available(now))
        .order_by("due_at")
        .values_list("pk", flat=True)[:2000]
    )
    for job_id in ids:
        deliver.delay(str(job_id))
