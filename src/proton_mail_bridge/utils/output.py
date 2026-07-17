from __future__ import annotations

import json
import sys
from typing import Any

import click

_AS_JSON = False


def set_json(flag: bool) -> None:
    global _AS_JSON
    _AS_JSON = bool(flag)


def out(data: Any) -> None:
    """Success output. JSON when enabled, otherwise rich-friendly via click."""
    if _AS_JSON:
        click.echo(json.dumps(data, ensure_ascii=False, default=str))
    else:
        from rich.console import Console

        Console().print(data)


def out_ok(message: str) -> None:
    out({"ok": True, "message": message} if _AS_JSON else message)


def out_err(type: str, title: str, detail: str = "", exit_code: int = 1) -> None:
    """Error output + exit. Fail loudly."""
    payload = {"ok": False, "error": {"type": type, "title": title, "detail": detail}}
    if _AS_JSON:
        click.echo(json.dumps(payload, ensure_ascii=False), err=False)
    else:
        click.echo(f"✖ {title}" + (f" — {detail}" if detail else ""), err=True)
    sys.exit(exit_code)
