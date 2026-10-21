import uuid
from unittest.mock import patch
import pytest
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from redis.exceptions import ConnectionError
from .models import EmailJob, DeadLetter, SendAttempt
from .providers import TransientFailure, PermanentFailure
from .service import enqueue
from .tasks import process, backoff, recover

pytestmark = pytest.mark.django_db


@pytest.fixture
def job():
    return EmailJob.objects.create(
        recipient="a@example.test", subject="Subject", body="Body"
    )


@pytest.fixture
def limiter():
    with patch("mailjobs.tasks.SlidingWindow") as factory:
        factory.return_value.acquire.side_effect = lambda: (str(uuid.uuid4()), 0)
        yield factory.return_value


def test_success_and_duplicate(job, limiter):
    with patch("mailjobs.tasks.import_string") as provider:
        assert process(job.pk) is None
        assert process(job.pk) is None
        assert provider.return_value.call_count == 1
    job.refresh_from_db()
    assert job.status == "sent"
    assert job.attempts.get().outcome == "accepted"
    limiter.finish.assert_called_once()


def test_deferrals_do_not_spend_failure_budget(job, limiter):
    limiter.acquire.side_effect = None
    limiter.acquire.return_value = (None, 100)
    with patch("mailjobs.tasks.import_string") as provider:
        assert process(job.pk) >= 0.1
        provider.assert_not_called()
    job.refresh_from_db()
    assert (job.failures, job.deferrals, job.attempts.count()) == (0, 1, 0)


def test_redis_outage_fails_closed(job, limiter):
    limiter.acquire.side_effect = ConnectionError()
    assert process(job.pk) == 5
    job.refresh_from_db()
    assert job.status == "pending"
    assert job.failures == 0
    assert not job.attempts.exists()


def test_transient_then_success(job, limiter):
    with patch("mailjobs.tasks.import_string") as provider:
        provider.return_value.side_effect = TransientFailure()
        assert 2 <= process(job.pk) <= 3
        job.refresh_from_db()
        assert job.failures == 1
        EmailJob.objects.filter(pk=job.pk).update(due_at=timezone.now())
        provider.return_value.side_effect = None
        assert process(job.pk) is None
    job.refresh_from_db()
    assert job.status == "sent"
    assert job.attempts.count() == 2


@pytest.mark.parametrize("permanent", [True, False])
def test_dead_letter(job, limiter, permanent):
    if not permanent:
        EmailJob.objects.filter(pk=job.pk).update(failures=4)
    with patch("mailjobs.tasks.import_string") as provider:
        provider.return_value.side_effect = (
            PermanentFailure() if permanent else TransientFailure()
        )
        assert process(job.pk) is None
    job.refresh_from_db()
    assert job.status == "dead"
    assert DeadLetter.objects.filter(job=job).exists()


def test_backoff_bounds():
    for n in range(1, 12):
        assert min(300, 2**n) <= backoff(n) <= min(300, 2**n) + 1


def test_expired_lease_recovered(job):
    EmailJob.objects.filter(pk=job.pk).update(
        status="processing", lease_until=timezone.now() - timedelta(seconds=1)
    )
    with patch("mailjobs.tasks.deliver.delay") as publish:
        recover()
        publish.assert_called_once_with(str(job.pk))


def test_enqueue_deduplicates_and_rollback():
    key = uuid.uuid4()
    with patch("mailjobs.tasks.deliver.delay"):
        one = enqueue("a@example.test", "Subject", "Body", key)
        two = enqueue("a@example.test", "Subject", "Body", key)
        assert one.pk == two.pk
        with pytest.raises(ValueError):
            enqueue("a@example.test", "Different", "Body", key)
        with pytest.raises(RuntimeError), transaction.atomic():
            enqueue("b@example.test", "Subject", "Body")
            raise RuntimeError()
    assert EmailJob.objects.count() == 1


def test_active_lease_not_claimed(job, limiter):
    EmailJob.objects.filter(pk=job.pk).update(
        status="processing", lease_until=timezone.now() + timedelta(seconds=30)
    )
    assert process(job.pk) is None
    limiter.acquire.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_publish_outage_preserves_durable_outbox():
    with patch(
        "mailjobs.tasks.deliver.delay", side_effect=ConnectionError("broker down")
    ):
        pending = enqueue("outbox@example.test", "Subject", "Body")
    assert EmailJob.objects.get(pk=pending.pk).status == "pending"
    with patch("mailjobs.tasks.deliver.delay") as publish:
        recover()
        publish.assert_called_once_with(str(pending.pk))
