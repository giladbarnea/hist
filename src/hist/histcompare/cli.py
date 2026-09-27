"""
histcompare.py - Visualizer for ZSH history file coverage and gaps.

Analyzes multiple ZSH history files (extended_history format) to visualize their temporal
coverage, overlaps, and gaps.

Key Concepts
------------
1. Sequences & Gaps:
   Unlike simple start/end range checks, this tool fully scans each file to identify
   continuous "sequences" of history. A gap of > 1 day between entries breaks the sequence.
   This reveals significantly more detail, such as "hollow" backup files that span years
   but only contain a few distinct sessions.

2. Time Alignment:
   The tool identifies exact timestamp matches across files (start/end of sequences),
   helping to visualize when backups were taken relative to each other.

3. Visualization Modes:
   - Terminal: Rich-formatted summary table and ASCII timeline (stderr).
   - HTML: Interactive, scrollable web-based timeline with:
     * Discontinuous bars representing actual data sequences.
     * Two-way highlighting: Hovering a file highlights aligned timestamps in other files.
     * Sticky labels and horizontal scrolling for long histories.
     * Click-to-open integration with Cursor/VSCode.

Inputs
------
The same corpus histmerge reads: ~/.zsh_history plus ~/.zsh_history.*, minus
zsh's transient .new and .LOCK files. Explicit CLI paths override the corpus.

Usage
-----
    uv run histcompare --html timeline.html

Format
------
Expects ZSH EXTENDED_HISTORY format: ": <epoch>:<duration>;command"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..corpus import history_paths
from .analysis import analyze_all
from .html import output_html
from .terminal import console, output_terminal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare time ranges across zsh history backups",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Specific files to analyze instead of the corpus",
    )
    parser.add_argument(
        "--html",
        metavar="FILE",
        type=Path,
        help="Generate HTML visualization to FILE",
    )
    parser.add_argument(
        "--no-terminal",
        action="store_true",
        help="Suppress terminal output (useful with --html)",
    )
    args = parser.parse_args(argv)

    paths = history_paths(args.files)
    if not paths:
        console.print("[red]No history files found[/red]")
        return 1

    result = analyze_all(paths)

    if not args.no_terminal:
        output_terminal(result)

    if args.html:
        output_html(result, args.html)

    return 0


if __name__ == "__main__":
    sys.exit(main())
