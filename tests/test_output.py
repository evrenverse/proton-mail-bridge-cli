from __future__ import annotations

import json

from proton_mail_bridge.core.errors import BridgeError
from proton_mail_bridge.utils import output


def test_error_to_dict():
    err = BridgeError("auth", "No account", "Run `account add`")
    assert err.to_dict() == {
        "ok": False,
        "error": {
            "type": "auth",
            "title": "No account",
            "detail": "Run `account add`",
        },
    }


def test_out_json(capsys):
    output.set_json(True)
    output.out({"a": 1})
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"a": 1}


def test_out_err_json_exit(capsys):
    output.set_json(True)
    try:
        output.out_err("conn", "Bridge nicht erreichbar", "127.0.0.1:1143")
    except SystemExit as exc:
        assert exc.code == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"]["type"] == "conn"
