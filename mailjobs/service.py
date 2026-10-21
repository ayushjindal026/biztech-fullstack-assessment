from django.core.validators import validate_email
from django.db import transaction
from .models import EmailJob


def enqueue(recipient, subject, body, job_id=None):
    """Caller can wrap this in the business transaction. UUID is the dedup key."""
    validate_email(recipient)
    from .tasks import deliver

    with transaction.atomic():
        kwargs = {"id": job_id} if job_id else {}
        if job_id:
            job, _ = EmailJob.objects.get_or_create(
                **kwargs,
                defaults={"recipient": recipient, "subject": subject, "body": body}
            )
            if (job.recipient, job.subject, job.body) != (recipient, subject, body):
                raise ValueError("job identifier already used for different content")
        else:
            job = EmailJob.objects.create(
                recipient=recipient, subject=subject, body=body
            )
        # Robust hook: a publish outage leaves a durable pending row for recovery.
        transaction.on_commit(lambda: deliver.delay(str(job.pk)), robust=True)
    return job
