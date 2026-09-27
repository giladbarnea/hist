"""
Merge the zsh history corpus, review it once, and print the clean union to stdout.

Inputs
- Explicit paths, else the corpus: ~/.zsh_history plus ~/.zsh_history.*, minus
  zsh's transient .new and .LOCK files.
- Inputs are read-only. histmerge writes nothing except stdout and stderr.

Pipeline
1. Parse every file into entries. A multi-line entry stays one entry.
2. Union: exact duplicate entries collapse to one; sort by timestamp.
3. With a TTY on stdin, analyze the union once and review the flags in a TUI
   drawn on stderr, so `histmerge | grep foo` works. Without a TTY, skip the
   review and print the raw union.
4. Print the kept entries to stdout.

To persist the result, redirect it to a new dated file such as
~/.zsh_history.2026-09-27.consolidated, then delete the older consolidated
file. Otherwise its removed entries return to the union on the next run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .corpus import history_paths
from .entries import Entry, read_entries, render, union
from .histclean import Approve, approve_in_tui, console, review


def print_stats(paths: list[Path], entry_lists: list[list[Entry]], merged: list[Entry]) -> None:
    seen: set[Entry] = set()
    for path, entries in zip(paths, entry_lists, strict=True):
        newly_contributed = len(set(entries) - seen)
        seen.update(entries)
        print(f"{path}: entries={len(entries)}, newly_contributed={newly_contributed}", file=sys.stderr)
    total = sum(len(entries) for entries in entry_lists)
    print(f"union: files={len(paths)}, entries={len(merged)}, duplicates_collapsed={total - len(merged)}", file=sys.stderr)


def main(argv: list[str] | None = None, approve: Approve | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="*", help="Files to merge instead of the corpus")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print per-file and union counts to stderr, then stop.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    paths = history_paths(args.files)
    if not paths:
        console.print("[error]No history files found.[/error]")
        return 1
    entry_lists = [read_entries(path) for path in paths]
    merged = union(entry_lists)
    print_stats(paths, entry_lists, merged)
    if args.dry_run:
        return 0

    if approve is None and sys.stdin.isatty():
        approve = approve_in_tui
    if approve is None:
        console.print("[warning]stdin is not a TTY. Skipping the review and printing the raw union.[/warning]")
    kept_entries = review(merged, approve) if approve else merged

    sys.stdout.reconfigure(errors="surrogateescape")
    try:
        sys.stdout.write(render(kept_entries))
        sys.stdout.flush()
    except BrokenPipeError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
