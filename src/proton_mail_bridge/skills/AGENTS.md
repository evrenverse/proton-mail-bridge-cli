# proton-mail-bridge — agent guide

Agent-native CLI for Proton Mail Bridge (IMAP/SMTP). Command: `proton-mail-bridge` / `pmb`.

## Install & setup

```bash
uv tool install git+https://github.com/evrenverse/proton-mail-bridge-cli
pmb account add   # wizard: host/ports + email + bridge password, tests the login
```

## Usage

- **Always `--json`**. Bulk-first (one task = 1–3 calls). Token-efficient:
  `message search --ids-only` (pipelines) and `--count-only` (count questions).
- **Multi-account fan-out**: without `--account`, `message search`/`list` cover all accounts
  (results tagged with `account`). Sending uses `default_account`/the only account,
  otherwise `--account`/`--from`.
- **Sender identity**: `--identity <label|address>` picks the sender address (and thereby the
  account); `account list` shows all identities. `reply`/`forward` default to the address the
  original was sent to.
- **Search folder-smart**: no `--folder` → `All Mail`; "sent" → `--folder Sent`;
  "received" → `--folder INBOX`. Names are localized → `pmb --json account info` shows the map.
- **`--limit` bounds the matches**, not the fetch: a client-side criterion (`--text`,
  `--header`, `--has-attachments`, `--list-unsubscribe`, umlauts) keeps reading until the
  limit is met or the scope is exhausted. Every result carries a `search` block
  (`candidates`, `scanned`, `truncated`, `reason`) — **check `truncated` before acting on it**.
  `--limit 0` = all matches, `--max-fetch N` caps the scan.
- **Follow-up ops**: pass `account` + `folder` + `uid` through from the search result
  (UIDs are unique per account+folder). `All Mail` is read-only: writes there are refused
  (`type: "read_only"`) — work per folder or use `message bulk-move`/`bulk-delete`.
- **Cleaning up**: `message senders` ranks who sends the most (headers only);
  `message bulk-move --dest F` / `message bulk-delete` select by the same criteria as `search`
  and run folder by folder (`--dest`, because `--to` stays the recipient filter);
  `delete --log FILE` records what a permanent delete removed.
- **Discovery**: `pmb --help`, `pmb <group> --help`, `pmb --json describe <path...>`
  (e.g. `describe account identity add`), `pmb --json fields message`.
- **Writes** (move/copy/flag/mark/delete, folder create, send/reply/forward/draft, attachment
  download): `--dry-run` first, never pass `--yes` on your own.

## Protection layer

🟢 free · 🟡 confirm (`--yes`) · 🔴 critical (`delete --expunge`, bulk ≥ 20 — terminal only)

`--dry-run` sits before all three: every writing command has it, it changes nothing (headers via
`BODY.PEEK`, so not even `\Seen`) and needs no confirmation — the only way to inspect a 🔴
operation. UID ops return `count`, `risk`, `missing_uids` and one entry per message
(uid/date/from/subject/size/flags). Read-only commands have no `--dry-run`; `account identity
discover` has none either — without `--save` it already is the preview.

## Error format

`{"ok": false, "error": {"type": "...", "title": "...", "detail": "..."}}` (exit ≠ 0)

## Gotchas

- Body/text search is filtered client-side; `date` is ISO-8601 with offset; self-signed TLS (unverified).
- macOS: Bridge SMTP is often in SSL mode → `bridge config --smtp-security ssl` (autodetected by `account add`).
- WSL→Windows: 127.0.0.1 → Windows-host fallback; diagnosis `pmb bridge doctor`.
- Labels: the same mail can live in INBOX + Labels/X + All Mail (same Message-ID, different UIDs).
- `List-Unsubscribe` marks bulk senders, **not** advertising: project and portal notifications
  set it too. A selection criterion, never an automatic delete recommendation.

Full reference: `references/commands.md` | Workflows: `references/workflows.md` |
Details: `references/gotchas.md` | Long form of this guide: `references/SKILL.md`
