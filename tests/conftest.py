from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from proton_mail_bridge.utils import output


@pytest.fixture(autouse=True)
def _reset_output_mode():
    output.set_json(False)
    yield
    output.set_json(False)


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", default=False,
                     help="Run tests against a real bridge (marker 'live').")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip = pytest.mark.skip(reason="needs --run-live (real bridge)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@dataclass
class FakeAttachment:
    filename: str
    content_type: str = "application/pdf"
    size: int = 1234
    content_id: str | None = None
    content_disposition: str = "attachment"
    payload: bytes = b"%PDF-1.4 fake"


@dataclass
class FakeMessage:
    uid: str = "1"
    subject: str = "Container order"
    from_: str = "supplier@company.com"
    to: tuple = ("me@p.me",)
    cc: tuple = ()
    date: datetime = field(default_factory=lambda: datetime(2026, 1, 2, 9, 30, tzinfo=UTC))
    date_str: str = "Thu, 02 Jan 2026 09:30:00 +0000"
    flags: tuple = ("\\Seen",)
    size: int = 4096
    text: str = "We order 3 containers."
    html: str = "<p>We order 3 containers.</p>"
    headers: dict = field(default_factory=lambda: {"message-id": ("<m1@company.com>",)})
    attachments: list = field(default_factory=lambda: [FakeAttachment("invoice.pdf")])


class _Folder:
    def __init__(self, store, flags_map):
        self._store = store
        self._flags = flags_map
        self.current = "INBOX"

    def list(self):
        @dataclass
        class FInfo:
            name: str
            flags: tuple = ()
            delim: str = "/"

        return [FInfo(name, self._flags.get(name, ())) for name in self._store]

    def set(self, name):
        self.current = name

    def create(self, name):
        self._store[name] = []

    def status(self, name):
        msgs = self._store.get(name, [])
        return {"MESSAGES": len(msgs), "UNSEEN": 0, "UIDVALIDITY": 1, "UIDNEXT": len(msgs) + 1}


class FakeMailBox:
    """Mimics the imap_tools.MailBox API for tests."""

    def __init__(self, store=None, folder_flags=None):
        self._store = store if store is not None else {"INBOX": [FakeMessage()]}
        self.folder = _Folder(self._store, folder_flags or {})
        self.moved: list = []
        self.copied: list = []
        self.flagged: list = []
        self.deleted: list = []
        self.appended: list = []

    def fetch(self, criteria="ALL", limit=None, mark_seen=False, bulk=True, reverse=False,
              headers_only=False):
        msgs = list(self._store.get(self.folder.current, []))
        if reverse:
            msgs.reverse()
        return msgs[:limit] if limit else msgs

    def uids(self, criteria="ALL", charset="US-ASCII", sort=None):
        return [m.uid for m in self._store.get(self.folder.current, [])]

    def move(self, uid_list, dest):
        self.moved.append((list(uid_list), dest))

    def copy(self, uid_list, dest):
        self.copied.append((list(uid_list), dest))

    def flag(self, uid_list, flag_set, value):
        self.flagged.append((list(uid_list), flag_set, value))

    def delete(self, uid_list):
        self.deleted.append(list(uid_list))

    def append(self, message_bytes, folder, dt=None, flag_set=None):
        self.appended.append((folder, flag_set))

    def logout(self):
        pass
