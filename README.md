# proton-mail-bridge-cli

[![CI](https://github.com/evrenverse/proton-mail-bridge-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/evrenverse/proton-mail-bridge-cli/actions/workflows/ci.yml)

> Unofficial, agent-native CLI for **Proton Mail Bridge** — search, read, send, and organize
> mail through the local IMAP/SMTP gateway. Multi-account, JSON output for AI agents, robust
> from WSL against a Windows-hosted bridge. Not operated by Proton.

## Quickstart

```bash
uv tool install git+https://github.com/evrenverse/proton-mail-bridge-cli
pmb account add            # wizard: host/ports + email + bridge password, tests the login
pmb --json message search --text "invoice" --since 2026-01-01 --with-body
```

Proton Mail Bridge must be running. The **bridge password** (≠ your Proton password) is shown
in the Bridge under `info`. Short alias: `pmb` = `proton-mail-bridge`.

## For AI agents

You can hand this block to an agent as-is ("here's the repo, install it"):

```bash
# 1. Install (requires uv: https://docs.astral.sh/uv/)
uv tool install git+https://github.com/evrenverse/proton-mail-bridge-cli
# 2. Check connectivity — Proton Mail Bridge must be running
pmb --json bridge doctor
# 3. Set up an account (non-interactive). The bridge password (≠ Proton password)
#    is shown in the Bridge under `info` — ask the human for it, never guess.
pmb account add-raw --email you@proton.me --password '<bridge-password>'
pmb --json account test
# 4. Install the agent skill into the project (docs + workflows for the agent)
pmb skill install --agent claude   # or --agent codex
```

Operating rules (details in the skill):

1. **Always `--json`**, **bulk-first** (one task = 1–3 calls).
2. **Multi-account**: without `--account`, `message search`/`list` fan out over all accounts.
3. **Token-efficient**: `message search --ids-only` (pipelines), `--count-only` (count questions).
4. **Discovery**: `pmb --help`, `pmb describe <path...>` (e.g. `describe account identity add`),
   `pmb fields message`.
5. **Write operations**: `--dry-run` first (every writing command has it), never pass `--yes`
   on your own.
6. **Read `search.truncated`**: `--limit` bounds the matches, and a result that had to stop
   early says so instead of looking complete.

## Cleaning up a mailbox

```bash
pmb --json message senders --min-count 20          # who sends the volume (headers only)
pmb --json message search --list-unsubscribe --limit 0   # everything with an unsubscribe link
pmb --json --account you@proton.me message bulk-delete --all-folders \
    --from newsletter@example.com --dry-run        # preview, one entry per folder
```

`bulk-move --dest F` and `bulk-delete` take the same selection options as `search`, run folder
by folder and skip All Mail (read-only duplicate view). `--log FILE` writes one JSON line per
deleted message — the only record that survives `--expunge`.

`List-Unsubscribe` is a bulk-sender signal, **not** proof of advertising: project boards and
portals set it on notifications that matter. Selection criterion, never an auto-delete rule.

## Configuration

Env vars (`PROTON_BRIDGE_HOST/IMAP_PORT/SMTP_PORT/USER/PASS/ACCOUNT`) or a config file
(`~/.config/proton-mail-bridge/config.toml`, Windows `%APPDATA%`). Template: `config.example.toml`.

**macOS:** the Bridge often runs SMTP in SSL mode (IMAP stays STARTTLS). `pmb account add`
detects this automatically; after the fact: `pmb bridge config --smtp-security ssl`
(diagnosis: `pmb bridge doctor`).

### Multiple sender addresses

A Proton account can own several addresses. With the Bridge in combined-addresses mode a
single login covers all of them:

```bash
pmb --json account identity discover        # preview: senders found in Sent
pmb --json account identity discover --save # write them into the config
pmb account identity set-default kontakt@proton.me  # default sender for this account
pmb --json compose send --identity kontakt@proton.me --to a@x.de --subject S --body B --dry-run
```

`discover` fills in email/name only — it never invents labels. Labels come from
`account identity add --label` (or editing the config file); use the address with
`--identity`/`set-default` otherwise. `reply` and `forward` answer from the address the
original mail was sent to.

## WSL → Windows bridge

`127.0.0.1` is tried first (works with WSL in *mirrored networking mode*, native macOS,
Windows, and Linux without any special path). If that fails inside WSL, the CLI automatically
probes the Windows host IP (gateway/nameserver). Diagnosis: `pmb bridge doctor`.

## Security

Write operations are risk-tiered (🟢/🟡/🔴) and every one of them takes `--dry-run`:

```bash
pmb --json --account you@proton.me message delete --uid 12,13,14 --dry-run
```

The dry run resolves the whole operation and prints it — for UID operations including one entry
per message (uid, date, sender, subject, size, flags), the resulting risk tier, and the UIDs the
folder does not hold — then stops. It changes nothing, not even `\Seen` (headers are fetched
with `BODY.PEEK`), and it needs no confirmation, because there is nothing to confirm. That makes
it the way to inspect a 🔴 operation that would otherwise demand a terminal.

Read-only commands (`search`, `read`, `list`, `mailbox list`, …) have no `--dry-run`; neither
does `account identity discover`, which without `--save` already is the preview.

TLS against the self-signed bridge certificate is unverified by default (loopback/trusted host);
pin it via `tls_cert_path` in the config file. See `SECURITY.md`.

## Status & license

Unofficial community client, **not** operated by Proton. Apache-2.0.
