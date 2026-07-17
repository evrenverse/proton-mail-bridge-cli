from __future__ import annotations


def test_version_importable():
    from importlib.metadata import version

    from proton_mail_bridge import __version__

    assert __version__ == version("proton-mail-bridge-cli")  # __init__ matches pyproject
