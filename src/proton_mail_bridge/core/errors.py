from __future__ import annotations


class BridgeError(Exception):
    """Base class for all expected errors; carries the uniform error format."""

    def __init__(self, type: str, title: str, detail: str = "") -> None:
        super().__init__(f"{title}: {detail}" if detail else title)
        self.type = type
        self.title = title
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "error": {"type": self.type, "title": self.title, "detail": self.detail},
        }


class AccountSelectionError(BridgeError):
    """Account selection is ambiguous or unknown."""


class ConnectionResolveError(BridgeError):
    """Bridge endpoint is unreachable."""
