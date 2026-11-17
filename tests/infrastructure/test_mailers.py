import json

import pytest

from src.infrastructure.entrypoint.worker import tasks


class _Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_mailer_defaults_to_smtp_and_picks_resend(monkeypatch):
    monkeypatch.delenv("MAIL_PROVIDER", raising=False)
    assert isinstance(tasks.mailer(), tasks.SMTPMailer)
    monkeypatch.setenv("MAIL_PROVIDER", "resend")
    assert isinstance(tasks.mailer(), tasks.ResendMailer)
    monkeypatch.setenv("MAIL_PROVIDER", "carrier-pigeon")
    with pytest.raises(ValueError):
        tasks.mailer()


def test_resend_posts_the_reset_mail_with_an_idempotency_key(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "Terra <no-reply@example.test>")
    sent = []

    def opener(request, timeout):
        sent.append((request, timeout))
        return _Response(200)

    tasks.ResendMailer(opener).send_reset("eng@example.test", "https://app.test/reset-password#token=t", "m1")

    request, timeout = sent[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://api.resend.com/emails" and request.method == "POST"
    assert request.get_header("Authorization") == "Bearer re_test"
    assert request.get_header("Idempotency-key") == "reset-m1"
    assert payload["from"] == "Terra <no-reply@example.test>" and payload["to"] == ["eng@example.test"]
    assert "https://app.test/reset-password#token=t" in payload["text"] and timeout == 20
    assert 'href="https://app.test/reset-password#token=t"' in payload["html"]


def test_reset_mail_html_escapes_the_link_and_states_the_expiry(monkeypatch):
    monkeypatch.setenv("AUTH_RESET_SECONDS", "1800")
    url = 'https://app.test/reset-password#token=a"b<c'
    html = tasks.reset_html(url)
    assert 'href="https://app.test/reset-password#token=a&quot;b&lt;c"' in html and url not in html
    assert "30 minutos" in html and "30 minutos" in tasks.reset_body(url)


def test_resend_falls_back_to_smtp_from_and_fails_on_error_status(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.delenv("MAIL_FROM", raising=False)
    monkeypatch.setenv("SMTP_FROM", "SPAT <noreply@example.test>")
    seen = []

    def opener(request, timeout):
        seen.append(json.loads(request.data)["from"])
        return _Response(422)

    with pytest.raises(RuntimeError):
        tasks.ResendMailer(opener).send_reset("eng@example.test", "https://app.test/r", "m2")
    assert seen == ["SPAT <noreply@example.test>"]
