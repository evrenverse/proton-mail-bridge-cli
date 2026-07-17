from __future__ import annotations

import click

from proton_mail_bridge.core import connection
from proton_mail_bridge.core.config import load_config, resolve_config, save_config
from proton_mail_bridge.utils import output as out_mod


@click.group("bridge")
def bridge_group() -> None:
    """Endpoint & diagnostics."""


@bridge_group.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show the resolved host/port + reachability."""
    cfg = resolve_config()
    ep = cfg.endpoint
    try:
        host, source = connection.resolve_host(ep)
        out_mod.out({"reachable": True, "host": host, "source": source,
                     "imap_port": ep.imap_port, "smtp_port": ep.smtp_port, "security": ep.security})
    except Exception as exc:
        out_mod.out({"reachable": False, "detail": str(exc),
                     "imap_port": ep.imap_port, "smtp_port": ep.smtp_port})


@bridge_group.command("doctor")
@click.pass_context
def doctor_cmd(ctx: click.Context) -> None:
    """Full connectivity diagnosis with fix hints."""
    cfg = resolve_config()
    ep = cfg.endpoint
    wsl = connection.detect_wsl()
    report: dict = {"wsl": wsl, "imap_port": ep.imap_port, "smtp_port": ep.smtp_port,
                    "probes": [], "reachable": False, "resolved_host": None}
    hosts = ["127.0.0.1"] + (connection.windows_host_candidates() if wsl else [])
    for host in hosts:
        imap_ok = connection.probe(host, ep.imap_port)
        smtp_ok = connection.probe(host, ep.smtp_port)
        report["probes"].append({"host": host, "imap": imap_ok, "smtp": smtp_ok})
        if imap_ok and smtp_ok and report["resolved_host"] is None:
            report["resolved_host"] = host
            report["reachable"] = True
            report["imap_security"] = connection.detect_security(host, ep.imap_port)
            report["smtp_security"] = connection.detect_security(host, ep.smtp_port)
            effective_smtp = ep.smtp_security or ep.security
            if report["smtp_security"] and report["smtp_security"] != effective_smtp:
                report["hint"] = (
                    f"SMTP port speaks {report['smtp_security']}, config says {effective_smtp}"
                    f" → `proton-mail-bridge bridge config"
                    f" --smtp-security {report['smtp_security']}`"
                )
    if not report["reachable"]:
        report["hint"] = ("Bridge is not running or the ports are wrong. Check `info` in the "
                          "Bridge (host/ports/password) and whether the Windows bridge is "
                          "reachable.")
    out_mod.out(report)


@bridge_group.command("config")
@click.option("--host", default=None)
@click.option("--imap-port", "imap_port", type=int, default=None)
@click.option("--smtp-port", "smtp_port", type=int, default=None)
@click.option("--security", type=click.Choice(["starttls", "ssl"]), default=None)
@click.option("--smtp-security", "smtp_security", type=click.Choice(["starttls", "ssl"]),
              default=None, help="SMTP separately (the macOS Bridge often uses ssl for SMTP).")
@click.pass_context
def config_cmd(ctx: click.Context, host, imap_port, smtp_port, security, smtp_security) -> None:
    """Show or set the endpoint."""
    from proton_mail_bridge.core.config import config_path

    path = config_path()
    cfg = load_config(path)
    changed = False
    for attr, val in (("host", host), ("imap_port", imap_port),
                      ("smtp_port", smtp_port), ("security", security),
                      ("smtp_security", smtp_security)):
        if val is not None:
            setattr(cfg.endpoint, attr, val)
            changed = True
    if changed:
        save_config(cfg, path)
    out_mod.out({"host": cfg.endpoint.host, "imap_port": cfg.endpoint.imap_port,
                 "smtp_port": cfg.endpoint.smtp_port, "security": cfg.endpoint.security,
                 "smtp_security": cfg.endpoint.smtp_security or cfg.endpoint.security})


def register(root: click.Group) -> None:
    root.add_command(bridge_group)
