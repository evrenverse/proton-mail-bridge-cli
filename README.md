# proton-mail-bridge-cli

[![CI](https://github.com/codename-cn/proton-mail-bridge-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/codename-cn/proton-mail-bridge-cli/actions/workflows/ci.yml)

> Unofficial, agent-native CLI for **Proton Mail Bridge** — search, read, send, and organize
> mail through the local IMAP/SMTP gateway. Multi-account, JSON output for AI agents, robust
> from WSL against a Windows-hosted bridge. Not operated by Proton.

## Quickstart

```bash
uv tool install git+https://github.com/codename-cn/proton-mail-bridge-cli
pmb account add            # wizard: host/ports + email + bridge password, tests the login
pmb --json message search --text "invoice" --since 2026-01-01 --with-body
```

Proton Mail Bridge must be running. The **bridge password** (≠ your Proton password) is shown
in the Bridge under `info`. Short alias: `pmb` = `proton-mail-bridge`.

## For AI agents

You can hand this block to an agent as-is ("here's the repo, install it"):

```bash
# 1. Install (requires uv: https://docs.astral.sh/uv/)
uv tool install git+https://github.com/codename-cn/proton-mail-bridge-cli
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
4. **Discovery**: `pmb --help`, `pmb describe <group> <command>`, `pmb fields message`.
5. **Write operations**: never pass `--yes` on your own; show `--dry-run` before `send`.

## Configuration

Env vars (`PROTON_BRIDGE_HOST/IMAP_PORT/SMTP_PORT/USER/PASS/ACCOUNT`) or a config file
(`~/.config/proton-mail-bridge/config.toml`, Windows `%APPDATA%`). Template: `config.example.toml`.

**macOS:** the Bridge often runs SMTP in SSL mode (IMAP stays STARTTLS). `pmb account add`
detects this automatically; after the fact: `pmb bridge config --smtp-security ssl`
(diagnosis: `pmb bridge doctor`).

## WSL → Windows bridge

`127.0.0.1` is tried first (works with WSL in *mirrored networking mode*, native macOS,
Windows, and Linux without any special path). If that fails inside WSL, the CLI automatically
probes the Windows host IP (gateway/nameserver). Diagnosis: `pmb bridge doctor`.

## Security

Write operations are risk-tiered (🟢/🟡/🔴). TLS against the self-signed bridge certificate is
unverified by default (loopback/trusted host); pin it via `tls_cert_path` in the config file.
See `SECURITY.md`.

## Status & license

Unofficial community client, **not** operated by Proton. Apache-2.0.
