from __future__ import annotations

from click.testing import CliRunner

from proton_mail_bridge.cli import main


def test_skill_install_claude(tmp_path):
    dest = tmp_path / "proton-mail-bridge"
    result = CliRunner().invoke(
        main, ["skill", "install", "--agent", "claude", "--dest", str(dest)]
    )
    assert result.exit_code == 0
    assert (dest / "SKILL.md").exists()
    assert (dest / "references" / "commands.md").exists()


def test_skill_install_codex(tmp_path):
    dest = tmp_path / "codex-out"
    result = CliRunner().invoke(main, ["skill", "install", "--agent", "codex", "--dest", str(dest)])
    assert result.exit_code == 0
    assert (dest / "AGENTS.md").exists()
    assert (dest / "references" / "commands.md").exists()
    # AGENTS.md is the condensed guide; the long form used to be missing entirely
    assert (dest / "references" / "SKILL.md").exists()
    assert "references/SKILL.md" in (dest / "AGENTS.md").read_text(encoding="utf-8")


def test_dest_means_the_same_directory_for_both_agents(tmp_path):
    """One flag, one meaning. It used to be the parent for claude and the target for codex,
    so the same --dest scattered files into a skills collection for one and not the other."""
    for agent in ("claude", "codex"):
        dest = tmp_path / agent
        assert CliRunner().invoke(
            main, ["skill", "install", "--agent", agent, "--dest", str(dest)]
        ).exit_code == 0
        assert (dest / "references" / "commands.md").exists()
        assert not (dest / "proton-mail-bridge").exists()


def test_claude_default_target_is_the_skill_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert CliRunner().invoke(main, ["skill", "install", "--agent", "claude"]).exit_code == 0
    assert (tmp_path / ".claude" / "skills" / "proton-mail-bridge" / "SKILL.md").exists()


def test_skill_install_claude_stays_free_of_agents_md(tmp_path):
    dest = tmp_path / "skills"
    CliRunner().invoke(main, ["skill", "install", "--agent", "claude", "--dest", str(dest)])
    assert not (dest / "AGENTS.md").exists()
    assert not (dest / "references" / "SKILL.md").exists()


def test_skill_install_dry_run_predicts_every_file(tmp_path):
    """The preview is only worth anything if it lists exactly what the real run writes."""
    import json

    for agent in ("claude", "codex"):
        dest = tmp_path / agent
        preview = CliRunner().invoke(
            main, ["--json", "skill", "install", "--agent", agent, "--dest", str(dest),
                   "--dry-run"]
        )
        assert preview.exit_code == 0
        planned = set(json.loads(preview.output)["files"])
        assert not dest.exists()
        assert CliRunner().invoke(
            main, ["skill", "install", "--agent", agent, "--dest", str(dest)]
        ).exit_code == 0
        assert {str(p) for p in dest.rglob("*") if p.is_file()} == planned


def test_skill_install_codex_refuses_to_overwrite(tmp_path):
    dest = tmp_path / "codex-out"
    dest.mkdir()
    (dest / "AGENTS.md").write_text("project-owned content")
    result = CliRunner().invoke(main, ["skill", "install", "--agent", "codex", "--dest", str(dest)])
    assert result.exit_code != 0
    assert (dest / "AGENTS.md").read_text() == "project-owned content"


def test_codex_updates_its_own_agents_md(tmp_path):
    """Refusing every existing AGENTS.md made updating impossible: the only copy in the way
    was normally an older one this installer had written itself."""
    dest = tmp_path / "codex-out"
    dest.mkdir()
    (dest / "AGENTS.md").write_text(
        "# proton-mail-bridge — Anleitung für Agenten\n\nalte deutsche Fassung\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(main, ["skill", "install", "--agent", "codex", "--dest", str(dest)])
    assert result.exit_code == 0
    assert "alte deutsche Fassung" not in (dest / "AGENTS.md").read_text(encoding="utf-8")
    assert (dest / "references" / "commands.md").exists()


def test_skill_install_default_agent_is_claude(tmp_path):
    dest = tmp_path / "default-skills"
    result = CliRunner().invoke(main, ["skill", "install", "--dest", str(dest)])
    assert result.exit_code == 0
    assert (dest / "SKILL.md").exists()
    assert not (dest / "AGENTS.md").exists()
