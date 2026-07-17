# Changelog

## 0.1.0 (2026-07-17)
- Initial release: account/bridge/mailbox/message/compose/attachment groups, multi-account
  fan-out, write guard (🟢/🟡/🔴), skill files for Claude & Codex, discovery (`describe`/`fields`).
- Connectivity: WSL→Windows fallback, socket timeouts, separate TLS modes `security` (IMAP) and
  `smtp_security` (the macOS Bridge often runs SMTP in SSL mode) with banner autodetection in
  `account add`/`bridge doctor`.
- Agent contract: JSON output including errors (usage and unexpected errors too),
  `search --ids-only/--count-only/--has-attachments`, `mailbox create`.
