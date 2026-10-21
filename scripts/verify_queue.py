"""Real Redis + two independent Celery processes; isolated disposable SQLite or PostgreSQL DB.
Run: python -m scripts.verify_queue [--production] [--postgres]
No fake Redis, eager tasks or throttle sleeps. Provider is explicitly simulated.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import Event


def wait_for(predicate, timeout, label):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        Event().wait(0.05)  # test observation only; never used for throttling
    raise AssertionError("Timed out: " + label)


@contextmanager
def isolated_database(directory, postgres):
    if not postgres:
        os.environ.pop("DB_HOST", None)
        os.environ["SQLITE_PATH"] = str(Path(directory) / "queue.sqlite3")
        yield
        return
    if not os.environ.get("DB_HOST"):
        raise ValueError("--postgres requires DB_HOST and PostgreSQL credentials")
    import psycopg
    from psycopg import sql

    original = os.environ.get("POSTGRES_DB", "assessment")
    # Only this generated test database is created/dropped. Application DB is untouched.
    name = "assessment_verify_" + uuid.uuid4().hex
    with psycopg.connect(
        host=os.environ["DB_HOST"],
        dbname=original,
        user=os.environ.get("POSTGRES_USER", "assessment"),
        password=os.environ.get("POSTGRES_PASSWORD", "local-development-only"),
        autocommit=True,
    ) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        os.environ["POSTGRES_DB"] = name
        try:
            yield
        finally:
            from django.db import connections

            connections.close_all()
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
            os.environ["POSTGRES_DB"] = original


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Use a generated test-only PostgreSQL database",
    )
    args = parser.parse_args()
    window = 60000 if args.production else 1000
    limit = 200 if args.production else 20
    prefix = "assessment-test:" + uuid.uuid4().hex
    workers = []
    with tempfile.TemporaryDirectory(
        prefix="assessment-"
    ) as directory, isolated_database(directory, args.postgres):
        os.environ.update(
            DJANGO_SETTINGS_MODULE="config.settings",
            EMAIL_PROVIDER="scripts.queue_provider.send",
            EMAIL_LIMIT_KEY=prefix,
            EMAIL_QUEUE=prefix + ":queue",
            EMAIL_LIMIT=str(limit),
            EMAIL_WINDOW_MS=str(window),
            EMAIL_LEASE_SECONDS="3",
        )
        import django

        django.setup()
        from django.core.management import call_command
        from django.db import connection
        from mailjobs.limiter import redis_client
        from mailjobs.models import EmailJob, SendAttempt, DeadLetter
        from mailjobs.service import enqueue
        from mailjobs.tasks import recover

        r = redis_client()
        r.ping()  # fail loudly when real Redis unavailable
        call_command("migrate", verbosity=0)
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA journal_mode=WAL")

        def start_worker(index):
            log = open(Path(directory) / f"worker-{index}.log", "w")
            p = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "celery",
                    "-A",
                    "config",
                    "worker",
                    "--pool=solo",
                    "--concurrency=1",
                    "--loglevel=WARNING",
                    "--without-gossip",
                    "--without-mingle",
                    "--without-heartbeat",
                    "-Q",
                    prefix + ":queue",
                    "-n",
                    f"test{index}@%h",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            workers.append((p, log))

        start_worker(0)
        start_worker(1)
        started = time.monotonic()
        try:
            # Kill the entire worker after its provider call has begun.
            crash = enqueue("crash@example.test", "Assessment", "Body")
            wait_for(
                lambda: r.get(prefix + ":crash_pid"), 30, "worker entered provider"
            )
            pid = int(r.get(prefix + ":crash_pid"))
            os.kill(pid, signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL)
            for i in range(499):
                enqueue(
                    "retry@example.test" if i == 0 else f"user{i}@example.test",
                    "Assessment",
                    "Body",
                )
            start_worker(2)
            deadline = time.monotonic() + (240 if args.production else 90)
            next_recovery = 0
            while EmailJob.objects.filter(status="sent").count() < 500:
                assert time.monotonic() < deadline, "500 jobs did not finish"
                if time.monotonic() >= next_recovery:
                    recover()
                    next_recovery = time.monotonic() + 2
                Event().wait(0.1)
            rows = r.xrange(prefix + ":events")
            timestamps = [int(fields[b"ms"]) for _, fields in rows]
            left = 0
            peak = 0
            for right, stamp in enumerate(timestamps):
                while timestamps[left] <= stamp - window:
                    left += 1
                peak = max(peak, right - left + 1)
            assert peak <= limit, (peak, window)
            assert len(rows) == 502, len(
                rows
            )  # 500 + transient retry + crash redelivery
            assert EmailJob.objects.count() == 500
            assert EmailJob.objects.filter(status="sent").count() == 500
            assert not DeadLetter.objects.exists()
            retry = EmailJob.objects.get(recipient="retry@example.test")
            assert retry.failures == 1 and retry.attempts.count() == 2
            assert SendAttempt.objects.filter(outcome="uncertain").count() == 1
            result = {
                "mode": "production" if args.production else "fast",
                "database": connection.vendor,
                "redis_version": r.info("server")["redis_version"],
                "window_ms": window,
                "limit": limit,
                "jobs": 500,
                "provider_attempts": len(rows),
                "max_rolling_attempts": peak,
                "sent": 500,
                "intentional_transient_failures": 1,
                "killed_worker_recovered": True,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "events": [
                    {
                        "stream_id": stream.decode(),
                        "job": fields[b"job"].decode(),
                        "ms": int(fields[b"ms"]),
                    }
                    for stream, fields in rows
                ],
            }
            Path("evidence").mkdir(exist_ok=True)
            output = Path("evidence") / (
                ("queue-production" if args.production else "queue-fast")
                + ("-postgres" if args.postgres else "")
                + ".json"
            )
            output.write_text(json.dumps(result, indent=2))
            print(
                json.dumps({k: v for k, v in result.items() if k != "events"}, indent=2)
            )
        finally:
            for p, log in workers:
                if p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait()
                log.close()
            # Preserve logs even on failure before disposable DB removal.
            Path("evidence").mkdir(exist_ok=True)
            for logfile in Path(directory).glob("worker-*.log"):
                (
                    Path("evidence")
                    / (
                        "worker-"
                        + ("production" if args.production else "fast")
                        + ("-postgres" if args.postgres else "")
                        + "-"
                        + logfile.name.removeprefix("worker-")
                    )
                ).write_bytes(logfile.read_bytes())
            keys = list(r.scan_iter(prefix + "*"))
            if keys:
                r.delete(*keys)


if __name__ == "__main__":
    main()
