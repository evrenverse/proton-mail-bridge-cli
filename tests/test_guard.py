from __future__ import annotations

import pytest

from proton_mail_bridge.core import guard


def test_free_passes_without_prompt():
    guard.enforce("message read", guard.FREE, assume_yes=False, isatty=lambda: False)  # kein Raise


def test_confirm_blocked_without_tty():
    with pytest.raises(SystemExit):
        guard.enforce("message move", guard.CONFIRM, assume_yes=False, isatty=lambda: False)


def test_confirm_bypassed_with_yes():
    # kein Raise
    guard.enforce("message move", guard.CONFIRM, assume_yes=True, isatty=lambda: False)


def test_critical_ignores_yes_and_needs_token():
    with pytest.raises(SystemExit):
        guard.enforce("message delete", guard.CRITICAL, assume_yes=True, isatty=lambda: False)


def test_escalate_bulk():
    assert guard.escalate(guard.CONFIRM, count=25, threshold=20) == guard.CRITICAL
    assert guard.escalate(guard.CONFIRM, count=5, threshold=20) == guard.CONFIRM


def test_critical_tty_wrong_token_aborts():
    with pytest.raises(SystemExit):
        guard.enforce("message delete", guard.CRITICAL, assume_yes=False,
                      isatty=lambda: True, tokener=lambda p: "wrong")


def test_critical_tty_correct_token_passes():
    # korrektes Token (Default "confirm") → kein Raise
    guard.enforce("message delete", guard.CRITICAL, assume_yes=False,
                  isatty=lambda: True, tokener=lambda p: "confirm")


def test_unknown_risk_fails_closed():
    with pytest.raises(ValueError):
        guard.enforce("x", "bogus", assume_yes=True, isatty=lambda: True)
