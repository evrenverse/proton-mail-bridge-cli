from __future__ import annotations

import json

from click.testing import CliRunner

from proton_mail_bridge.cli import main
from proton_mail_bridge.core.config import Account, Config, Endpoint, save_config


def _seed(tmp_path):
    cfg = Config(
        endpoint=Endpoint(),
        accounts=[Account("a@p.me", "pw", alias="work")],
        default_account="a@p.me",
    )
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    return path


def test_account_list_json(tmp_path, monkeypatch):
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    result = CliRunner().invoke(main, ["--json", "account", "list"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["accounts"][0]["email"] == "a@p.me"
    assert data["accounts"][0]["default"] is True


def test_account_set_default(tmp_path, monkeypatch):
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    CliRunner().invoke(main, ["account", "add-raw", "--email", "b@p.me", "--password", "x"])
    result = CliRunner().invoke(main, ["account", "set-default", "b@p.me"])
    assert result.exit_code == 0
    from proton_mail_bridge.core.config import load_config
    assert load_config(path).default_account == "b@p.me"


def test_remove_by_alias_clears_stale_default(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    cfg = Config(endpoint=Endpoint(), accounts=[Account("a@p.me", "pw", alias="work")],
                 default_account="a@p.me")
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    result = CliRunner().invoke(main, ["account", "remove", "work", "--yes"])
    assert result.exit_code == 0
    loaded = load_config(path)
    assert loaded.accounts == []
    assert loaded.default_account is None


def test_identity_add_and_list(tmp_path, monkeypatch):
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    add = CliRunner().invoke(main, ["account", "identity", "add", "--email", "k@p.me",
                                    "--name", "Kontakt", "--label", "kontakt"])
    assert add.exit_code == 0
    result = CliRunner().invoke(main, ["--json", "account", "list"])
    row = json.loads(result.output)["accounts"][0]
    assert {i["email"] for i in row["identities"]} == {"a@p.me", "k@p.me"}   # login is implicit
    assert row["default_identity"] is None


def test_identity_add_rejects_duplicates(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    CliRunner().invoke(main, ["account", "identity", "add", "--email", "k@p.me",
                              "--label", "kontakt"])
    dup_mail = CliRunner().invoke(main, ["--json", "account", "identity", "add",
                                         "--email", "k@p.me"])
    assert dup_mail.exit_code != 0
    mail_error = json.loads(dup_mail.output)["error"]
    assert mail_error["title"] == "Identity already exists"
    assert mail_error["detail"] == "k@p.me"
    dup_label = CliRunner().invoke(main, ["--json", "account", "identity", "add",
                                          "--email", "x@p.me", "--label", "kontakt"])
    assert dup_label.exit_code != 0
    label_error = json.loads(dup_label.output)["error"]
    assert label_error["title"] == "Label already used"
    assert label_error["detail"] == "kontakt"
    # neither rejected duplicate was appended — the account still holds just the first entry
    assert len(load_config(path).accounts[0].identities) == 1


def test_identity_add_rejects_duplicates_case_insensitively(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    CliRunner().invoke(main, ["account", "identity", "add", "--email", "k@p.me",
                              "--label", "kontakt"])
    dup_mail = CliRunner().invoke(main, ["--json", "account", "identity", "add",
                                         "--email", "K@p.me"])
    assert dup_mail.exit_code != 0
    dup_label = CliRunner().invoke(main, ["--json", "account", "identity", "add",
                                          "--email", "y@p.me", "--label", "Kontakt"])
    assert dup_label.exit_code != 0
    # a case-shifted duplicate must not shadow the original entry
    assert len(load_config(path).accounts[0].identities) == 1


def test_identity_set_default_and_remove(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    CliRunner().invoke(main, ["account", "identity", "add", "--email", "k@p.me",
                              "--label", "kontakt"])
    assert CliRunner().invoke(main, ["account", "identity", "set-default",
                                     "kontakt"]).exit_code == 0
    assert load_config(path).accounts[0].default_identity == "kontakt"
    remove = CliRunner().invoke(main, ["account", "identity", "remove", "kontakt", "--yes"])
    assert remove.exit_code == 0
    account = load_config(path).accounts[0]
    assert account.identities == []
    assert account.default_identity is None   # stale default is cleared


def test_identity_remove_refuses_the_login_address(tmp_path, monkeypatch):
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    result = CliRunner().invoke(
        main, ["--json", "account", "identity", "remove", "a@p.me", "--yes"]
    )
    assert result.exit_code != 0
    assert "login" in json.loads(result.output)["error"]["detail"].lower()


def test_identity_remove_allows_an_explicit_entry_for_the_login_address(tmp_path, monkeypatch):
    """An explicit identity entry for the login address itself is removable -- only the
    *implicit* (synthesized) login identity is protected. account_identities() returns the
    explicit object in this case, so the login guard must not fire."""
    from proton_mail_bridge.core.config import Identity, load_config
    cfg = Config(endpoint=Endpoint(),
                 accounts=[Account("a@p.me", "pw",
                                   identities=[Identity("a@p.me", name="Chef", label="chef")])],
                 default_account="a@p.me")
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    result = CliRunner().invoke(main, ["--json", "account", "identity", "remove", "chef", "--yes"])
    assert result.exit_code == 0
    assert load_config(path).accounts[0].identities == []


def test_identity_remove_case_mismatched_config_removes_the_named_entry(tmp_path, monkeypatch):
    """`identity add` can no longer create this state (case-insensitive dedup), but a
    hand-edited config can: two identities differing only by case. Removing k@p.me must
    remove k@p.me, not K@p.me."""
    from proton_mail_bridge.core.config import Identity, load_config
    cfg = Config(endpoint=Endpoint(),
                 accounts=[Account("a@p.me", "pw",
                                   identities=[Identity("k@p.me"), Identity("K@p.me")])],
                 default_account="a@p.me")
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    result = CliRunner().invoke(
        main, ["--json", "account", "identity", "remove", "k@p.me", "--yes"]
    )
    assert result.exit_code == 0
    assert [i.email for i in load_config(path).accounts[0].identities] == ["K@p.me"]


def test_identity_remove_does_not_delete_a_sibling_with_the_same_address(tmp_path, monkeypatch):
    """Two identities can share one address under different labels (hand-edited config only --
    `identity add` blocks duplicate addresses outright). Filtering the removal by email string
    would delete both; filtering by object identity removes only the one that was resolved."""
    from proton_mail_bridge.core.config import Identity, load_config
    cfg = Config(endpoint=Endpoint(),
                 accounts=[Account("a@p.me", "pw",
                                   identities=[Identity("k@p.me", label="alpha"),
                                               Identity("k@p.me", label="beta")])],
                 default_account="a@p.me")
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    result = CliRunner().invoke(main, ["--json", "account", "identity", "remove", "alpha", "--yes"])
    assert result.exit_code == 0
    assert [i.label for i in load_config(path).accounts[0].identities] == ["beta"]


def test_identity_remove_rejects_blank_value(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    CliRunner().invoke(main, ["account", "identity", "add", "--email", "k@p.me",
                              "--label", "kontakt"])
    CliRunner().invoke(main, ["account", "identity", "set-default", "kontakt"])
    result = CliRunner().invoke(main, ["--json", "account", "identity", "remove", "", "--yes"])
    assert result.exit_code != 0
    # a blank VALUE must not fall back to (and delete) the current default identity
    account = load_config(path).accounts[0]
    assert len(account.identities) == 1
    assert account.default_identity == "kontakt"


def _fake_sent_mailbox(monkeypatch, messages):
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox
    box = FakeMailBox({"Sent": messages}, folder_flags={"Sent": ("\\Sent",)})
    monkeypatch.setattr(
        ImapClient, "connect", classmethod(lambda cls, ep, acc, **k: ImapClient(box, acc.email))
    )


def test_identity_discover_previews_without_writing(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    from tests.conftest import FakeMessage
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    _fake_sent_mailbox(monkeypatch, [FakeMessage(from_="k@p.me"), FakeMessage(from_="k@p.me"),
                                     FakeMessage(from_="a@p.me")])
    result = CliRunner().invoke(main, ["--json", "account", "identity", "discover"])
    assert result.exit_code == 0
    items = json.loads(result.output)[0]["items"]
    senders = items["senders"]
    assert items["folder"] == "Sent"
    assert senders[0] == {"email": "k@p.me", "name": None, "count": 2, "known": False}
    assert [s for s in senders if s["email"] == "a@p.me"][0]["known"] is True
    assert items["added"] == []                             # nothing created, only reported
    assert load_config(path).accounts[0].identities == []   # no --save, no change


def test_identity_discover_save_adds_unknown_addresses(tmp_path, monkeypatch):
    from proton_mail_bridge.core.config import load_config
    from tests.conftest import FakeMessage
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    _fake_sent_mailbox(monkeypatch, [FakeMessage(from_="k@p.me"), FakeMessage(from_="a@p.me")])
    result = CliRunner().invoke(main, ["--json", "account", "identity", "discover", "--save"])
    assert result.exit_code == 0
    assert [i.email for i in load_config(path).accounts[0].identities] == ["k@p.me"]


def test_identity_discover_save_with_nothing_added_does_not_rewrite_the_file(tmp_path, monkeypatch):
    """save_config is a full tomli_w rewrite that strips comments and hand formatting -- skip
    it entirely when --save has nothing new to add, so hand-added notes survive a no-op run."""
    from tests.conftest import FakeMessage
    path = tmp_path / "config.toml"
    raw = '# hand-added notes about this account\n[[accounts]]\nemail = "a@p.me"\npassword = "pw"\n'
    path.write_text(raw, encoding="utf-8")
    before = path.read_bytes()  # as written: Windows text mode turns \n into \r\n
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    _fake_sent_mailbox(monkeypatch, [FakeMessage(from_="a@p.me")])   # already known: login address
    result = CliRunner().invoke(main, ["--json", "account", "identity", "discover", "--save"])
    assert result.exit_code == 0
    assert path.read_bytes() == before


def test_identity_discover_save_twice_adds_no_duplicate(tmp_path, monkeypatch):
    """A second --save must not re-add what is already configured — not even case-shifted,
    because `identity remove` filters by exact case and would then delete the wrong entry."""
    from proton_mail_bridge.core.config import load_config
    from tests.conftest import FakeMessage
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    # the stored spelling comes first, so both sides of the comparison must fold case
    for sender in ("K@P.me", "k@p.me", "K@P.me"):
        _fake_sent_mailbox(monkeypatch, [FakeMessage(from_=sender)])
        result = CliRunner().invoke(main, ["--json", "account", "identity", "discover", "--save"])
        assert result.exit_code == 0
    assert [i.email for i in load_config(path).accounts[0].identities] == ["K@P.me"]


def test_identity_discover_refuses_when_there_is_no_sent_folder(tmp_path, monkeypatch):
    """Without \\Sent, resolve_folder would fall back to INBOX — and --save would then
    store every correspondent as our own identity."""
    from proton_mail_bridge.core.config import load_config
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    box = FakeMailBox({"INBOX": [FakeMessage(from_="fremd@x.de")]})   # no \\Sent flags
    monkeypatch.setattr(
        ImapClient, "connect", classmethod(lambda cls, ep, acc, **k: ImapClient(box, acc.email))
    )
    result = CliRunner().invoke(main, ["--json", "account", "identity", "discover", "--save"])
    assert result.exit_code == 0            # for_accounts reports the error per account
    entry = json.loads(result.output)[0]
    assert entry["ok"] is False
    assert "Sent" in entry["error"]["detail"]
    assert load_config(path).accounts[0].identities == []


def test_identity_discover_connects_with_the_resolved_endpoint(tmp_path, monkeypatch):
    """Env overrides must reach discover like every other network command."""
    from proton_mail_bridge.core.imap import ImapClient
    from tests.conftest import FakeMailBox, FakeMessage
    path = _seed(tmp_path)
    monkeypatch.setenv("PROTON_BRIDGE_CONFIG", str(path))
    monkeypatch.setenv("PROTON_BRIDGE_HOST", "10.9.9.9")
    seen = []
    box = FakeMailBox({"Sent": [FakeMessage(from_="k@p.me")]}, folder_flags={"Sent": ("\\Sent",)})

    def fake_connect(cls, ep, acc, **k):
        seen.append(ep.host)
        return ImapClient(box, acc.email)

    monkeypatch.setattr(ImapClient, "connect", classmethod(fake_connect))
    result = CliRunner().invoke(main, ["--json", "account", "identity", "discover"])
    assert result.exit_code == 0
    assert seen == ["10.9.9.9"]
