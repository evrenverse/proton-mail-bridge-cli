# Security Policy

## Credential handling
- The **bridge password** (≠ your Proton account password) lives in the config file; on POSIX it
  is protected with `chmod 600`. On Windows, `PROTON_BRIDGE_USER`/`PROTON_BRIDGE_PASS` as
  environment variables are the safe path.
- Create bridge credentials least-privilege; the CLI cannot hard-protect against a compromised
  agent that holds a valid bridge password.

## TLS
- Against the **self-signed bridge certificate**, an unverified context is used by default
  (loopback/trusted host). To harden this, pin a certificate exported via the Bridge's
  `cert export` using `tls_cert_path` in the config file.

## Write protection
- Write operations are risk-tiered: 🟢 free · 🟡 confirm (`--yes`) · 🔴 critical (terminal
  only). Every write operation is logged to `~/.local/state/proton-mail-bridge/audit.jsonl`.

## Reporting
Please report vulnerabilities privately via a **GitHub Security Advisory** — do not open a
public issue.
