"""Integration-only provider. Records real attempt starts in Redis."""

import os
from threading import Event
from django.conf import settings
from mailjobs.limiter import redis_client
from mailjobs.providers import TransientFailure


def send(job):
    r = redis_client()
    prefix = settings.EMAIL_LIMIT_KEY
    script = r.register_script(
        "local t=redis.call('TIME'); return redis.call('XADD',KEYS[1],'*','job',ARGV[1],'ms',tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000))"
    )
    script(keys=[prefix + ":events"], args=[str(job.pk)])
    n = r.incr(prefix + ":calls:" + str(job.pk))
    if job.recipient == "retry@example.test" and n == 1:
        raise TransientFailure("intentional")
    if job.recipient == "crash@example.test" and n == 1:
        r.set(prefix + ":crash_pid", os.getpid())
        Event().wait(120)
