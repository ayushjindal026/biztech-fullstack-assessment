# Implementation and verification status

Latest verification: 21 October 2026, Docker Desktop on Windows. All three assessment phases are implemented. The Docker/PostgreSQL results below supersede the earlier WSL-only verification limitations. External email delivery is simulated.

## Docker build diagnosis and minimal fixes

The original Windows build was reproduced: context transfer failed with `archive/tar: unknown file mode ?rwxr-xr-x`. `.runtime/` was missing from `.dockerignore`. That local WSL runtime contains Linux symlinks stored as Windows reparse points, including `.runtime/root/usr/bin/redis-server` with tag `0xa000001d` (`IO_REPARSE_TAG_LX_SYMLINK`). An isolated Docker context containing `usr/bin` and `COPY . /` reproduced the same error; this directory has the redis-server symlink. Other symlinks also exist below .runtime. Windows Docker cannot archive these entries. Earlier `.pytest_cache` access-denied output is a separate cache/ACL issue already addressed by the existing ignore patterns.

Added `.runtime/` to the existing `.dockerignore`, preserving the runtime files. Context transfer then succeeded (about 596 KB versus 34.5 MB on the failed attempt). A direct final-image inspection confirms `.runtime`, `.venv`, host `.pytest_cache`, and `.env` were not copied. Pytest may generate a new cache inside a running container.

All four application images (`init`, `web`, `worker`, `beat`) built successfully, including a final rebuild containing the updated test files. Dockerfile and production application logic were unchanged. PostgreSQL/Redis images were pulled and started. Because other projects already bind host ports 8000 and 6379, Compose host bindings now support `WEB_PORT`/`REDIS_PORT`; an ignored local `.env` selects 18000/16379. No other project was stopped.

Source changes are limited to `.dockerignore`, port interpolation in compose.yaml, `.env.example`, README/DESIGN/status documentation, one Redis test timing fix, and an optional PostgreSQL mode in the verification harness. No dependency was added.

Evidence: `docker/context-probe-before.log`, `docker/build.log`, `docker/final-build-startup.log`, `docker/images-final.json`.

## Final container and PostgreSQL verification

| Service | Actual result |
| --- | --- |
| PostgreSQL 16.4 | Running, Docker healthcheck healthy, SQL SELECT and Django connection verified |
| Redis 7.4.1 | Running, Docker healthcheck healthy, real PING and Lua operations verified |
| Django | Running; summary and Silk both HTTP 200 at localhost:18000 |
| Celery worker 5.5.3 | Running with configured prefork concurrency four; inspect ping returned pong |
| Celery Beat | Running; scheduled recovery published a database-only verification job, accepted in one attempt |
| Migration init | Exited successfully with code 0; zero pending migrations |

Runtime: Linux containers, Python 3.12.7, Django 5.2.7, Celery 5.5.3, PostgreSQL 16.4-alpine, Redis 7.4.1-alpine. Web/worker/Beat do not define Docker HEALTHCHECK instructions; their process/HTTP/task checks are recorded separately rather than labelling them Docker-healthy.

First startup used new application volumes and applied all migrations. The final rebuild preserved all 320 seeded orders and the successful Beat verification job (f083d267-8ee7-4341-81a9-73058e8b5e24). No application data or Docker volume was deleted. Tests used Django's isolated test database or generated `assessment_verify_<uuid>` databases. Those test-only databases were disposed after testing; SQL inspection confirmed none remained.

Evidence: `docker/migrations.log`, `docker/migrations-final.log`, `docker/application-smoke.json`, `docker/final-health.json`, `docker/containers-final.jsonl`, `docker/worker-beat.log`.

## Automated tests

Final built image, PostgreSQL backend and real Redis enabled:

```sh
docker compose exec -T -e RUN_REDIS_TESTS=1 web python -m pytest -q --junitxml=/tmp/pytest-final-image.xml
```

**23 passed, 0 failed, 0 skipped in 10.20 seconds.** This comprises 22 unit/ORM tests and one actual Redis concurrency integration test. Unit tests deliberately mock provider/limiter boundaries where appropriate; they are not counted as real Celery executions. The Redis test uses real Lua and 100 concurrent calls across a thread pool and checks active-slot retention and completed-slot expiry. Separate Celery process integration scenarios are below and are not inflated into the pytest count.

The first isolated Docker Redis-test attempt failed because its 100 ms window assumed twenty sequential `finish()` network round trips would complete before an early slot expired. The production limiter correctly allowed a new permit after expiry. The test now completes one slot, checks its retained membership/score, and uses a one-second observation window. Application limiter code was unchanged. The original failure log and XML were retained, followed by two complete successful Docker suite runs (16.27 seconds and final-image 10.20 seconds).

Additional checks passed: Django system checks, migration drift check, pip check, Black formatting check, Compose configuration validation. Default README pytest leaves the Redis integration opt-in: the clean-project run produced 22 passed and one explicit skip; the full command above runs all 23.

Evidence: `docker/tests-postgres.log`, `docker/tests-redis-initial-failure.log`, `docker/pytest-redis-initial-failure.xml`, `docker/tests-final.log`, `docker/tests-final-image.log`, `docker/pytest-final-image.xml`.

## Actual Redis and Celery process integration

Both scenarios ran inside Docker with Redis 7.4.1 and a uniquely generated PostgreSQL database. `--postgres` was added because the original portable harness intentionally forced SQLite even inside Docker. No production application logic changed. Both scenarios launch two independent Celery worker processes and a replacement, use real Redis transport, kill a worker with SIGKILL while inside the simulated provider, and invoke the actual database recovery task.

| Scenario | Jobs sent | Provider invocations | Maximum rolling starts | Retry and crash recovery | Elapsed |
| --- | --- | --- | --- | --- | --- |
| Fast: 20 / 1000 ms | 500 | 502 | 17 | Passed | 58.301 s |
| Production: 200 / 60000 ms | 500 | 502 | 200 | Passed | 138.2 s |

Each 502-attempt total accounts for 500 jobs, one intentional transient retry and one crash replay. Both assert 500 terminal successes, one durable transient failure/retry, one uncertain killed-worker attempt and no lost jobs. Saved raw Redis-TIME start events were independently rechecked locally against every rolling window; both matched their reported maxima and stayed within the configured limit. This is execution evidence, not an external email or throughput benchmark.

The configured application Beat/prefork worker was tested separately by inserting a pending job without calling `.delay()`: Beat recovered it through its scheduled task and the worker accepted it once. Evidence includes the durable UUID and count, not just process startup logs.

Commands:

```sh
docker compose exec -T web python -m scripts.verify_queue --postgres
docker compose exec -T web python -m scripts.verify_queue --postgres --production
```

Evidence: `docker/queue-fast-postgres.json`, `docker/queue-production-postgres.json`, matching .log files and worker-*-postgres-*.log files. Original earlier WSL/SQLite evidence remains at the evidence root for historical comparison.

## Section 1 profiler evidence

Fresh PostgreSQL data: 320 deterministic orders / 960 lines. Genuine Silk export records **1,501 application SQL queries before and 2 after**, with identical payloads asserted by regression tests. Optimized counts remain constant for 1, 50 and 300 orders; the seed repeatability test passes on PostgreSQL. Silk's own EXPLAIN/persistence overhead is excluded from those application-query counts. No latency benchmark or fabricated screenshot is claimed.

Evidence: `docker/silk-profile-postgres.json` (matching request IDs remain in the application database) and `docker/silk-profile-clean-postgres.json` (separate clean project).

## README clean setup

Verified the README sequence (`up --build -d`, seed, profile, pytest) in separate project `biztech-cleanverify-20261021172022` with newly created PostgreSQL and Redis volumes, independent host ports 18001/16380 and cached base/dependency image layers. Startup, HTTP readiness, seeding, profiling and default tests completed in **78.774 seconds**. This verifies a clean data environment under five minutes on this machine; it does not guarantee a fully uncached download/build time on every network. Initial dependency installation also succeeded from the pinned lock during the earlier main build.

The clean project's containers/network were stopped afterward, with both named volumes retained to respect the no-volume-deletion constraint:

- `biztech-cleanverify-20261021172022_postgres`
- `biztech-cleanverify-20261021172022_redis`

The primary stack remains running. Evidence: `docker/clean-setup.json` and clean-*.log files.

## Remaining limitations and submission readiness

The assessment is technically ready for submission based on the implemented sections and successful Docker/PostgreSQL/Redis/Celery checks. Commit/push or sharing a hosted Git repository remains a submission step; no remote repository was created or pushed. The optional recording was not produced.

- Provider acceptance is simulated. Live HTTP gateway credentials, actual recipient delivery and provider Idempotency-Key behavior were not tested. HTTP adapter status/transport handling is unit-tested.
- Crash harnesses use separate solo-pool worker processes and a three-second test lease. They verify whole-worker SIGKILL plus SQL recovery. The main configured prefork worker processes jobs correctly, but prefork child-loss requeue and the full 3,600-second Redis visibility-timeout path were not directly exercised.
- Redis host failover/data loss and provider-side duplicates remain documented limitations. Killed workers retain limiter slots indefinitely, failing closed and potentially reducing capacity; DESIGN describes safe operator reconciliation. Exactly-once delivery is not claimed.
- A fully cold, uncached under-five-minute setup is network dependent and was not timed as a single sequence. The measured clean-volume run used cached layers.
- This is a local assessment server; Django runserver, local demo credentials and unauthenticated demo/Silk endpoints are not a production deployment.
