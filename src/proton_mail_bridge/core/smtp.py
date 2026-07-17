from __future__ import annotations

from email.message import EmailMessage
from typing import Any

from proton_mail_bridge.core.config import Account, Endpoint


class SmtpSession:
    """Click-independent SMTP wrapper. One instance = one connection."""

    def __init__(self, smtp: Any):
        self._smtp = smtp

    @classmethod
    def connect(
        cls, endpoint: Endpoint, account: Account, *, host: str | None = None
    ) -> SmtpSession:
        import smtplib

        from proton_mail_bridge.core.connection import resolve_host, tls_context

        host = host or resolve_host(endpoint)[0]
        ctx = tls_context(endpoint)
        if (endpoint.smtp_security or endpoint.security) == "ssl":
            smtp: Any = smtplib.SMTP_SSL(host, endpoint.smtp_port, timeout=endpoint.timeout,
                                         context=ctx)
        else:
            smtp = smtplib.SMTP(host, endpoint.smtp_port, timeout=endpoint.timeout)
            smtp.starttls(context=ctx)
        smtp.login(account.email, account.password)
        return cls(smtp)

    def __enter__(self) -> SmtpSession:
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self._smtp.quit()
        except Exception:
            pass

    def send(self, msg: EmailMessage) -> str:
        self._smtp.send_message(msg)
        return msg["Message-ID"]
