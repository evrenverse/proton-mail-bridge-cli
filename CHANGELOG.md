# Changelog

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
