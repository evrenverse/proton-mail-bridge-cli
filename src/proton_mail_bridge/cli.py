from __future__ import annotations

import os

import click
from click_repl import repl as _click_repl

from proton_mail_bridge import __version__
from proton_mail_bridge.core.errors import BridgeError
from proton_mail_bridge.utils import output as out_mod


class _BridgeCli(click.Group):
    def invoke(self, ctx: click.Context):  # type: ignore[override]
        try:
            return super().invoke(ctx)
        except BridgeError as exc:
            out_mod.out_err(exc.type, exc.title, exc.detail)
        except click.UsageError as exc:
            # keep the JSON error contract for wrong flags/subcommands too
            if ctx.obj and ctx.obj.get("as_json"):
                out_mod.out_err("usage", "Invalid invocation", exc.format_message(), exit_code=2)
            raise
        except (click.ClickException, click.Abort):
            raise
        except Exception as exc:
            # contract: agents get JSON, never a raw traceback
            if os.environ.get("PROTON_BRIDGE_DEBUG"):
                raise
            out_mod.out_err("error", type(exc).__name__, str(exc))


@click.group(cls=_BridgeCli, invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.option(
    "--account",
    "account",
    default=None,
    help="Account (email/alias/'all'). Default: fan-out over all for read commands.",
)
@click.version_option(__version__, "--version")
@click.pass_context
def main(ctx: click.Context, as_json: bool, account: str | None) -> None:
    """proton-mail-bridge — agent-native CLI for Proton Mail Bridge."""
    ctx.ensure_object(dict)
    ctx.obj["as_json"] = as_json
    ctx.obj["account"] = account
    out_mod.set_json(as_json)
    if ctx.invoked_subcommand is None:
        click.echo("◆ proton-mail-bridge REPL — 'help' for commands, 'quit' to exit")
        _click_repl(ctx)


def _register() -> None:
    from proton_mail_bridge import meta, skill_install
    from proton_mail_bridge.commands import account, attachment, bridge, compose, mailbox, message

    for module in (account, bridge, mailbox, message, compose, attachment):
        module.register(main)
    meta.register_meta(main)
    skill_install.register_skill(main)


_register()


if __name__ == "__main__":
    main()
