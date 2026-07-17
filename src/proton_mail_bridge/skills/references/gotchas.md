# Gotchas

## Folder taxonomy

- System folders without prefix: `INBOX`, `Sent`, `Drafts`, `Spam`, `Trash`, `Archive`,
  `All Mail`, `Starred`.
- Proton folders: `Folders/<name>`, Proton labels: `Labels/<name>`.
- **Names are localized** — the CLI resolves Sent/Trash/All Mail/… via
  **RFC 6154 special-use flags** (`\Sent \Trash \All …`), not via fixed names.
  `pmb --json account info` shows the map (logical name → real folder name).

## Labels = multiple occurrences → dedup

A labeled mail lives in `INBOX` + `Labels/X` + `All Mail` at the same time
(each with its own UID, same Message-ID). `message search --all-folders` **deduplicates by
Message-ID**; the default scope `All Mail` contains each mail only once.

## All Mail

Best "search everything" view, but by default it **also contains Spam/Trash** (excludable in
the Proton web settings) and is effectively **read-only** — do not use it for moving/deleting.

## Search

- Headers (`--from/--to/--cc/--subject`) and dates (`--since/--before`) run server-side.
- **Body (`--text`) and non-ASCII/umlauts** are unreliable server-side (Gluon IMAP) →
  the CLI filters client-side (fetches bodies). Narrow large mailboxes with `--folder`/`--since`.

## IMAP capabilities

The Bridge offers IDLE, MOVE, UIDPLUS — **no QUOTA, SORT, THREAD, CONDSTORE**.
Sorting/threading happens client-side; `pmb --json account info` shows **no** quota.

## Sending

- The Bridge stores sent mail in the Sent folder **itself** — do **not** additionally save it
  via IMAP APPEND (that duplicates Sent).
- **From address**: only your own account addresses are allowed; foreign/alias addresses
  (e.g. SimpleLogin) → "Invalid Return Path" error. Multiple senders → run the Bridge in
  **split-addresses mode**.

## Limits

Message ≤ **25 MB**; free plan **150 mails/day, 50/h**; ≤ **100 recipients/mail**.
No mass sends.

## Drafts

`compose draft` uses IMAP APPEND with `\Draft`. If that fails, the mail ends up in the
Bridge folder **`Recovered Messages`** (it is not lost).

## Timestamps

`date` is ISO-8601 **with offset** (not necessarily UTC); `date_str` is the original header.

## TLS

Self-signed bridge certificate → unverified context by default. Pin via `tls_cert_path` in the
config file (certificate exported via the Bridge's `cert export`).

## macOS: SMTP often in SSL mode

The macOS Bridge frequently runs SMTP in **SSL mode** while IMAP stays STARTTLS. Symptom with
the wrong setting: the SMTP connect hangs until timeout ("Connection unexpectedly closed").
`pmb account add` detects the mode automatically (banner probe); after the fact:
`pmb bridge doctor` shows the detected modes + a fix hint, set it via
`pmb bridge config --smtp-security ssl`.

## WSL → Windows bridge

Without mirrored networking, WSL cannot reach the Windows `127.0.0.1` — the CLI automatically
probes Windows host candidates (gateway/nameserver). Native macOS/Linux: plain
`127.0.0.1`, no special path. Diagnosis: `pmb bridge doctor`.

## UIDs

UIDs are unique per account+folder → always pass `account` + `folder` + `uid` through from the
search result for follow-up ops.
