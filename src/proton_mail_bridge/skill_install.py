from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

import click


def _skills_dir() -> Path:
    return Path(str(resources.files("proton_mail_bridge").joinpath("skills")))


@click.group("skill")
def skill_group() -> None:
    """Install the agent skill."""


@skill_group.command("install")
@click.option(
    "--agent",
    type=click.Choice(["claude", "codex"]),
    default="claude",
    show_default=True,
)
@click.option("--dest", default=None, help="Target directory (default: agent-typical).")
def install(agent: str, dest: str | None) -> None:
    """Copies SKILL.md/AGENTS.md + references to the agent location."""
    src = _skills_dir()
    if agent == "claude":
        target = Path(dest) if dest else Path.cwd() / ".claude" / "skills"
        skill_dir = target / "proton-mail-bridge"
        (skill_dir / "references").mkdir(parents=True, exist_ok=True)
        shutil.copy(src / "SKILL.md", skill_dir / "SKILL.md")
        for ref in (src / "references").glob("*.md"):
            shutil.copy(ref, skill_dir / "references" / ref.name)
        click.echo(f"Claude skill installed → {skill_dir}")
    else:
        target = Path(dest) if dest else Path.cwd()
        if (target / "AGENTS.md").exists():
            # never clobber an existing (possibly project-owned) AGENTS.md
            raise click.ClickException(
                f"{target / 'AGENTS.md'} already exists — merge the content manually "
                "or pick another target with --dest."
            )
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / "AGENTS.md", target / "AGENTS.md")
        refs = target / "references"
        refs.mkdir(parents=True, exist_ok=True)
        for ref in (src / "references").glob("*.md"):
            shutil.copy(ref, refs / ref.name)
        click.echo(f"Codex AGENTS.md installed → {target / 'AGENTS.md'}")


def register_skill(root: click.Group) -> None:
    root.add_command(skill_group)
