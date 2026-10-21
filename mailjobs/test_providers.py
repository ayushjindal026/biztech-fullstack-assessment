from types import SimpleNamespace
from unittest.mock import patch
import pytest
import requests
from .providers import http_provider, TransientFailure, PermanentFailure


@pytest.mark.parametrize(
    "code, expected",
    [
        (202, None),
        (429, TransientFailure),
        (503, TransientFailure),
        (400, PermanentFailure),
        (302, PermanentFailure),
    ],
)
def test_http_adapter_single_attempt(monkeypatch, code, expected):
    monkeypatch.setenv("EMAIL_PROVIDER_URL", "https://gateway.example.test/send")
    monkeypatch.setenv("EMAIL_PROVIDER_TOKEN", "test-placeholder")
    job = SimpleNamespace(
        pk="durable-id", recipient="a@example.test", subject="Subject", body="Body"
    )
    with patch(
        "mailjobs.providers.requests.post",
        return_value=SimpleNamespace(status_code=code),
    ) as post:
        if expected:
            with pytest.raises(expected):
                http_provider(job)
        else:
            http_provider(job)
        post.assert_called_once()
        assert post.call_args.kwargs["allow_redirects"] is False
        assert post.call_args.kwargs["headers"]["Idempotency-Key"] == "durable-id"
        assert post.call_args.kwargs["timeout"] == (3, 10)


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
def test_transport_errors_are_transient(monkeypatch, error):
    monkeypatch.setenv("EMAIL_PROVIDER_URL", "https://gateway.example.test/send")
    monkeypatch.setenv("EMAIL_PROVIDER_TOKEN", "test-placeholder")
    job = SimpleNamespace(
        pk="durable-id", recipient="a@example.test", subject="Subject", body="Body"
    )
    with patch("mailjobs.providers.requests.post", side_effect=error), pytest.raises(
        TransientFailure
    ):
        http_provider(job)
