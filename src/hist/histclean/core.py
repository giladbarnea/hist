from __future__ import annotations

from abc import ABC, abstractmethod

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text as RichText

from ..entries import Entry

MAX_SHOWN_NON_MEMBERS = 3


class BaseFlag(ABC):
    """Abstract base class for a flagged change in the history."""

    def __init__(
        self,
        all_entries: list[Entry],
        max_line_num_width: int,
        reason_text: str,
    ):
        self.all_entries = all_entries
        self.max_line_num_width = max_line_num_width
        self.reason_text = reason_text

    @abstractmethod
    def get_indices_to_remove(self) -> set[int]:
        raise NotImplementedError

    @abstractmethod
    def render(self) -> Panel:
        raise NotImplementedError

    @abstractmethod
    def get_sort_key(self) -> int:
        raise NotImplementedError

    def _format_line(
        self,
        table: Table,
        entry_index: int,
        content_renderable: RichText | Syntax,
        marker: str = " ",
    ) -> None:
        marker_text = RichText(
            marker, style=f"diff.{'plus' if marker == '+' else 'minus'}"
        )
        table.add_row(f"{entry_index + 1}", marker_text, content_renderable)


class IndividualFlag(BaseFlag):
    """Represents a single flagged entry to be removed."""

    def __init__(
        self,
        entry_index: int,
        reasons: list[str],
        **kwargs,
    ):
        super().__init__(reason_text="\n".join(f"- {reason}" for reason in reasons), **kwargs)
        self.entry_index = entry_index

    def get_indices_to_remove(self) -> set[int]:
        return {self.entry_index}

    def get_sort_key(self) -> int:
        return self.entry_index

    def render(self) -> Panel:
        meta_table = Table.grid(padding=(0, 2))
        meta_table.add_column(style=Style.parse("bold #98C379"))
        meta_table.add_column()
        meta_table.add_row("Reason(s):", self.reason_text)
        entry_command = self.all_entries[self.entry_index].command

        line_num_str = f"{self.entry_index + 1:>{self.max_line_num_width}}"
        line_num_text = RichText(line_num_str, style="#3A3F4C")

        entry_syntax = Syntax(entry_command, "bash", theme="monokai", line_numbers=False)

        entry_display_table = Table.grid(padding=(0, 1))
        entry_display_table.add_column(width=self.max_line_num_width, justify="right")
        entry_display_table.add_column()
        entry_display_table.add_row(line_num_text, entry_syntax)

        meta_table.add_row("Entry:", entry_display_table)

        return Panel(
            meta_table,
            box=box.ROUNDED,
            title="[title]Flagged Entry[/title]",
            border_style="#4B5263",
            padding=(1, 2),
        )


class GroupFlag(BaseFlag):
    """A group of duplicate or similar entries. Removes the marked members; non-members are never touched."""

    def __init__(self, member_indices: list[int], removed_indices: set[int], **kwargs):
        super().__init__(**kwargs)
        self.member_indices = member_indices
        self.removed_indices = removed_indices

    def get_indices_to_remove(self) -> set[int]:
        return self.removed_indices

    def get_sort_key(self) -> int:
        return self.member_indices[0]

    def render(self) -> Panel:
        meta_table = Table.grid(padding=(0, 1, 1, 2))
        meta_table.add_column(style=Style.parse("bold #98C379"))
        meta_table.add_column()
        meta_table.add_row("Reason:", self.reason_text)
        meta_table.add_row(
            "Action:",
            RichText(
                "Remove the entries marked -; everything else stays", style="italic #61AFEF"
            ),
        )

        entries_table = Table.grid(padding=(0, 1))
        entries_table.add_column(
            width=self.max_line_num_width + 1, justify="right", style="#3A3F4C"
        )
        entries_table.add_column(width=2, justify="right")
        entries_table.add_column()

        for previous_member, member in zip([None, *self.member_indices], self.member_indices):
            if previous_member is not None:
                self._render_non_members(entries_table, range(previous_member + 1, member))
            command = self.all_entries[member].command
            if member not in self.removed_indices:
                syntax = Syntax(command, "bash", theme="monokai", line_numbers=False)
                self._format_line(entries_table, member, syntax, marker="+")
                continue
            self._format_line(entries_table, member, RichText(command, style="#5C6370"), marker="-")

        content_group = Group(meta_table, Rule(style="#4B5263"), entries_table)

        return Panel(
            content_group,
            box=box.ROUNDED,
            title="[title]Entry Group[/title]",
            border_style="#4B5263",
            padding=(0, 1),
        )

    def _render_non_members(self, table: Table, non_members: range) -> None:
        if len(non_members) > MAX_SHOWN_NON_MEMBERS:
            table.add_row("", "", RichText(f"⋯ {len(non_members)} other entries", style="#3A3F4C"))
            return
        for index in non_members:
            self._format_line(table, index, RichText(self.all_entries[index].command, style="#3A3F4C"))
