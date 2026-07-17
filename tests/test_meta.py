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
