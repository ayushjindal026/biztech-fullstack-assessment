"""Adapters must perform exactly ONE network attempt per invocation (no retries)."""

import logging
import os
import requests


class TransientFailure(Exception):
    pass


class PermanentFailure(Exception):
    pass


def console_provider(job):
    # Safe runnable default: no network delivery. Never log email contents.
    logging.getLogger(__name__).info("Simulated email accepted job=%s", job.pk)


def http_provider(job):
    """Generic JSON email gateway; configure endpoint/token outside source control."""
    try:
        response = requests.post(
            os.environ["EMAIL_PROVIDER_URL"],
            json={"to": job.recipient, "subject": job.subject, "body": job.body},
            headers={
                "Authorization": "Bearer " + os.environ["EMAIL_PROVIDER_TOKEN"],
                "Idempotency-Key": str(job.pk),
            },
            timeout=(3, 10),
            allow_redirects=False,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise TransientFailure(type(exc).__name__) from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise TransientFailure(f"HTTP {response.status_code}")
    if not 200 <= response.status_code < 300:
        raise PermanentFailure(f"HTTP {response.status_code}")
