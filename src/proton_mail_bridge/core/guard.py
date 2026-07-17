from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

FREE = "free"
CONFIRM = "confirm"
CRITICAL = "critical"

BULK_THRESHOLD = 20


def audit_path() -> Path:
    override = os.environ.get("PROTON_BRIDGE_AUDIT_LOG")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "proton-mail-bridge" / "audit.jsonl"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "proton-mail-bridge" / "audit.jsonl"


def audit(entry: dict[str, Any]) -> None:
    try:
        rec = {"ts": int(time.time()), **entry}
        path = audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def escalate(risk: str, count: int, threshold: int = BULK_THRESHOLD) -> str:
    """Escalate bulk operations to CRITICAL from the threshold on."""
    if risk == CONFIRM and count >= threshold:
        return CRITICAL
    return risk


def _abort(label: str, risk: str, decision: str, msg: str) -> None:
    audit({"label": label, "risk": risk, "decision": decision})
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def enforce(
    label: str,
    risk: str,
    *,
    assume_yes: bool = False,
    isatty: Callable[[], bool] | None = None,
    confirmer: Callable[[str], bool] | None = None,
    tokener: Callable[[str], str] | None = None,
    token: str = "confirm",
) -> None:
    """Enforce the risk tier. Returning = allowed; SystemExit = blocked."""
    isatty = isatty or sys.stdin.isatty

    if risk not in (FREE, CONFIRM, CRITICAL):
        # fail-closed: an unknown/mistyped tier must never slip through silently
        raise ValueError(f"Unknown risk tier: {risk!r}")

    if risk == FREE:
        return

    if risk == CRITICAL:
        if not isatty():
            msg = (
                f"🔴 {label}: critical operation –"
                " terminal confirmation required (no --yes bypass)."
            )
            _abort(label, risk, "blocked_no_tty", msg)
        tokener = tokener or (lambda p: input(p))
        entered = tokener(f"🔴 CRITICAL: {label}. Type '{token}' to confirm: ")
        if (entered or "").strip() != token:
            _abort(label, risk, "aborted", "Aborted (token mismatch).")
        audit({"label": label, "risk": risk, "decision": "critical_confirmed"})
        return

    # CONFIRM
    if assume_yes:
        audit({"label": label, "risk": risk, "decision": "override"})
        return
    if not isatty():
        _abort(
            label, risk, "blocked_no_tty",
            f"🟡 {label}: needs confirmation. Pass --yes to approve deliberately.",
        )
    confirmer = confirmer or (lambda p: input(p).strip().lower() in ("y", "j", "yes", "ja"))
    if confirmer(f"🟡 Run {label}? [y/N] "):
        audit({"label": label, "risk": risk, "decision": "confirmed"})
        return
    _abort(label, risk, "aborted", "Aborted.")
