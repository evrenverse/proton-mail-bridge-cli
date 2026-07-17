# Commands

Global flags go **before** the group: `pmb --json --account <val> <group> <command>`.

## account

- `pmb account add` — interactive wizard (endpoint + email/password, login test)
- `pmb account add-raw --email E --password P [--alias A]` — non-interactive
- `pmb account list` — all configured accounts
- `pmb account remove <value> [--yes]` 🟡
- `pmb account set-default <value>`
- `pmb --json account info [--account V|all]` — shows real folder names/special-use map
- `pmb --json account test [--account V|all]` — login test

## bridge

- `pmb --json bridge status` — bridge reachability and host resolution
- `pmb --json bridge doctor` — connectivity diagnosis (WSL/macOS/Linux) including detected
  TLS modes (`imap_security`/`smtp_security`) and a fix hint on mismatch
- `pmb bridge config [--host H --imap-port N --smtp-port N --security S --smtp-security S]`
  — `--smtp-security` separately, because the macOS Bridge often uses `ssl` for SMTP

## mailbox

- `pmb --json mailbox list` — all folders (with message count/UNSEEN)
- `pmb --json mailbox info <folder>`
- `pmb --json --account A mailbox create <name>` — create folder/label; Proton: `Folders/<name>` or `Labels/<name>`

## message

`list`/`search` return **newest first**.

- `pmb --json message list [--folder F --limit N --offset N --unread --since YYYY-MM-DD]`
- `pmb --json message search [--from A --to A --cc A --subject S --text T --since D --before D --seen/--unseen --flagged --larger BYTES --smaller BYTES --header Key:Value --folder F --with-body --with-attachments --has-attachments --limit N --all-folders --ids-only --count-only]`
  - `--ids-only`: only `account/folder/uid/message_id` per hit — token-efficient for search→move/delete pipelines
  - `--count-only`: exact server-side count without fetching messages (ignores `--limit`; not combinable with `--text`/`--header`/`--has-attachments`/`--all-folders`/non-ASCII values)
- `pmb --json message read --uid 1,2,3 [--folder F --format text|html|both|raw --include-headers]`
- `pmb --json message raw --uid U [--folder F --output PATH]`
- `pmb --json --account A message move --uid U --to DEST [--folder F --yes]` 🟡
- `pmb --json --account A message copy --uid U --to DEST [--folder F]`
- `pmb --json --account A message flag --uid U [--add F --remove F --folder F --yes]`
- `pmb --json --account A message mark --uid U --read|--unread [--folder F]`
- `pmb --json --account A message delete --uid U [--folder F --expunge --yes]` 🟡/🔴

## compose

- `pmb --json --account A compose send --to A --subject S [--cc A --bcc A --body T --body-file F --html-file F --attach PATH --from E --dry-run --yes]` 🟡
- `pmb --json --account A compose reply --uid U [--folder F --all --body T --attach PATH --dry-run --yes]` 🟡
- `pmb --json --account A compose forward --uid U --to A [--folder F --body T --dry-run --yes]` 🟡
- `pmb --json --account A compose draft --to A --subject S [--folder F --body T --attach PATH]` 🟢

## attachment

`--folder` must match the folder the UIDs came from (UIDs are unique per account+folder).

- `pmb --json attachment list --uid U [--folder F]`
- `pmb --json attachment download --uid U [--name N --index I --all] --dir D [--folder F]`
- `pmb --json attachment extract --uid U --name N [--folder F]`

## meta / skill

- `pmb --json describe <group> <command>` — command metadata (options, description)
- `pmb --json fields message|folder|attachment` — JSON shape documentation
- `pmb skill install --agent claude|codex [--dest PATH]` — copy skill files into the agent location
