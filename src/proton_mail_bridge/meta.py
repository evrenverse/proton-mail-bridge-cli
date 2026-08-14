from __future__ import annotations

import click

from proton_mail_bridge.utils import output as out_mod

_FIELDS = {
    "message": {
        "summary": [
            "account", "uid", "folder", "message_id", "date", "date_str", "from", "from_name",
            "list_unsubscribe", "to", "cc", "subject", "flags", "size", "has_attachments",
            "attachment_count", "snippet",
        ],
        "full": ["...summary...", "body_text", "body_html", "headers", "attachments"],
        "list_unsubscribe": {
            "shape": {"http": ["url"], "mailto": ["mailto:…"], "one_click": "bool"},
            "null_when": "the message carries no List-Unsubscribe header (RFC 2369)",
            "note": "bulk-sender signal, not a verdict — notifications set it too",
        },
        "search": {
            "note": "sibling of 'items' in message search/senders results",
            "fields": ["candidates", "scanned", "truncated", "reason", "limit", "folders"],
            "truncated": "the answer is incomplete; reason is 'limit' or 'fetch_budget'",
        },
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
@click.argument("path", nargs=-1, required=True)
@click.pass_context
def describe_cmd(ctx: click.Context, path: tuple[str, ...]) -> None:
    """Shows options/arguments of a command from the click tree.

    Walks nested groups: `describe account identity add`. Naming a group instead of a
    command lists that group's commands.
    """
    from proton_mail_bridge.cli import main as root

    node: click.Command = root
    for name in path:
        if not isinstance(node, click.Group) or name not in node.commands:
            out_mod.out_err("not_found", "Unknown command", " ".join(path), exit_code=2)
            return
        node = node.commands[name]
    if isinstance(node, click.Group):
        out_mod.out({
            "path": list(path),
            "help": (node.help or "").strip(),
            "commands": sorted(node.commands),
        })
        return
    out_mod.out({
        "path": list(path),
        "group": " ".join(path[:-1]),
        "command": path[-1],
        "help": (node.help or "").strip(),
        "options": [p.name for p in node.params if isinstance(p, click.Option)],
        "arguments": [p.name for p in node.params if isinstance(p, click.Argument)],
    })


def register_meta(root: click.Group) -> None:
    root.add_command(fields_cmd)
    root.add_command(describe_cmd)
