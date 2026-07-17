from __future__ import annotations

from click.testing import CliRunner

from proton_mail_bridge.cli import main


def test_skill_install_claude(tmp_path):
    dest = tmp_path / "skills"
    result = CliRunner().invoke(
        main, ["skill", "install", "--agent", "claude", "--dest", str(dest)]
    )
    assert result.exit_code == 0
    assert (dest / "proton-mail-bridge" / "SKILL.md").exists()
    assert (dest / "proton-mail-bridge" / "references" / "commands.md").exists()


def test_skill_install_codex(tmp_path):
    dest = tmp_path / "codex-out"
    result = CliRunner().invoke(main, ["skill", "install", "--agent", "codex", "--dest", str(dest)])
    assert result.exit_code == 0
    assert (dest / "AGENTS.md").exists()
    assert (dest / "references" / "commands.md").exists()


def test_skill_install_codex_refuses_to_overwrite(tmp_path):
    dest = tmp_path / "codex-out"
    dest.mkdir()
    (dest / "AGENTS.md").write_text("project-owned content")
    result = CliRunner().invoke(main, ["skill", "install", "--agent", "codex", "--dest", str(dest)])
    assert result.exit_code != 0
    assert (dest / "AGENTS.md").read_text() == "project-owned content"


def test_skill_install_default_agent_is_claude(tmp_path):
    dest = tmp_path / "default-skills"
    result = CliRunner().invoke(main, ["skill", "install", "--dest", str(dest)])
    assert result.exit_code == 0
    assert (dest / "proton-mail-bridge" / "SKILL.md").exists()
