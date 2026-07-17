---
name: proton-mail-bridge
description: Use when reading, searching, sending, or organizing Proton Mail via the local Proton Mail Bridge — list/search messages across all accounts, read bodies, download attachments, send/reply/forward, move/delete/flag messages. Provides the `proton-mail-bridge` (alias `pmb`) CLI with JSON output for agents.
---

# proton-mail-bridge

Agent-native CLI for Proton Mail Bridge (local IMAP/SMTP gateway).
Command: `proton-mail-bridge`, short alias `pmb`.

## Setup (once)

```bash
uv tool install git+https://github.com/codename-cn/proton-mail-bridge-cli
pmb account add   # wizard: host/ports + email + bridge password, tests the login
```

The Bridge must be running. Bridge password ≠ Proton account password (shown in the Bridge under `info`).

## Ground rules for agents

- **Always `--json`**: `pmb --json <group> <command>`.
- **Raw-data principle**: the CLI returns structured JSON. Aggregating, summing, matching, and
  analyzing is the agent's job — not the CLI's.
- **Bulk-first**: one task = 1–3 calls. `message search --with-body` fetches many bodies at
  once; `message read --uid 1,2,3`; `attachment download --uid 1,2,3 --all`.
- **Token-efficient**: `message search --ids-only` for move/delete pipelines,
  `--count-only` for pure count questions ("how many unread from X?").
- **Multi-account fan-out**: without `--account`, `message search`/`list` fan out over **all**
  accounts (results tagged with `account`). Pick one account with `--account <email|alias>`.
  Sending uses `default_account`/the only account, otherwise `--account`/`--from`.
- **Search folder-smart**:
  - no `--folder` → `All Mail` (complete view, deduplicated by Message-ID); also contains
    Spam/Trash and is effectively read-only (search/read only)
  - "sent to X" → `--folder Sent`; "received from X" → `--folder INBOX`
  - `--all-folders` deduplicates by Message-ID (useful when the scope is unclear)
  - The logical names `Sent`/`INBOX`/`All Mail` always work; `pmb --json account info` is only
    needed to see the exact (possibly localized) folder name
- **Follow-up ops** (`read`/`move`/`delete`): pass `account` + `folder` + `uid` through from the
  search result. UIDs are unique per account+folder.
- **Discovery**: `pmb --help`, `pmb <group> --help`, `pmb --json describe <group> <command>`,
  `pmb --json fields message`.

## Write operations — protection layer

🟢 free · 🟡 confirm (`--yes` skips) · 🔴 critical (human terminal input only)

- **Never pass `--yes` on your own** — ask the user first.
- 🔴 (`delete --expunge`, bulk delete ≥ 20) requires terminal input.
- Before `send`/`reply`/`forward`, show `--dry-run` first, then send.

## Error format

`{"ok": false, "error": {"type": "...", "title": "...", "detail": "..."}}` (exit ≠ 0)

## Common workflows

- Identify vendors: `pmb --json message search --text "order" --since 2026-01-01 --with-body`
- Collect invoices: `pmb --json message search --folder Sent --to client@x.com --with-attachments`
  then `pmb --json attachment download --uid <ids> --all --dir ./invoices`
- Send mail: `pmb --json compose send --to a@x.com --subject "..." --body "..." --dry-run`
  → review → send without `--dry-run`

## Gotchas

- **Body/text search** is filtered client-side (Gluon IMAP quirks) — narrow large mailboxes
  with `--folder`/`--since`.
- **TLS**: self-signed bridge certificate → unverified context by default. Pin via
  `tls_cert_path` in the config file.
- **macOS**: the Bridge often runs SMTP in SSL mode — `account add` autodetects;
  manually: `pmb bridge config --smtp-security ssl`.
- **WSL→Windows**: `127.0.0.1` first, then automatic Windows-host fallback; diagnosis
  `pmb bridge doctor`.
- Complete list: `references/gotchas.md`

## Full command list

See `references/commands.md`.
