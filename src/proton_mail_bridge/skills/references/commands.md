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
- `pmb --json message search [--from A --to A --cc A --subject S --text T --since D --before D --seen/--unseen --flagged --larger BYTES --smaller BYTES --header Key:Value --folder F --with-body --with-attachments --has-attachments --limit N --all-folders --ids-only --count-only]`
  - `--ids-only`: only `account/folder/uid/message_id` per hit — token-efficient for search→move/delete pipelines
  - `--count-only`: exact server-side count without fetching messages (ignores `--limit`; not combinable with `--text`/`--header`/`--has-attachments`/`--all-folders`/non-ASCII values)
- `pmb --json message read --uid 1,2,3 [--folder F --format text|html|both|raw --include-headers]`
- `pmb --json message raw --uid U [--folder F --output PATH]`
- `pmb --json --account A message move --uid U --to DEST [--folder F --yes --dry-run]` 🟡
- `pmb --json --account A message copy --uid U --to DEST [--folder F --dry-run]`
- `pmb --json --account A message flag --uid U [--add F --remove F --folder F --yes --dry-run]`
- `pmb --json --account A message mark --uid U --read|--unread [--folder F --dry-run]`
- `pmb --json --account A message delete --uid U [--folder F --expunge --yes --dry-run]` 🟡/🔴
  - dry run reports `permanent` (`--expunge`/from Trash) and, for the soft delete, the
    resolved Trash folder as `to`
- `message read --mark-read` has no `--dry-run`: reading is PEEK anyway, and simulating the
  flag means leaving `--mark-read` off

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
