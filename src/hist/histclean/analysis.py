from __future__ import annotations

import difflib
import re
from collections import defaultdict
from collections.abc import Callable, Iterator

from ..entries import Entry
from .core import BaseFlag, GroupFlag, IndividualFlag

IndividualStrategy = Callable[[list[Entry]], Iterator[tuple[int, str]]]
GroupStrategy = Callable[[list[Entry]], Iterator[list[int]]]

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


def flag_duplicate_groups(entries: list[Entry]) -> Iterator[list[int]]:
    command_to_indices: dict[str, list[int]] = defaultdict(list)
    for index, entry in enumerate(entries):
        if command := entry.command.strip():
            command_to_indices[command].append(index)
    yield from (indices for indices in command_to_indices.values() if len(indices) > 1)


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


def flag_similar_groups(entries: list[Entry]) -> Iterator[list[int]]:
    """Group similar commands run within the time window of each other, transitively.

    Unrelated entries in between are never members. The relation depends only on each pair's own
    timestamps and commands, so removing entries creates no new group: a second run over the result finds none.
    Expects entries sorted by timestamp.
    """
    commands = [entry.command.strip() for entry in entries]
    tokens = [tokenize(command) for command in commands]
    timestamps = [entry.timestamp or 0 for entry in entries]
    parents = list(range(len(entries)))

    def find_root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for first in range(len(entries)):
        for second in range(first + 1, len(entries)):
            if timestamps[second] - timestamps[first] > SIMILAR_COMMAND_WINDOW_SECONDS:
                break
            if not commands[first] or not commands[second]:
                continue
            if are_tokens_similar_jaccard(tokens[first], tokens[second]) or are_tokens_similar_difflib(
                tokens[first], tokens[second]
            ):
                parents[find_root(second)] = find_root(first)

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(entries)):
        groups[find_root(index)].append(index)
    yield from (members for members in groups.values() if len(members) > 1)


INDIVIDUAL_STRATEGIES: list[IndividualStrategy] = [
    flag_individual_multiline,
    flag_individual_empty,
    flag_individual_blacklist,
    flag_individual_orphaned_backslash,
]
GROUP_STRATEGIES: list[tuple[GroupStrategy, str]] = [
    (flag_duplicate_groups, "Duplicate command"),
    (
        flag_similar_groups,
        f"Similar commands within {SIMILAR_COMMAND_WINDOW_SECONDS // 60} minutes of each other",
    ),
]


def merge_groups(groups: list[tuple[list[int], str]]) -> list[tuple[list[int], list[str]]]:
    """Merge groups that share a member into one group.

    >>> merge_groups([([1, 5], "dup"), ([5, 6], "similar"), ([8, 9], "dup")])
    [([1, 5, 6], ['dup', 'similar']), ([8, 9], ['dup'])]
    """
    parents = list(range(len(groups)))

    def find_root(group_index: int) -> int:
        while parents[group_index] != group_index:
            group_index = parents[group_index]
        return group_index

    owner_by_member: dict[int, int] = {}
    for group_index, (members, _) in enumerate(groups):
        for member in members:
            if member in owner_by_member:
                parents[find_root(group_index)] = find_root(owner_by_member[member])
                continue
            owner_by_member[member] = group_index

    merged: dict[int, tuple[set[int], list[str]]] = {}
    for group_index, (members, reason) in enumerate(groups):
        merged_members, reasons = merged.setdefault(find_root(group_index), (set(), []))
        merged_members.update(members)
        if reason not in reasons:
            reasons.append(reason)
    return [(sorted(members), reasons) for members, reasons in merged.values()]


def analyze(entries: list[Entry]) -> list[BaseFlag]:
    """Flag entries to remove, once, over entries sorted by timestamp. Entries marked `# !keep` are never removed."""
    flag_context = {
        "all_entries": entries,
        "max_line_num_width": len(str(len(entries))),
    }
    is_kept = [bool(KEEP_MARKER_RE.search(entry.command)) for entry in entries]

    raw_groups = [
        (removable_members, reason)
        for strategy, reason in GROUP_STRATEGIES
        for members in strategy(entries)
        if len(removable_members := [member for member in members if not is_kept[member]]) > 1
    ]
    group_flags = [
        GroupFlag(member_indices=members, reason_text=" / ".join(reasons), **flag_context)
        for members, reasons in merge_groups(raw_groups)
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
