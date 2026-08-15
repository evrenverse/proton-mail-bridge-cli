from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

import click

from proton_mail_bridge.utils import output as out_mod

TITLE_MARKER = "# proton-mail-bridge"


def _skills_dir() -> Path:
    return Path(str(resources.files("proton_mail_bridge").joinpath("skills")))


def _is_ours(path: Path) -> bool:
    """True for an AGENTS.md this installer wrote — any version, including older ones in a
    different language. Those may be replaced by an update; anything else belongs to the
    project and must not be lost."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").lstrip().startswith(
            TITLE_MARKER
        )
    except OSError:
        return False


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
@click.option("--dest", default=None,
              help="Exact directory to write into (default: agent-typical).")
@out_mod.dry_run_option
def install(agent: str, dest: str | None, dry_run: bool) -> None:
    """Copies SKILL.md/AGENTS.md + references to the agent location.

    `--dest` names the directory that is written into, the same way for both agents. Only
    the defaults differ, because the agents do: Claude reads one folder per skill, Codex
    reads AGENTS.md from the project root.
    """
    src = _skills_dir()
    if agent == "claude":
        root = (Path(dest) if dest
                else Path.cwd() / ".claude" / "skills" / "proton-mail-bridge")
        files = {src / "SKILL.md": root / "SKILL.md"}
        done = f"Claude skill installed → {root}"
    else:
        root = Path(dest) if dest else Path.cwd()
        agents_md = root / "AGENTS.md"
        if agents_md.exists() and not _is_ours(agents_md):
            # never clobber a project-owned AGENTS.md; replacing our own is an update
            raise click.ClickException(
                f"{agents_md} exists and was not written by this installer — merge the "
                "content manually or pick another target with --dest."
            )
        # Codex auto-reads AGENTS.md only, so SKILL.md rides along as the long form under
        # references/ (linked from the AGENTS.md footer) instead of cluttering the project root
        files = {src / "AGENTS.md": root / "AGENTS.md",
                 src / "SKILL.md": root / "references" / "SKILL.md"}
        done = f"Codex AGENTS.md installed → {root / 'AGENTS.md'}"
    files.update({r: root / "references" / r.name
                  for r in sorted((src / "references").glob("*.md"))})
    if dry_run:
        _plan(agent, root, list(files.values()))
        return
    (root / "references").mkdir(parents=True, exist_ok=True)
    for source, target in files.items():
        shutil.copy(source, target)
    click.echo(done)


def register_skill(root: click.Group) -> None:
    root.add_command(skill_group)
