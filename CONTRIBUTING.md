# Contributing

## Dev setup
```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q
uv run ruff check . && uv run mypy src
```

## Architecture
- Click-independent core (`core/connection.py`, `core/imap.py`, `core/smtp.py`, `core/config.py`,
  `core/guard.py`); commands are thin wrappers.
- Tests mock IMAP/SMTP via `tests/conftest.py` (FakeMailBox) and a fake SMTP — no real server needed.
- Bulk-first: new commands should handle multiple objects per invocation.

## Conventions
- `from __future__ import annotations` in every file; the core never imports `click`.
- Commits without AI attribution trailers.
