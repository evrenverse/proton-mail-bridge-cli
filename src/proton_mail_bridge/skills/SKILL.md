---
name: proton-mail-bridge
description: Use when reading, searching, sending, or organizing Proton Mail via the local Proton Mail Bridge — list/search messages across all accounts, read bodies, download attachments, send/reply/forward, move/delete/flag messages. Provides the `proton-mail-bridge` (alias `pmb`) CLI with JSON output for agents.
---

# proton-mail-bridge

Agent-native CLI for Proton Mail Bridge (local IMAP/SMTP gateway).
Command: `proton-mail-bridge`, short alias `pmb`.

## Setup (once)

```bash
uv tool install git+https://github.com/evrenverse/proton-mail-bridge-cli
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
  `--count-only` for pure count questions ("how many unread from X?"). A count with a
  client-side criterion scans for its answer and reports `scanned`/`truncated` with it.
- **Multi-account fan-out**: without `--account`, `message search`/`list` fan out over **all**
  accounts (results tagged with `account`). Pick one account with `--account <email|alias>`.
  Sending uses `default_account`/the only account, otherwise `--account`/`--from`.
- **Sender identity**: one Proton account can own several addresses. `pmb --json account list`
  shows them per account (`identities`, `default_identity`). Choose one with
  `--identity <label|address>` — that alone also picks the account. Without it, `send`/`draft`
  use the account's `default_identity`, while `reply`/`forward` answer from the address the
  original mail was sent to. Unknown identities are rejected before any connection is made.
- **Search folder-smart**:
  - no `--folder` → `All Mail` (complete view, deduplicated by Message-ID); also contains
    Spam/Trash and is **read-only** — searching there is right, writing there is refused
  - "sent to X" → `--folder Sent`; "received from X" → `--folder INBOX`
  - `--all-folders` walks every folder *except* All Mail and deduplicates by Message-ID —
    use it when the scope is unclear, and whenever the UIDs have to be writable
  - The logical names `Sent`/`INBOX`/`All Mail` always work; `pmb --json account info` is only
    needed to see the exact (possibly localized) folder name
- **`--limit` bounds the matches, not the fetch.** A search with a client-side criterion
  (`--text`, `--header`, `--has-attachments`, `--list-unsubscribe`, umlauts) keeps reading
  until it has that many hits or the scope is exhausted. Every search result carries a
  `search` block next to `items`:

  ```json
  {"account": "…", "ok": true,
   "search": {"candidates": 4321, "scanned": 4321, "truncated": false, "limit": 50,
              "folders": 1, "skipped_folders": []},
   "items": […]}
  ```

  `truncated: true` means the answer is incomplete — `reason` says why (`limit`: more matches
  exist, raise `--limit` or use `0` for all; `fetch_budget`: `--max-fetch` ran out). **Check
  it before you act on a result**, especially before feeding `--ids-only` into move/delete.
- **Follow-up ops** (`read`/`move`/`delete`): pass `account` + `folder` + `uid` through from the
  search result. UIDs are unique per account+folder. A search without `--folder` returns
  `folder: "All Mail"` — that folder cannot be written to; re-run with `--all-folders` (or a
  concrete folder), or let `message bulk-move`/`bulk-delete` do the folder-wise work.
- **Discovery**: `pmb --help`, `pmb <group> --help`, `pmb --json describe <path...>`
  (e.g. `describe account identity add`), `pmb --json fields message`.

## Write operations — protection layer

🟢 free · 🟡 confirm (`--yes` skips) · 🔴 critical (human terminal input only)

- **Never pass `--yes` on your own** — ask the user first.
- 🔴 (`delete --expunge`, bulk delete ≥ 20) requires terminal input.
- **`--dry-run` sits before all three tiers**: every writing command takes it, it changes
  nothing, and it needs no confirmation — so it also works for 🔴 operations you cannot run
  yourself. Run it first, show the result, then let the user decide.

```bash
pmb --json --account A message delete --uid 12,13,14 --dry-run
{"dry_run": true, "action": "message delete", "account": "…", "folder": "INBOX",
 "risk": "confirm", "count": 3, "missing_uids": ["14"], "permanent": false, "to": "Trash",
 "messages": [{"uid": "12", "folder": "INBOX", "date": "…", "from": "…", "subject": "…",
               "size": 4096, "flags": ["\\Seen"]}, …]}
```

`missing_uids` are UIDs the folder does not hold — usually a wrong `--folder` or a stale UID
list. `risk` is the tier the real run would hit (bulk ≥ 20 escalates 🟡 → 🔴).

No `--dry-run` on read-only commands, and none on `account identity discover` — without
`--save` that command *is* its own preview.

## Cleaning up a mailbox

1. **Who sends the volume**: `pmb --json message senders --min-count 20` — count, last date
   and last subject per sender, headers only. `--all-folders` adds `folders` per sender:
   where the mails actually sit, which is where a cleanup has to go.
2. **Pick a criterion**, e.g. `--from`, `--subject`, `--larger`, `--before`, or
   `--list-unsubscribe` (messages offering an unsubscribe link).
3. **Preview folder by folder**: `pmb --json message bulk-delete --all-folders --from X
   --dry-run` — one entry per folder with `count`, `uids` and every message.
4. **Let the human run it** without `--dry-run`. Bulk ≥ 20 is 🔴 and needs a terminal.
   `--log FILE` writes one JSON line per deleted message — the only record that survives a
   permanent delete.

⚠️ **`List-Unsubscribe` does not mean "advertising".** Project boards, portals and service
providers set the header on business-critical notifications. Use it to narrow a selection and
show the result — never as an automatic reason to delete.

## Error format

`{"ok": false, "error": {"type": "...", "title": "...", "detail": "..."}}` (exit ≠ 0)

## Common workflows

- Identify vendors: `pmb --json message search --text "order" --since 2026-01-01 --with-body`
- Collect invoices: `pmb --json message search --folder Sent --to client@x.com --with-attachments`
  then `pmb --json attachment download --uid <ids> --all --dir ./invoices`
- Hunt a missing document — `--text` reads bodies only, so a receipt forwarded as a bare
  attachment is invisible to it. Two extra passes, cheapest first:
  `pmb --json message search --attachment-name rechnung --since 2026-06-01` (filenames), then
  `pmb --json message search --attachment-text 26593328 --since 2026-06-01` (text inside the
  PDFs). Searching by invoice number, amount or customer number belongs in the second pass —
  those live in the document, not in the mail.
- Send mail: `pmb --json compose send --to a@x.com --subject "..." --body "..." --dry-run`
  → review → send without `--dry-run`
- Clean up in bulk: `message search --ids-only` → `message move --uid <ids> --to Trash --dry-run`
  → check `count`/`missing_uids`/`messages` with the user → run again without `--dry-run`
- Clean up across folders: `message bulk-delete --all-folders --from x@example.com --dry-run`
  → check per folder with the user → run again without `--dry-run` (add `--log`)

## Gotchas

- **Body/text search** is filtered client-side (Gluon IMAP quirks) — narrow large mailboxes
  with `--folder`/`--since`. Client-side criteria scan the scope until the limit is reached,
  so on a 30k mailbox a `--text` search is slow by nature; `--max-fetch N` caps it and says
  so in `search.truncated`.
- **`--text` never sees attachments** — use `--attachment-name` for filenames and
  `--attachment-text` for what is written inside a PDF. `--attachment-text` fetches and
  parses every PDF in scope (~10 messages/second), so narrow it with `--folder`/`--since`
  or cap it with `--max-fetch`. It reads the text layer only: a scanned document is an
  image and stays invisible, there is no OCR. A "nothing found" on a document hunt has to
  say which of the three passes were run.
- **All Mail is read-only** — `move`/`delete`/`flag`/`mark` there are refused with
  `type: "read_only"`. Work per folder.
- **TLS**: self-signed bridge certificate → unverified context by default. Pin via
  `tls_cert_path` in the config file.
- **macOS**: the Bridge often runs SMTP in SSL mode — `account add` autodetects;
  manually: `pmb bridge config --smtp-security ssl`.
- **WSL→Windows**: `127.0.0.1` first, then automatic Windows-host fallback; diagnosis
  `pmb bridge doctor`.
- Complete list: `references/gotchas.md`

## Full command list

See `references/commands.md`.
