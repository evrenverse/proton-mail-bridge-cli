from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

import click

from proton_mail_bridge.utils import output as out_mod


def _skills_dir() -> Path:
    return Path(str(resources.files("proton_mail_bridge").joinpath("skills")))


@click.group("skill")
def skill_group() -> None:
    """Install the agent skill."""


def _plan(agent: str, target: Path, files: list[Path]) -> None:
    """Dry-run payload: which files would be written, and which of them already exist
    (the copy overwrites silently, so that list is the point of the preview)."""
    out_mod.out_plan("skill install", {
        "agent": agent,
        "target": str(target),
        "count": len(files),
        "overwrites": [str(f) for f in files if f.exists()],
        "files": [str(f) for f in files],
    })


@skill_group.command("install")
@click.option(
    "--agent",
    type=click.Choice(["claude", "codex"]),
    default="claude",
    show_default=True,
)
@click.option("--dest", default=None, help="Target directory (default: agent-typical).")
@out_mod.dry_run_option
def install(agent: str, dest: str | None, dry_run: bool) -> None:
    """Copies SKILL.md/AGENTS.md + references to the agent location."""
    src = _skills_dir()
    refs = sorted((src / "references").glob("*.md"))
    if agent == "claude":
        target = Path(dest) if dest else Path.cwd() / ".claude" / "skills"
        skill_dir = target / "proton-mail-bridge"
        if dry_run:
            _plan(agent, skill_dir,
                  [skill_dir / "SKILL.md"] + [skill_dir / "references" / r.name for r in refs])
            return
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
        if dry_run:
            _plan(agent, target,
                  [target / "AGENTS.md"] + [target / "references" / r.name for r in refs])
            return
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / "AGENTS.md", target / "AGENTS.md")
        ref_dir = target / "references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        for ref in refs:
            shutil.copy(ref, ref_dir / ref.name)
        click.echo(f"Codex AGENTS.md installed → {target / 'AGENTS.md'}")


def register_skill(root: click.Group) -> None:
    root.add_command(skill_group)
