from __future__ import annotations

import click

from proton_mail_bridge.utils import output as out_mod

_FIELDS = {
    "message": {
        "summary": [
            "account", "uid", "folder", "message_id", "date", "date_str", "from", "to",
            "cc", "subject", "flags", "size", "has_attachments", "attachment_count", "snippet",
        ],
        "full": ["...summary...", "body_text", "body_html", "headers", "attachments"],
    },
    "folder": {"fields": ["name", "MESSAGES", "UNSEEN", "UIDVALIDITY", "UIDNEXT"]},
    "attachment": {"fields": ["filename", "content_type", "size", "content_id", "inline"]},
}


@click.command("fields")
@click.argument("name", type=click.Choice(["message", "folder", "attachment"]))
@click.pass_context
def fields_cmd(ctx: click.Context, name: str) -> None:
    """Documents the JSON shapes the CLI emits."""
    out_mod.out(_FIELDS[name])


@click.command("describe")
@click.argument("group")
@click.argument("command")
@click.pass_context
def describe_cmd(ctx: click.Context, group: str, command: str) -> None:
    """Shows options/arguments of a command from the click tree."""
    from proton_mail_bridge.cli import main as root

    grp = root.commands.get(group)
    if not isinstance(grp, click.Group) or command not in grp.commands:
        out_mod.out_err("not_found", "Unknown command", f"{group} {command}", exit_code=2)
        return
    cmd = grp.commands[command]
    out_mod.out({
        "group": group,
        "command": command,
        "help": (cmd.help or "").strip(),
        "options": [p.name for p in cmd.params if isinstance(p, click.Option)],
        "arguments": [p.name for p in cmd.params if isinstance(p, click.Argument)],
    })


def register_meta(root: click.Group) -> None:
    root.add_command(fields_cmd)
    root.add_command(describe_cmd)
