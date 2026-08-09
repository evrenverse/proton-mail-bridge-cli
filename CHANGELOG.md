# Changelog

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
