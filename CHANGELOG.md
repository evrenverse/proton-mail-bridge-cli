# Changelog

## Unreleased
- **`message search` can look at attachments.** `--attachment-name` matches the filename,
  `--attachment-text` the text inside a PDF. `--text` only ever read the mail body, so a
  receipt forwarded as a bare attachment — no telling subject, nothing in the body — could
  not be found at all, and a search that came back empty looked like an answer. Searching by
  invoice number, amount or customer number now works, because those live in the document.
  `--attachment-text` fetches and parses every PDF in scope (~10 messages/second): narrow it
  with `--folder`/`--since` or cap it with `--max-fetch`. It reads the text layer only —
  scanned documents are images and stay invisible, there is no OCR.
- **Fix: `message search --limit` bounded the fetch, not the matches.** Client-side criteria
  (`--text`, `--header`, `--has-attachments`, non-ASCII values) ran *after* the limit had cut
  the fetch, so the same search returned 7 hits at `--limit 50`, 21 at `--limit 200` and 111
  at `--limit 2000` — every answer plausible, incomplete, and silent about it. The search now
  takes the server-side match set once and pages through it, filtering while it reads, until
  the limit is met or the scope is exhausted.
- Every `message search` result carries a `search` block next to `items`: `candidates`,
  `scanned`, `truncated`, `reason` (`limit`/`fetch_budget`), `limit`, `folders`. `items` keeps
  its shape. `--limit 0` returns all matches; `--max-fetch N` caps the scan and reports the
  exhausted budget instead of cutting silently.
- The scan reads `BODY.PEEK[HEADER]` whenever the criteria need neither body nor attachments
  and fetches only the hits in full, so header searches stay usable on large mailboxes.
  `--count-only` now rejects *every* client-side criterion through the predicate itself instead
  of an enumerated flag list; `--header` searches no longer return bodies nobody asked for.
- `message bulk-move --dest F` and `message bulk-delete [--expunge]`: same selection options as
  `search`, executed folder by folder, one entry per folder (`count`, `uids`, and in the dry run
  every message). All Mail, the destination, and Trash on a soft delete are skipped and named in
  `skipped_folders`. The guard sees the total: ≥ 20 or `--expunge` is 🔴.
- `message senders`: count, display name, last date and last subject per From address, ranked by
  count, headers only. `--min-count`, `--limit` (top N), `--max-fetch`, plus `senders_total`, so
  a top-N never reads as the whole list.
- Writes to `All Mail` (`move`/`copy`/`flag`/`mark`/`delete`, and both move/copy destinations)
  are refused with `type: "read_only"` and a pointer to working folder by folder. The folder is
  recognized by its `\All` special-use flag, so localized names are caught too.
- `message delete --log FILE` / `bulk-delete --log FILE`: one JSON line per message (`ts`,
  `action`, `account`, `folder`, `uid`, `date`, `from`, `subject`), written before the delete.
  Without it the only record of a permanently deleted message is its absence.
- `message search --attachment-name S` matches a case-insensitive substring of an attachment
  filename. `--text` reads bodies only, so a document forwarded as a bare attachment was
  invisible to every other criterion; PDF *contents* remain out of reach.
- `--max-fetch` holds exactly: the budget used to be checked only between fetch rounds, so
  `--max-fetch 50` scanned 200. The last round now takes only what the budget has room for.
- Message summaries gained `list_unsubscribe` (RFC 2369 targets split into `http`/`mailto`, plus
  the RFC 8058 `one_click` flag) and `from_name`. `message search --list-unsubscribe` filters on
  it — a selection criterion, never an automatic delete recommendation: project and portal
  notifications set the header too.
- Fix: `skill install --agent codex` now ships the long-form guide as `references/SKILL.md`
  (linked from the AGENTS.md footer) instead of only `AGENTS.md` + references.

## 0.3.0 (2026-08-14)
- `--dry-run` on every writing command (previously only `compose send/reply/forward`):
  `message move/copy/flag/mark/delete`, `mailbox create`, `compose draft`,
  `attachment download`, `account add/add-raw/remove/set-default`,
  `account identity add/remove/set-default`, `bridge config`, `skill install`.
  The command resolves the whole operation, prints it, and executes nothing.
- Uniform payload `{"dry_run": true, "action": "<group> <command>", …}`. UID operations report
  `account`, `folder`, `risk`, `count`, `missing_uids` and one entry per message
  (uid/date/from/subject/size/flags) — headers via `BODY.PEEK`, so a preview never sets `\Seen`.
- A dry run needs no `--yes` and no terminal: it is the way to inspect a 🔴 operation
  (`delete --expunge`, bulk ≥ 20) before a human runs it.
- `attachment download --dry-run` lists target paths including `overwrites` and does not create
  the target directory; `skill install --dry-run` lists the files it would overwrite.
- No `--dry-run` for read-only commands; `account identity discover` keeps none, because without
  `--save` it already is the preview.
- The existing `compose` dry runs gained `action`/`risk` (and `cc`/`bcc`/`attachments` on
  `send`); existing keys are unchanged.
- Fix: `pmb <group> --help` (and every nested `--help`) exited 1 and, under `--json`, appended
  a bogus error object to the help text. `click.exceptions.Exit` inherits from `RuntimeError`
  and was swallowed by the catch-all — on the very path the skill documents for discovery.

## 0.2.0 (2026-08-09)
- Multiple sender identities per account: `account identity add/remove/set-default/discover`,
  `--identity <label|address>` on `compose send/reply/forward/draft`. One login in the Bridge's
  combined-addresses mode can send from every address of the Proton account.
- `reply`/`forward` answer from the address the original mail was sent to; `--identity` overrides.
- Fix: `reply --all` now filters *every* own address out of To/Cc, not just the login address.
- Unknown identities are rejected locally; "Invalid Return Path" from the Bridge is mapped to an
  actionable error.
- `account list` reports `identities` and `default_identity` per account.
- `describe` now walks nested command groups (`describe account identity add`) and lists a
  group's commands when given a group.
- Docs: the claim that multiple senders require split-addresses mode was wrong and is corrected.

## 0.1.0 (2026-07-17)
- Initial release: account/bridge/mailbox/message/compose/attachment groups, multi-account
  fan-out, write guard (🟢/🟡/🔴), skill files for Claude & Codex, discovery (`describe`/`fields`).
- Connectivity: WSL→Windows fallback, socket timeouts, separate TLS modes `security` (IMAP) and
  `smtp_security` (the macOS Bridge often runs SMTP in SSL mode) with banner autodetection in
  `account add`/`bridge doctor`.
- Agent contract: JSON output including errors (usage and unexpected errors too),
  `search --ids-only/--count-only/--has-attachments`, `mailbox create`.
