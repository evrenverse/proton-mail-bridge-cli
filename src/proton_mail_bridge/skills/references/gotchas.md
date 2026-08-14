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
the Proton web settings) and is **read-only**: `move`/`delete`/`flag`/`mark` with
`--folder "All Mail"` are refused with `{"error": {"type": "read_only", …}}` — resolved via the
`\All` special-use flag, so the localized name is caught too.

It is also a **duplicate view**: every hit there also lives in a real folder. Deleting "via All
Mail" is therefore impossible by design — work per folder. `message search --all-folders`,
`bulk-move` and `bulk-delete` all skip All Mail and name it in `skipped_folders`, so their UIDs
are usable for writes. (The Bridge does not list folders in a stable order, so without that
skip it would be luck which folder a deduplicated hit came from.)

Since `search` defaults to All Mail, its results carry `folder: "All Mail"`. Passing that
straight into a write operation is the trap the guard catches.

## Search

- Headers (`--from/--to/--cc/--subject`) and dates (`--since/--before`) run server-side.
- **Body (`--text`) and non-ASCII/umlauts** are unreliable server-side (Gluon IMAP) →
  the CLI filters client-side (fetches bodies). Narrow large mailboxes with `--folder`/`--since`.
- **`--limit` counts matches, not fetched messages.** With a client-side criterion the search
  pages through the scope until it has that many hits or the scope is exhausted. That is
  correct but not free: on a large mailbox a `--text` search reads a lot of bodies. Header-only
  criteria (`--header`, `--list-unsubscribe`) scan with `BODY.PEEK[HEADER]` and only fetch the
  hits in full.
- **Read `search.truncated`.** `reason: "limit"` = more matches exist (raise `--limit`, `0` =
  all); `reason: "fetch_budget"` = `--max-fetch` ran out. Nothing is ever cut silently.

## List-Unsubscribe is not a synonym for advertising

The RFC 2369 header (plus RFC 8058 one-click) is the standard bulk-sender signal and drives
Proton's own unsubscribe button — but project boards, portals, banks and service providers set
it on notifications you cannot afford to lose. `--list-unsubscribe` narrows a selection; the
decision stays with the human.

## IMAP capabilities

The Bridge offers IDLE, MOVE, UIDPLUS — **no QUOTA, SORT, THREAD, CONDSTORE**.
Sorting/threading happens client-side; `pmb --json account info` shows **no** quota.

## Sending

- The Bridge stores sent mail in the Sent folder **itself** — do **not** additionally save it
  via IMAP APPEND (that duplicates Sent).
- **From address**: every address of your own Proton account works, even with the Bridge in
  **combined-addresses mode** (one login covers all addresses). Configure them once via
  `pmb account identity discover --save` (fills in email/name; it never invents labels — add
  one via `account identity add --label`), then select with `--identity <address>` (or
  `<label>` once one is set).
- Foreign addresses (e.g. SimpleLogin aliases) are **not** allowed → the Bridge answers with
  "Invalid Return Path".
- **`MAIL FROM` is no validation**: the Bridge answers `250 … Roger, accepting mail from <…>`
  for *any* address, including addresses that do not exist. The check happens at send time.
  That is why identities are discovered from the Sent folder instead of probed via SMTP.

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

Gluon returns the UID **after** the literal, in the next element of the FETCH response:

```
(b'2 (FLAGS (\Seen) BODY[HEADER.FIELDS (...)] {2}', b'\r\n')
b' UID 3)'
```

Anything scanning only the leading part for `UID (\d+)` finds nothing and loses every UID
silently. `imap_tools` reads both places; the CLI never parses FETCH responses itself. A test
pins this, because an upgrade could break it without a single error message.
