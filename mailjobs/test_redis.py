import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from .limiter import SlidingWindow, redis_client

pytestmark = pytest.mark.integration


@pytest.fixture
def redis():
    if os.environ.get("RUN_REDIS_TESTS") != "1":
        pytest.skip("set RUN_REDIS_TESTS=1 with a real Redis server")
    client = redis_client()
    client.ping()
    return client


def test_atomic_concurrent_workers(redis):
    key = "assessment-test:" + uuid.uuid4().hex
    limiter = SlidingWindow(redis, key, 20, 1000)
    try:
        with ThreadPoolExecutor(max_workers=32) as pool:
            results = list(pool.map(lambda _: limiter.acquire(), range(100)))
        tokens = [token for token, _ in results if token]
        assert len(tokens) == 20
        Event().wait(1.1)
        assert limiter.acquire()[0] is None  # active slots survive the window
        # Complete one call: twenty sequential round trips can outlast a short
        # window on Docker Desktop. Retained membership is checked directly too.
        limiter.finish(tokens[0])
        assert redis.zscore(key, tokens[0]) != float("inf")
        assert redis.zcard(key) == 20
        assert limiter.acquire()[0] is None
        Event().wait(1.1)
        assert limiter.acquire()[0] is not None
    finally:
        redis.delete(key)
