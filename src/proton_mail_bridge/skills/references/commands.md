# Commands

Global flags go **before** the group: `pmb --json --account <val> <group> <command>`.

## --dry-run

Every command marked `[--dry-run]` below resolves what it would do, prints it, and executes
nothing. Uniform payload: `{"dry_run": true, "action": "<group> <command>", …}`. It never needs
`--yes` and never touches state — UID operations read headers with `BODY.PEEK`, so not even
`\Seen` is set, and file writers do not even create their target directory.

UID operations (`message move/copy/flag/mark/delete`) additionally return:

| field | meaning |
|---|---|
| `account`, `folder` | where the operation would run |
| `risk` | tier the real run would hit — `free`/`confirm`/`critical` (bulk ≥ 20 escalates) |
| `count` | messages actually found |
| `missing_uids` | requested UIDs the folder does not hold (wrong `--folder`, stale UIDs) |
| `messages[]` | `uid`, `folder`, `date`, `from`, `subject`, `size`, `flags` per message |

Commands without the flag change nothing (`search`, `read`, `list`, `mailbox list`,
`attachment list`/`extract`, `bridge status`/`doctor`, `describe`, `fields`).
`account identity discover` has none either: without `--save` it already is the preview.

## account

- `pmb account add [--dry-run]` — interactive wizard (endpoint + email/password, login test)
- `pmb account add-raw --email E --password P [--alias A --dry-run]` — non-interactive
- `pmb account list` — all configured accounts
- `pmb account remove <value> [--yes --dry-run]` 🟡
- `pmb account set-default <value> [--dry-run]`
- `pmb --json account info [--account V|all]` — shows real folder names/special-use map
- `pmb --json account test [--account V|all]` — login test
- `pmb --json --account A account identity add --email E [--name N --label L --dry-run]`
- `pmb --json --account A account identity remove <label|email> [--yes --dry-run]` 🟡
- `pmb --json --account A account identity set-default <label|email> [--dry-run]`
- `pmb --json [--account A] account identity discover [--limit N --save]` — scans the Sent
  folder for sender addresses; fans out over all accounts without `--account`

## bridge

- `pmb --json bridge status` — bridge reachability and host resolution
- `pmb --json bridge doctor` — connectivity diagnosis (WSL/macOS/Linux) including detected
  TLS modes (`imap_security`/`smtp_security`) and a fix hint on mismatch
- `pmb bridge config [--host H --imap-port N --smtp-port N --security S --smtp-security S
  --dry-run]` — `--smtp-security` separately, because the macOS Bridge often uses `ssl` for
  SMTP; without a setter the command only prints the endpoint, so `--dry-run` is a no-op there

## mailbox

- `pmb --json mailbox list` — all folders (with message count/UNSEEN)
- `pmb --json mailbox info <folder>`
- `pmb --json --account A mailbox create <name> [--dry-run]` — create folder/label; Proton: `Folders/<name>` or `Labels/<name>` (dry run reports `exists`)

## message

`list`/`search` return **newest first**.

- `pmb --json message list [--folder F --limit N --offset N --unread --since YYYY-MM-DD]`
- `pmb --json message search [--from A --to A --cc A --subject S --text T --since D --before D --seen/--unseen --flagged --larger BYTES --smaller BYTES --header Key:Value --attachment-name S --attachment-text S --list-unsubscribe --folder F --with-body --with-attachments --has-attachments --limit N --max-fetch N --all-folders --ids-only --count-only]`
  - `--limit` bounds the **matches** (0 = all). Criteria the server cannot decide (`--text`,
    `--header`, `--has-attachments`, `--attachment-name`, `--attachment-text`,
    `--list-unsubscribe`, non-ASCII values) are filtered while the search pages through the
    scope, so the hit count no longer depends on the limit
  - `--max-fetch N`: stop the client-side scan after N fetched messages (0 = no budget)
  - every result carries a `search` block next to `items`: `candidates` (server-side matches in
    scope), `scanned`, `truncated`, `reason` (`limit`/`fetch_budget`), `limit`, `folders`,
    `skipped_folders`. `truncated: true` = the answer is incomplete, and the reason says which
    knob to turn
  - `--all-folders` walks every folder except All Mail (read-only duplicate view, and the
    server does not list folders in a stable order — without the skip it is luck whether the
    UIDs come back writable), deduplicated by Message-ID, asking each folder only for the
    matches still missing
  - `--attachment-name S`: case-insensitive substring of an attachment filename. `--text`
    reads bodies only, so this is the way to find a document that arrived as a bare attachment
  - `--attachment-text S`: substring of the text *inside* a PDF attachment. Fetches and parses
    every PDF in scope (first 50 pages each) — narrow it with `--since`/`--folder`. Scanned
    documents have no text layer and there is no OCR, so they never match: a "not found" after
    this pass has to be reported as "not found in machine-readable PDFs"
  - `--list-unsubscribe`: only messages carrying the RFC 2369 header. A selection criterion,
    **not** a verdict — notifications from project tools and portals set it too
  - `--ids-only`: only `account/folder/uid/message_id` per hit — token-efficient for search→move/delete pipelines
  - `--count-only`: exact count, `--limit` is ignored. Server-side criteria are answered by
    UID SEARCH without fetching a message; a client-side criterion is *scanned* and the count
    comes with `scanned`/`truncated`, so an incomplete count is recognizable as one. Not
    combinable with `--all-folders` (a labelled mail would be counted once per folder) or
    `--ids-only`
- `pmb --json message senders [--folder F --all-folders --since D --before D --seen/--unseen --min-count N --limit N --max-fetch N]`
  — count, display name, `last_date`, `last_subject`, a `list_unsubscribe` hint and `folders`
  per From address, ranked by count. Headers only, no body fetch. `senders` block reports
  `scanned`, `truncated`, `folders`/`skipped_folders` and `senders_total` (how many senders
  the top-N was cut from)
  - `--all-folders` scans every folder except All Mail and deduplicates by Message-ID:
    `count` counts messages, `folders` counts copies, so a labelled mail raises the count
    once while still naming both folders a cleanup has to visit
- `pmb --json message read --uid 1,2,3 [--folder F --format text|html|both|raw --include-headers]`
- `pmb --json message raw --uid U [--folder F --output PATH]`
- `pmb --json --account A message move --uid U --to DEST [--folder F --yes --dry-run]` 🟡
- `pmb --json --account A message copy --uid U --to DEST [--folder F --dry-run]`
- `pmb --json --account A message flag --uid U [--add F --remove F --folder F --yes --dry-run]`
- `pmb --json --account A message mark --uid U --read|--unread [--folder F --dry-run]`
- `pmb --json --account A message delete --uid U [--folder F --expunge --yes --log FILE --dry-run]` 🟡/🔴
  - dry run reports `permanent` (`--expunge`/from Trash) and, for the soft delete, the
    resolved Trash folder as `to`
  - `--log FILE` appends one JSON line per message (`ts`, `action`, `account`, `folder`, `uid`,
    `date`, `from`, `subject`) *before* the delete — the only record that survives `--expunge`
- `message read --mark-read` has no `--dry-run`: reading is PEEK anyway, and simulating the
  flag means leaving `--mark-read` off

### Bulk across folders

Same selection options as `search`; the destination of a bulk move is `--dest`, because `--to`
keeps its search meaning (recipient). Both run the selection per folder and execute per folder.

- `pmb --json --account A message bulk-move --dest F [<selection> --folder F --all-folders --limit N --max-fetch N --yes --dry-run]` 🟡/🔴
- `pmb --json --account A message bulk-delete [<selection> --folder F --all-folders --expunge --limit N --max-fetch N --yes --log FILE --dry-run]` 🟡/🔴

| field | meaning |
|---|---|
| `total` | messages across all folders |
| `folders[]` | per folder: `folder`, `count`, `uids` (dry run additionally `messages[]`) |
| `search.skipped_folders` | folders left out: All Mail (read-only duplicate view), the destination, and Trash on a soft delete |
| `risk` | `confirm`, `critical` from 20 messages on and for `--expunge` |

`--limit` caps the selection **per folder** (0 = every match); `--folder "All Mail"` is
refused. Without `--all-folders` the scope is `--folder` (default INBOX).

## compose

- `pmb --json --account A compose send --to A --subject S [--cc A --bcc A --body T --body-file F --html-file F --attach PATH --from E --identity E --dry-run --yes]` 🟡
- `pmb --json --account A compose reply --uid U [--folder F --all --body T --attach PATH --identity E --dry-run --yes]` 🟡
- `pmb --json --account A compose forward --uid U --to A [--folder F --body T --identity E --dry-run --yes]` 🟡
- `pmb --json --account A compose draft --to A --subject S [--folder F --body T --attach PATH --identity E --dry-run]` 🟢

## attachment

`--folder` must match the folder the UIDs came from (UIDs are unique per account+folder).

- `pmb --json attachment list --uid U [--folder F]`
- `pmb --json attachment download --uid U [--name N --index I --all] --dir D [--folder F --dry-run]`
  — writes files and overwrites silently, so the dry run lists `files[]` (`target`, `exists`)
  and `overwrites[]`, and does not even create `--dir`
- `pmb --json attachment extract --uid U --name N [--folder F]` — stdout only, no `--dry-run`

## meta / skill

- `pmb --json describe <path...>` — command metadata (options, description); walks nested
  groups (`describe account identity add`) and lists a group's commands when given a group
- `pmb --json fields message|folder|attachment` — JSON shape documentation
- `pmb skill install --agent claude|codex [--dest PATH --dry-run]` — copy skill files into the
  agent location; the dry run lists the target files and which of them would be overwritten
