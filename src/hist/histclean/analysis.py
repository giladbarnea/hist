from __future__ import annotations

import bisect
import difflib
import re
from collections import defaultdict
from collections.abc import Callable, Iterator

from ..entries import Entry
from .core import BaseFlag, GroupFlag, IndividualFlag

IndividualStrategy = Callable[[list[Entry]], Iterator[tuple[int, str]]]
GroupStrategy = Callable[[list[Entry]], Iterator[tuple[list[int], set[int]]]]

BLACKLIST_PATTERNS = [
    re.compile(r"--version\s*$"),
    re.compile(r"[א-ת]+"),
    re.compile(r"[^\x20-\x7E\t]+"),
    re.compile(r"^ *\n?$"),
    re.compile(r"^.$", re.DOTALL),
]
KEEP_MARKER_RE = re.compile(r"#\s*!keep\b", re.IGNORECASE)
TOKEN_SEPARATOR_RE = re.compile(r"[/ \s]+")

JACCARD_SIMILARITY_THRESHOLD = 0.5
DIFFLIB_SIMILARITY_THRESHOLD = 0.75
SIMILAR_COMMAND_WINDOW_SECONDS = 300


def flag_individual_multiline(entries: list[Entry]) -> Iterator[tuple[int, str]]:
    for index, entry in enumerate(entries):
        if len(entry.lines) > 1:
            yield index, "It is a multi-line entry."


def flag_individual_empty(entries: list[Entry]) -> Iterator[tuple[int, str]]:
    for index, entry in enumerate(entries):
        if not entry.command.strip():
            yield index, "It is an empty entry."


def flag_individual_blacklist(entries: list[Entry]) -> Iterator[tuple[int, str]]:
    for index, entry in enumerate(entries):
        if match := next(
            (pattern.search(entry.command) for pattern in BLACKLIST_PATTERNS), None
        ):
            yield index, f"Matches '{match.group()}'"


def flag_individual_orphaned_backslash(entries: list[Entry]) -> Iterator[tuple[int, str]]:
    for index, entry in enumerate(entries[:-1]):
        if entry.command.rstrip().endswith("\\"):
            yield index, "Entry ends with orphaned backslash (line continuation not found)"


def flag_duplicate_groups(entries: list[Entry]) -> Iterator[tuple[list[int], set[int]]]:
    """Every copy of a command except the last."""
    command_to_indices: dict[str, list[int]] = defaultdict(list)
    for index, entry in enumerate(entries):
        if command := entry.command.strip():
            command_to_indices[command].append(index)
    yield from ((indices, set(indices[:-1])) for indices in command_to_indices.values() if len(indices) > 1)


def tokenize(command: str) -> set[str]:
    return set(TOKEN_SEPARATOR_RE.split(command))


def are_tokens_similar_jaccard(tokens_one: set[str], tokens_two: set[str]) -> bool:
    union = tokens_one | tokens_two
    return len(tokens_one & tokens_two) / len(union) >= JACCARD_SIMILARITY_THRESHOLD


def are_tokens_similar_difflib(tokens_one: set[str], tokens_two: set[str]) -> bool:
    sorted_intersection = " ".join(sorted(tokens_one & tokens_two))
    first_comparison = f"{sorted_intersection} {' '.join(sorted(tokens_one - tokens_two))}".strip()
    second_comparison = f"{sorted_intersection} {' '.join(sorted(tokens_two - tokens_one))}".strip()
    return any(
        _ratio_reaches(one, two, DIFFLIB_SIMILARITY_THRESHOLD)
        for one, two in (
            (sorted_intersection, first_comparison),
            (sorted_intersection, second_comparison),
            (first_comparison, second_comparison),
        )
    )


def _ratio_reaches(one: str, two: str, threshold: float) -> bool:
    """Same answer as `ratio() >= threshold`, skipping the costly ratio when a cheap upper bound already fails."""
    matcher = difflib.SequenceMatcher(None, one, two)
    return (
        matcher.real_quick_ratio() >= threshold
        and matcher.quick_ratio() >= threshold
        and matcher.ratio() >= threshold
    )


def flag_superseded_groups(entries: list[Entry]) -> Iterator[tuple[list[int], set[int]]]:
    """Remove an entry when a similar command runs after it, within the time window. Group each one with what supersedes it.

    Entries with the same timestamp never supersede each other: zsh stamps imported entries with one load time,
    so their real times are unknown. Whether an entry is superseded depends only on entries after it that survive,
    so a second run over the result finds nothing. Expects entries sorted by timestamp.
    """
    commands = [entry.command.strip() for entry in entries]
    tokens = [tokenize(command) for command in commands]
    timestamps = [entry.timestamp or 0 for entry in entries]
    parents = list(range(len(entries)))
    superseded: set[int] = set()

    def find_root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for first in range(len(entries)):
        if not commands[first]:
            continue
        for second in range(bisect.bisect_right(timestamps, timestamps[first]), len(entries)):
            if timestamps[second] - timestamps[first] > SIMILAR_COMMAND_WINDOW_SECONDS:
                break
            if commands[second] and (
                are_tokens_similar_jaccard(tokens[first], tokens[second])
                or are_tokens_similar_difflib(tokens[first], tokens[second])
            ):
                superseded.add(first)
                parents[find_root(first)] = find_root(second)
                break

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(entries)):
        groups[find_root(index)].append(index)
    yield from ((members, superseded.intersection(members)) for members in groups.values() if len(members) > 1)


INDIVIDUAL_STRATEGIES: list[IndividualStrategy] = [
    flag_individual_multiline,
    flag_individual_empty,
    flag_individual_blacklist,
    flag_individual_orphaned_backslash,
]
GROUP_STRATEGIES: list[tuple[GroupStrategy, str]] = [
    (flag_duplicate_groups, "Duplicate command"),
    (
        flag_superseded_groups,
        f"A similar command followed within {SIMILAR_COMMAND_WINDOW_SECONDS // 60} minutes",
    ),
]


def analyze(entries: list[Entry]) -> list[BaseFlag]:
    """Flag entries to remove, once, over entries sorted by timestamp. Entries marked `# !keep` are never removed."""
    flag_context = {
        "all_entries": entries,
        "max_line_num_width": len(str(len(entries))),
    }
    is_kept = [bool(KEEP_MARKER_RE.search(entry.command)) for entry in entries]

    group_flags = [
        GroupFlag(member_indices=members, removed_indices=removable, reason_text=reason, **flag_context)
        for strategy, reason in GROUP_STRATEGIES
        for members, removed in strategy(entries)
        if (removable := {index for index in removed if not is_kept[index]})
    ]
    removed_by_groups = set().union(*(flag.get_indices_to_remove() for flag in group_flags))

    reasons_by_index: dict[int, list[str]] = defaultdict(list)
    for strategy in INDIVIDUAL_STRATEGIES:
        for index, reason in strategy(entries):
            reasons_by_index[index].append(reason)
    individual_flags = [
        IndividualFlag(entry_index=index, reasons=reasons, **flag_context)
        for index, reasons in reasons_by_index.items()
        if not is_kept[index] and index not in removed_by_groups
    ]

    return sorted([*group_flags, *individual_flags], key=lambda flag: flag.get_sort_key())
