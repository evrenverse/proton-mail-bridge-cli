from __future__ import annotations

from proton_mail_bridge.core.smtp import SmtpSession
from proton_mail_bridge.utils import mime


class FakeSMTP:
    def __init__(self):
        self.sent = []
        self.logged_in = None
        self.started_tls = False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)

    def quit(self):
        pass


def test_connect_uses_ssl_when_smtp_security_ssl(monkeypatch):
    """macOS bridge: SMTP often in SSL mode while IMAP stays starttls."""
    import smtplib

    from proton_mail_bridge.core.config import Account, Endpoint

    calls = []

    def fake_ssl(host, port, timeout=None, context=None):
        calls.append(("ssl", host, port, timeout))
        return FakeSMTP()

    def fake_plain(host, port, timeout=None):
        calls.append(("plain", host, port, timeout))
        return FakeSMTP()

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_ssl)
    monkeypatch.setattr(smtplib, "SMTP", fake_plain)
    ep = Endpoint(host="1.2.3.4", security="starttls", smtp_security="ssl")
    SmtpSession.connect(ep, Account("a@p.me", "pw"), host="1.2.3.4")
    assert calls[0][0] == "ssl"  # smtp_security wins over security


def test_send_returns_message_id():
    fake = FakeSMTP()
    msg = mime.build_message(sender="me@p.me", to=["a@x.de"], cc=None, bcc=None,
                             subject="S", body_text="b", body_html=None, attachments=None)
    session = SmtpSession(fake)
    mid = session.send(msg)
    assert fake.sent == [msg]
    assert mid == msg["Message-ID"]


def test_send_maps_invalid_return_path_to_a_bridge_error():
    import smtplib

    import pytest

    from proton_mail_bridge.core.errors import BridgeError

    class RefusingSMTP(FakeSMTP):
        def send_message(self, msg):
            raise smtplib.SMTPSenderRefused(550, b"Invalid Return Path", "fremd@x.de")

    msg = mime.build_message(sender="fremd@x.de", to=["a@x.de"], cc=None, bcc=None,
                             subject="S", body_text="b", body_html=None, attachments=None)
    with pytest.raises(BridgeError) as exc:
        SmtpSession(RefusingSMTP()).send(msg)
    assert exc.value.type == "send"
    assert "identity discover" in exc.value.detail


def test_send_reraises_other_smtp_errors():
    import smtplib

    import pytest

    class BrokenSMTP(FakeSMTP):
        def send_message(self, msg):
            raise smtplib.SMTPServerDisconnected("connection lost")

    msg = mime.build_message(sender="me@p.me", to=["a@x.de"], cc=None, bcc=None,
                             subject="S", body_text="b", body_html=None, attachments=None)
    with pytest.raises(smtplib.SMTPServerDisconnected):
        SmtpSession(BrokenSMTP()).send(msg)
