from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..entries import read_entries


@dataclass
class Sequence:
    """A continuous sequence of history entries."""

    start_ts: int
    end_ts: int
    count: int = 0


@dataclass
class HistoryFile:
    """Represents a history file with its metadata and time sequences."""

    path: Path
    name: str
    sequences: list[Sequence] = field(default_factory=list)
    lines: int = 0
    error: str | None = None

    def __hash__(self) -> int:
        return hash(self.path)

    @property
    def start_ts(self) -> int | None:
        return self.sequences[0].start_ts if self.sequences else None

    @property
    def end_ts(self) -> int | None:
        return self.sequences[-1].end_ts if self.sequences else None

    @property
    def start_date(self) -> datetime | None:
        return datetime.fromtimestamp(self.start_ts) if self.start_ts else None

    @property
    def end_date(self) -> datetime | None:
        return datetime.fromtimestamp(self.end_ts) if self.end_ts else None

    @property
    def duration_days(self) -> int | None:
        if self.start_ts and self.end_ts:
            return max(1, (self.end_ts - self.start_ts) // 86400)
        return None

    @property
    def category(self) -> str:
        if self.name == ".zsh_history":
            return "main"
        if self.name.startswith(".zsh_history."):
            return "snapshot"
        return "other"


@dataclass
class AnalysisResult:
    """Aggregated analysis of all history files."""

    files: list[HistoryFile] = field(default_factory=list)

    @property
    def min_ts(self) -> int | None:
        valid = [history_file.start_ts for history_file in self.files if history_file.start_ts]
        return min(valid) if valid else None

    @property
    def max_ts(self) -> int | None:
        valid = [history_file.end_ts for history_file in self.files if history_file.end_ts]
        return max(valid) if valid else None

    @property
    def time_range(self) -> int | None:
        if self.min_ts and self.max_ts:
            return self.max_ts - self.min_ts
        return None


def scan_file(path: Path) -> tuple[list[Sequence], int]:
    """Scan a file to extract sequences and total line count."""
    entries = read_entries(path)
    timestamps = [entry.timestamp for entry in entries if entry.timestamp is not None]
    line_count = sum(len(entry.lines) for entry in entries)

    if not timestamps:
        return [], line_count

    timestamps.sort()
    sequences: list[Sequence] = []
    gap_threshold = 86400

    current_start = timestamps[0]
    current_end = timestamps[0]
    current_count = 1

    for timestamp in timestamps[1:]:
        if timestamp - current_end >= gap_threshold:
            sequences.append(Sequence(current_start, current_end, current_count))
            current_start = timestamp
            current_count = 0
        current_end = timestamp
        current_count += 1

    sequences.append(Sequence(current_start, current_end, current_count))
    return sequences, line_count


def analyze_file(path: Path) -> HistoryFile:
    """Analyze a single history file."""
    history_file = HistoryFile(path=path, name=path.name)

    if not path.exists():
        history_file.error = "File not found"
        return history_file

    sequences, lines = scan_file(path)
    history_file.sequences = sequences
    history_file.lines = lines

    if not history_file.sequences:
        history_file.error = "No valid timestamps found"

    return history_file


def analyze_all(paths: Iterable[Path]) -> AnalysisResult:
    """Analyze all given history files."""
    result = AnalysisResult()
    for path in paths:
        result.files.append(analyze_file(path))
    result.files.sort(key=lambda history_file: (history_file.start_ts or float("inf"), history_file.name))
    return result
