from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from ..entries import Entry, decode, encode, parse_entries, render, union
from .analysis import analyze
from .core import BaseFlag
from .ui import HistoryCleanApp, _console_print

Approve = Callable[[list[BaseFlag]], list[BaseFlag]]


def approve_in_tui(flags: list[BaseFlag]) -> list[BaseFlag]:
    return HistoryCleanApp(flags).run() or []


def review(entries: list[Entry], approve: Approve) -> list[Entry]:
    """Analyze the entries once, let `approve` pick flags, and return the entries that survive them."""
    flags = analyze(entries)
    if not flags:
        _console_print("[success]Nothing to clean.[/success]")
        return entries
    removed_indices = set().union(*(flag.get_indices_to_remove() for flag in approve(flags)))
    _console_print(f"[info]Review removed {len(removed_indices)} of {len(entries)} entries.[/info]")
    return [entry for index, entry in enumerate(entries) if index not in removed_indices]


def write_by_rename(path: Path, entries: list[Entry]) -> None:
    """Write next to the file, then rename over it, the way zsh saves history. Keeps the file's permissions."""
    temporary_path = path.with_name(f"{path.name}.histclean.new")
    temporary_path.write_bytes(encode(render(entries)))
    shutil.copymode(path, temporary_path)
    os.replace(temporary_path, path)


def main(argv: list[str] | None = None, approve: Approve | None = None) -> int:
    """Review one history file and rewrite it in place with the approved removals."""
    parser = argparse.ArgumentParser(
        description="Review one zsh history file and rewrite it in place. To clean the whole corpus, use histmerge."
    )
    parser.add_argument("file", type=Path, help="The history file to clean, e.g. ~/.zsh_history")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    path: Path = args.file.expanduser()

    if approve is None and not sys.stdin.isatty():
        _console_print("[error]histclean needs a TTY on stdin for the review.[/error]")
        return 1
    approve = approve or approve_in_tui

    original_bytes = path.read_bytes()
    entries = union([parse_entries(decode(original_bytes).splitlines())])
    kept_entries = review(entries, approve)
    if kept_entries == entries:
        _console_print("[warning]No changes applied. History file unchanged.[/warning]")
        return 0
    if path.read_bytes() != original_bytes:
        _console_print(f"[error]{path} changed during the review. Nothing written. Run histclean again.[/error]")
        return 1

    write_by_rename(path, kept_entries)
    _console_print(f"[success]Cleaned history saved to {path}[/success]")
    return 0
