"""The corpus: every history file the user keeps, found by one naming convention."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

ZSH_TRANSIENT_SUFFIXES = (".new", ".LOCK")


def corpus(home: Path) -> list[Path]:
    """Return the live file `~/.zsh_history` and every `~/.zsh_history.*`, minus the files zsh writes transiently."""
    archives = [
        path
        for path in home.glob(".zsh_history.*")
        if not path.name.endswith(ZSH_TRANSIENT_SUFFIXES)
    ]
    return sorted(archives) + sorted(home.glob(".zsh_history"))


def history_paths(raw_paths: Sequence[str]) -> list[Path]:
    """Explicit paths override the corpus."""
    if raw_paths:
        return [Path(raw_path).expanduser() for raw_path in raw_paths]
    return corpus(Path.home())
