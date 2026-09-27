"""The one zsh EXTENDED_HISTORY parser, shared by histmerge, histclean, and histcompare."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ENTRY_HEADER_RE = re.compile(r"^: (\d+):\d+;")


@dataclass(frozen=True)
class Entry:
    """One history entry: a header line plus its continuation lines, or one line with no header."""

    timestamp: int | None
    lines: tuple[str, ...]

    @property
    def command(self) -> str:
        first_line, *continuation_lines = self.lines
        return "\n".join([ENTRY_HEADER_RE.sub("", first_line, count=1), *continuation_lines])


def parse_entries(lines: Iterable[str]) -> list[Entry]:
    """Group lines into entries. A line that follows a header and is not a header itself continues that entry.

    >>> [entry.lines for entry in parse_entries([": 1:0;cat <<EOF", "hi", "EOF", ": 2:0;ls"])]
    [(': 1:0;cat <<EOF', 'hi', 'EOF'), (': 2:0;ls',)]
    >>> parse_entries(["", "bare command"])
    [Entry(timestamp=None, lines=('bare command',))]
    """
    blocks: list[tuple[int | None, list[str]]] = []
    for line in lines:
        header = ENTRY_HEADER_RE.match(line)
        if header:
            blocks.append((int(header.group(1)), [line]))
            continue
        if blocks and blocks[-1][0] is not None:
            blocks[-1][1].append(line)
            continue
        if line:
            blocks.append((None, [line]))
    return [Entry(timestamp, tuple(block_lines)) for timestamp, block_lines in blocks]


def decode(data: bytes) -> str:
    """Decode history bytes losslessly. zsh writes metafied bytes that are not always valid UTF-8."""
    return data.decode("utf-8", errors="surrogateescape")


def encode(text: str) -> bytes:
    return text.encode("utf-8", errors="surrogateescape")


def read_entries(path: Path) -> list[Entry]:
    return parse_entries(decode(path.read_bytes()).splitlines())


def union(entry_lists: Iterable[list[Entry]]) -> list[Entry]:
    """Collapse exact duplicate entries to the first one seen, then sort by timestamp, stable by arrival.

    >>> a, b = Entry(2, (": 2:0;b",)), Entry(1, (": 1:0;a",))
    >>> union([[a, b], [a]]) == [b, a]
    True
    """
    unique_entries = dict.fromkeys(entry for entries in entry_lists for entry in entries)
    return sorted(unique_entries, key=lambda entry: entry.timestamp or 0)


def render(entries: Iterable[Entry]) -> str:
    return "".join(f"{line}\n" for entry in entries for line in entry.lines)
