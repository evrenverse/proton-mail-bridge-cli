from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main


def test_fields_message():
    result = CliRunner().invoke(main, ["--json", "fields", "message"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "account" in data["summary"]
    assert "body_text" in data["full"]


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
