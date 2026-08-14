from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main


def test_fields_message():
    result = CliRunner().invoke(main, ["--json", "fields", "message"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "account" in data["summary"]
    assert "list_unsubscribe" in data["summary"]
    assert "from_name" in data["summary"]
    assert "body_text" in data["full"]
    assert "truncated" in data["search"]["fields"]


def test_every_command_is_documented_for_agents():
    """The skill reference is what an agent reads instead of trying flags -- a command that
    only exists in the code is a command no agent will find."""
    import click

    from proton_mail_bridge.skill_install import _skills_dir

    doc = (_skills_dir() / "references" / "commands.md").read_text(encoding="utf-8")

    def paths(node: click.Command, path: list[str]):
        for name, cmd in getattr(node, "commands", {}).items():
            if isinstance(cmd, click.Group):
                yield from paths(cmd, path + [name])
            else:
                yield " ".join(path + [name])

    missing = [p for p in paths(main, []) if p not in doc]
    assert missing == []


def test_describe_command():
    result = CliRunner().invoke(main, ["--json", "describe", "message", "search"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["group"] == "message"
    assert data["command"] == "search"
    assert "subject" in data["options"]


def test_describe_nested_subgroup_command():
    result = CliRunner().invoke(main, ["--json", "describe", "account", "identity", "add"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["path"] == ["account", "identity", "add"]
    assert "email" in data["options"]
    assert "label" in data["options"]


def test_describe_group_lists_its_commands():
    result = CliRunner().invoke(main, ["--json", "describe", "account", "identity"])
    assert result.exit_code == 0
    assert set(json.loads(result.output)["commands"]) == {
        "add", "remove", "set-default", "discover"}


def test_describe_unknown_path_errors():
    result = CliRunner().invoke(main, ["--json", "describe", "account", "nope"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["title"] == "Unknown command"


def test_describe_deep_group_reconstructs_real_invocation():
    result = CliRunner().invoke(main, ["--json", "describe", "account", "identity", "add"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert f"{data['group']} {data['command']}" == "account identity add"


def test_describe_past_leaf_command_errors():
    result = CliRunner().invoke(main, ["--json", "describe", "message", "search", "extra"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["title"] == "Unknown command"
