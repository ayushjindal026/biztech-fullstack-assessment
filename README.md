# Biz-Tech Analytics assessment

A small Django orders API and durable Celery email queue. The default email provider logs acceptance without sending mail. The HTTP adapter implements one JSON gateway attempt per invocation; it requires a compatible gateway. All delivery claims below refer to the simulated provider unless explicitly stated.

## Quick start

Prerequisites: Docker Engine/Desktop running and Compose v2. From the repository root:

```sh
docker compose up --build -d
docker compose exec web python manage.py seed_orders
docker compose exec web python manage.py profile_orders
docker compose exec web python -m pytest -q
# Optional: copy newly generated profiler evidence out of the container
docker compose cp web:/app/evidence/silk-profile.json ./evidence/silk-profile.json
```

The `init` service runs migrations before web, worker and beat start. If the seed command races startup, wait for `docker compose logs web` to show the server listening and repeat. A fresh-volume Docker setup has been verified; see `evidence/STATUS.md` for measured time and cache conditions. Cold image/download duration remains network dependent. Submit jobs after startup completes.

If ports 8000 or 6379 are occupied, add `WEB_PORT=18000` and `REDIS_PORT=16379` to an ignored `.env` file before startup. Compose reads these host-port overrides; internal service addresses stay unchanged. On this verified Windows machine, the application is at [localhost:18000](http://localhost:18000/api/orders/summary/) and Redis is bound to localhost:16379. Default links below assume the default ports.

Open [optimized summary](http://localhost:8000/api/orders/summary/), [broken reproduction](http://localhost:8000/api/orders/summary/broken/), and [Silk](http://localhost:8000/silk/). These are local demonstration endpoints, capped at 300 orders. There is no customer authentication or tenant isolation. Never expose this server or Silk publicly: it records SQL. The seed command replaces only the demo orders, lines, customers and products; do not run it against valuable data.

```sh
docker compose exec web python manage.py submit_emails --count 500
docker compose logs -f worker
docker compose exec web python manage.py shell -c "from mailjobs.models import EmailJob; from django.db.models import Count; print(list(EmailJob.objects.values('status').annotate(total=Count('id'))))"
docker compose exec web python manage.py recover_emails
```

A full production-limit run takes more than two minutes for 500 attempts. Redis uses AOF and a persistent volume; PostgreSQL stores durable jobs and dead letters. `docker compose down` keeps data; `docker compose down -v` deletes it.

## Verification

```sh
# Real Redis atomicity and concurrent callers, not an emulator
docker compose exec -e RUN_REDIS_TESTS=1 web python -m pytest -q
# Fast mode: 20 attempts/second, two independent Celery processes, 500 jobs, worker SIGKILL,
# retry accounting, and every rolling window checked against attempt events.
# Uses a generated test-only PostgreSQL database and unique Redis queue/key namespace.
docker compose exec web python -m scripts.verify_queue --postgres
# Separate real 200 / 60,000 ms verification (allow about 3 minutes)
docker compose exec web python -m scripts.verify_queue --postgres --production
```

`--postgres` creates and drops only a uniquely generated verification database; application rows and Docker volumes are preserved. Omitting the flag retains the portable temporary SQLite mode for native development. PostgreSQL verification requires a role with CREATEDB permission, provided by the local Compose setup.

Do not run both queue verifications in the same process. They create subprocess workers, simulate provider acceptance, kill one worker inside the provider call, and reconcile durable jobs. The script restores progress through the same `recover()` task used by beat. It records attempt start timestamps using Redis `TIME`, checks all windows `(t-window,t]`, verifies 500 terminal successes and 502 invocations (one transient retry and one crash replay), and checks the uncertain attempt. These are integration checks, not throughput benchmarks. Dedicated tests cover permanent errors and exhaustion. Test scripts use timed waits to observe completion; limiter and application code never sleep for throttling.

For native development (Python 3.12):

```sh
python -m venv .venv
# POSIX: . .venv/bin/activate ; Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python manage.py migrate
python manage.py seed_orders
python -m pytest -q
python manage.py profile_orders
python manage.py runserver
```

Local ORM checks use SQLite. A running Redis is required only for integration tests and queue work; set `REDIS_URL` accordingly. Linux is the supported Celery worker platform. `requirements.txt` pins direct dependencies; `requirements.lock` pins the resolved dependency graph, and Docker installs the lock file.

## Evidence and status

`evidence/silk-profile.json` contains actual Silk request IDs, timestamps, SQL and counts; regenerate with `profile_orders` after seeding. This exports profiler data rather than screenshots. View the matching request in Silk on the database where it was generated. A fresh database generates new IDs. Silk also runs EXPLAIN and persists profiler rows; the recorded 1,501 versus 2 counts refer to application statements, not total profiler overhead. No latency claim is made.

See `evidence/STATUS.md` for actual checks, environments and limitations. Queue JSON files, when present, contain raw attempt events and assertions from successful runs. Failed verification raises an exception and does not create a success JSON. No live provider credentials or delivery test is included. The optional screen recording has not been produced.

## Configuration

Compose provides local demo database credentials, not production credentials. `.env.example` contains placeholders; `.env` is ignored and is not required. Database/service values are explicit and do not automatically consume `.env.example`. Compose does read `WEB_PORT` and `REDIS_PORT` from `.env` or the shell for host bindings. Configure production secrets through your deployment's secret injection. `DJANGO_SECRET_KEY`, `DEBUG`, `DB_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `REDIS_URL`, and `EMAIL_PROVIDER` are environment settings.

To connect a compatible JSON gateway, set `EMAIL_PROVIDER=mailjobs.providers.http_provider`, `EMAIL_PROVIDER_URL`, and `EMAIL_PROVIDER_TOKEN` on the worker. The gateway must honor `Idempotency-Key` to suppress ambiguous duplicates. Do not enable gateway client retries or redirects: every outbound send must acquire a separate slot. All workers for the provider account must share the same `EMAIL_LIMIT_KEY`, Redis instance and production settings `EMAIL_LIMIT=200`, `EMAIL_WINDOW_MS=60000`. Changing limits while calls are in flight is unsupported. Test overrides must never be deployed to production.

## Windows build context

Keep `.runtime/`, `.venv/`, `.pytest_cache/` and `.git/` excluded in `.dockerignore`. `.gitignore` does not control Docker's build context. The workspace-local WSL Redis runtime contains Linux symlink reparse points (`IO_REPARSE_TAG_LX_SYMLINK`), which the Windows Docker client cannot archive and reports as `archive/tar: unknown file mode ?rwxr-xr-x`. Excluding `.runtime/` fixes the context without changing or deleting those files. Excluding only pytest caches fixes the earlier access-denied error but leaves the symlink error. See `evidence/docker/context-probe-before.log` for an isolated reproduction.
