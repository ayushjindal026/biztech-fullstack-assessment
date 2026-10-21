"""One key for all workers sharing a provider account. Redis errors propagate."""

import uuid
from pathlib import Path
from django.conf import settings
from redis import Redis


def redis_client():
    return Redis.from_url(
        settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
    )


class SlidingWindow:
    def __init__(self, client=None, key=None, limit=None, window_ms=None):
        self.client = client or redis_client()
        self.key = key or settings.EMAIL_LIMIT_KEY
        self.limit = limit if limit is not None else settings.EMAIL_LIMIT
        self.window_ms = (
            window_ms if window_ms is not None else settings.EMAIL_WINDOW_MS
        )
        if self.limit < 1 or self.window_ms < 1:
            raise ValueError("positive limit and window required")
        self.acquire_script = self.client.register_script(
            Path(__file__).with_name("acquire.lua").read_text()
        )
        self.finish_script = self.client.register_script(
            Path(__file__).with_name("finish.lua").read_text()
        )

    def acquire(self):
        token = str(uuid.uuid4())
        granted, wait_ms = self.acquire_script(
            keys=[self.key], args=[self.limit, self.window_ms, token]
        )
        return (token if granted else None), int(wait_ms)

    def finish(self, token):
        self.finish_script(keys=[self.key], args=[token])
