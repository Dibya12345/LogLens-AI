"""Tests for the Phase 4 security hardening: redaction, SSRF guard, secrets."""

import pytest

from loglens.alerts import SlackAlerter, validate_webhook_url
from loglens.llm.config import LLMConfig
from loglens.redact import redact


class TestRedaction:
    def test_emails_masked(self):
        assert "<email>" in redact("login failed for alice@example.com from 10.0.0.1")
        assert "alice@example.com" not in redact("alice@example.com")

    def test_secrets_masked(self):
        assert "AKIA" not in redact("key AKIAIOSFODNN7EXAMPLE rotated")
        assert redact("password=hunter2").endswith("<redacted>")
        assert "<redacted>" in redact("Authorization: Bearer abcdef0123456789")
        assert "<jwt>" in redact("token eyJhbGciOi.J9eyJzdWIiOi.SflKxwRJSMeKKF2")

    def test_operational_data_kept(self):
        # IPs and hostnames stay — they are useful for RCA and not secrets.
        out = redact("connection refused to 10.0.0.1:5432 on host db-prod-01")
        assert "10.0.0.1" in out and "db-prod-01" in out

    def test_never_raises_on_empty(self):
        assert redact("") == ""


class TestWebhookSSRF:
    def test_rejects_non_http_scheme(self):
        with pytest.raises(ValueError, match="http"):
            validate_webhook_url("file:///etc/passwd")

    def test_rejects_cloud_metadata(self):
        with pytest.raises(ValueError, match="metadata|link-local"):
            validate_webhook_url("http://169.254.169.254/latest/meta-data/")

    def test_allows_normal_https(self):
        url = "https://hooks.slack.com/services/T000/B000/xxxx"
        assert validate_webhook_url(url) == url

    def test_alerter_rejects_bad_url(self):
        with pytest.raises(ValueError):
            SlackAlerter("ftp://evil/webhook")


class TestSecretExposure:
    def test_api_key_not_in_repr(self):
        cfg = LLMConfig(provider="openai", api_key="sk-supersecret", model="gpt-4o-mini")
        assert "sk-supersecret" not in repr(cfg)
        assert cfg.api_key == "sk-supersecret"  # still accessible
