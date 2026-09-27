"""Falsification claims for the corpus-first hist suite.

Each test drives a real CLI entry point against a temporary home. Only the review's
approval step (the TUI) is replaced, by a function that approves or rejects flags.
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from hist import histclean, histmerge
from hist.entries import parse_entries
from hist.histclean.analysis import analyze
from hist.histclean.core import GroupFlag

BASE_TIMESTAMP = 1_790_000_000


def entry(seconds: int, *command_lines: str) -> str:
    first_line, *continuation_lines = command_lines
    return "\n".join([f": {BASE_TIMESTAMP + seconds}:0;{first_line}", *continuation_lines]) + "\n"


def approve_all(flags):
    return flags


def reject_all(flags):
    return []


def snapshot(directory: Path) -> dict[str, bytes | str]:
    """Every name in the directory mapped to its bytes, or to its target for a symlink."""
    return {
        path.name: os.readlink(path) if path.is_symlink() else path.read_bytes()
        for path in directory.iterdir()
    }


class Home:
    def __init__(self, directory: Path):
        self.directory = directory

    def write(self, name: str, content: str | bytes) -> Path:
        path = self.directory / name
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return path

    def run(self, main, argv: list[str], approve=None, stdin=None) -> tuple[int, bytes, str]:
        stdout_buffer = io.BytesIO()
        stdout = io.TextIOWrapper(stdout_buffer, encoding="utf-8")
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {"HOME": str(self.directory)}),
            patch("sys.stdout", stdout),
            patch("sys.stdin", stdin or io.StringIO()),
            redirect_stderr(stderr),
        ):
            status = main(argv, approve=approve)
            stdout.flush()
        return status, stdout_buffer.getvalue(), stderr.getvalue()


class TemporaryHomeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.home = Home(Path(temporary_directory.name))

    def write_dirty_corpus(self) -> None:
        self.home.write(
            ".zsh_history.2026-08-17.consolidated",
            entry(0, "git status")
            + entry(100, 'fd -e md -x rg -l "hist corpus" src')
            + entry(130, 'fd -e md -x rg -l "hist corpus" docs')
            + entry(160, "bat README.md")
            + entry(200, 'fd -e md -x rg -l "corpus" docs'),
        )
        self.home.write(
            ".zsh_history",
            entry(0, "git status")
            + entry(5000, "git status")
            + entry(6000, "python --version")
            + entry(7000, "cat <<EOF > notes.txt", "line one", "EOF"),
        )


class HistmergeTest(TemporaryHomeTestCase):
    def test_dry_run_changes_nothing_on_disk(self) -> None:
        self.write_dirty_corpus()
        before = snapshot(self.home.directory)

        status, stdout, _ = self.home.run(histmerge.main, ["--dry-run"], approve=approve_all)

        self.assertEqual(status, 0)
        self.assertEqual(stdout, b"", f"Expected no merged output under --dry-run. Got: {stdout!r}")
        after = snapshot(self.home.directory)
        self.assertEqual(after, before, f"--dry-run changed the home. New or changed: {set(after.items()) ^ set(before.items())}")

    def test_running_twice_is_the_same_as_running_once(self) -> None:
        self.write_dirty_corpus()
        before = snapshot(self.home.directory)

        _, first_stdout, _ = self.home.run(histmerge.main, [], approve=approve_all)
        _, second_stdout, _ = self.home.run(histmerge.main, [], approve=approve_all)

        self.assertEqual(second_stdout, first_stdout, "Second run printed a different union.")
        after = snapshot(self.home.directory)
        self.assertEqual(after, before, f"A run changed the corpus. New or changed: {set(after) ^ set(before)}")

    def test_union_is_exhaustive_deduplicated_and_keeps_multiline_entries_whole(self) -> None:
        heredoc = entry(3, "cat <<EOF > notes.txt", "line one", "", "EOF")
        metafied = entry(4, "echo caf").encode()[:-1] + b"\x83\xa9\n"
        self.home.write(".zsh_history.a", entry(1, "ls -la /tmp").encode() + heredoc.encode() + metafied)
        self.home.write(".zsh_history", entry(2, "pwd") + heredoc + entry(5, "make test"))

        status, stdout, _ = self.home.run(histmerge.main, [], approve=reject_all)

        self.assertEqual(status, 0)
        expected = (entry(1, "ls -la /tmp") + entry(2, "pwd") + heredoc).encode() + metafied + entry(5, "make test").encode()
        self.assertEqual(stdout, expected, f"Union is wrong.\nExpected:\n{expected!r}\nGot:\n{stdout!r}")

    def test_corpus_is_the_naming_convention_and_nothing_else(self) -> None:
        self.home.write(".zsh_history", entry(1, "echo live"))
        consolidated = self.home.write(".zsh_history.2026-08-17.consolidated", entry(2, "echo consolidated"))
        self.home.write(".zsh_history.pinned", "echo pinned\n")
        self.home.write(".zsh_history.new", entry(3, "echo half-written"))
        os.symlink("host-12345", self.home.directory / ".zsh_history.LOCK")
        self.home.write(".zsh_hist.clean.2026-09-27_10-22-00_000000", entry(4, "echo old-backup"))
        self.home.write("notes.txt", entry(5, "echo unrelated"))

        _, stdout, _ = self.home.run(histmerge.main, [], approve=reject_all)
        _, explicit_stdout, _ = self.home.run(histmerge.main, [str(consolidated)], approve=reject_all)

        read_commands = {line.split(";", 1)[-1] for line in stdout.decode().splitlines()}
        self.assertEqual(
            read_commands,
            {"echo live", "echo consolidated", "echo pinned"},
            f"Corpus read the wrong files. Got commands: {read_commands}",
        )
        self.assertEqual(explicit_stdout.decode(), entry(2, "echo consolidated"), "Explicit paths must override the corpus.")

    def test_review_removes_only_group_members_and_never_keep_entries(self) -> None:
        self.home.write(
            ".zsh_history.a",
            entry(100, 'fd -e md -x rg -l "hist corpus" src')
            + entry(130, 'fd -e md -x rg -l "hist corpus" docs')
            + entry(160, "bat README.md")
            + entry(200, 'fd -e md -x rg -l "corpus" docs')
            + entry(1000, "git status")
            + entry(1010, "echo hello")
            + entry(1020, "git status -s")
            + entry(3000, "make deploy")
            + entry(9000, "make deploy # !keep")
            + entry(9500, "make deploy # !keep"),
        )
        self.home.write(
            ".zsh_history",
            entry(4000, "make deploy")
            + entry(5000, "make deploy")
            + entry(6000, "make deploy")
            + entry(7000, "echo שלום # !keep"),
        )

        _, stdout, _ = self.home.run(histmerge.main, [], approve=approve_all)

        expected = (
            entry(160, "bat README.md")
            + entry(200, 'fd -e md -x rg -l "corpus" docs')
            + entry(1010, "echo hello")
            + entry(1020, "git status -s")
            + entry(6000, "make deploy")
            + entry(7000, "echo שלום # !keep")
            + entry(9000, "make deploy # !keep")
            + entry(9500, "make deploy # !keep")
        )
        self.assertEqual(stdout.decode(), expected, f"Review removed the wrong entries.\nExpected:\n{expected}\nGot:\n{stdout.decode()}")

    def test_cleaning_its_own_output_again_proposes_nothing(self) -> None:
        self.write_dirty_corpus()
        self.home.write(
            ".zsh_history.b",
            entry(20_000, "docker compose up -d web")
            + entry(20_010, "cat a.txt")
            + entry(20_020, "cat a.txt")
            + entry(21_000, "docker compose up -d worker"),
        )
        _, first_stdout, _ = self.home.run(histmerge.main, [], approve=approve_all)
        with tempfile.TemporaryDirectory() as output_directory:
            output = Path(output_directory) / ".zsh_history.2026-09-27.consolidated"
            output.write_bytes(first_stdout)
            received_flags = []

            def record(flags):
                received_flags.extend(flags)
                return flags

            _, second_stdout, _ = self.home.run(histmerge.main, [str(output)], approve=record)

        self.assertEqual(
            [(flag.reason_text, sorted(flag.get_indices_to_remove())) for flag in received_flags],
            [],
            "A second run over the cleaned output proposed more removals.",
        )
        self.assertEqual(second_stdout, first_stdout)

    def test_without_a_tty_prints_the_raw_union_and_writes_nothing(self) -> None:
        self.write_dirty_corpus()
        before = snapshot(self.home.directory)

        status, stdout, stderr = self.home.run(histmerge.main, [], stdin=io.StringIO())

        self.assertEqual(status, 0)
        headers = [line for line in stdout.decode().splitlines() if line.startswith(": ")]
        self.assertEqual(len(headers), 8, f"Expected the 8 unique entries unreviewed. Got:\n{stdout.decode()}")
        self.assertIn("not a TTY", stderr)
        self.assertEqual(snapshot(self.home.directory), before)


class HistcleanTest(TemporaryHomeTestCase):
    def test_in_place_clean_changes_exactly_one_file(self) -> None:
        self.write_dirty_corpus()
        live_file = self.home.directory / ".zsh_history"
        live_file.chmod(0o600)
        before = snapshot(self.home.directory)

        status, _, _ = self.home.run(histclean.main, [str(live_file)], approve=approve_all)

        self.assertEqual(status, 0)
        after = snapshot(self.home.directory)
        self.assertEqual(set(after), set(before), f"Files appeared or vanished: {set(after) ^ set(before)}")
        changed = {name for name in before if before[name] != after[name]}
        self.assertEqual(changed, {".zsh_history"})
        self.assertEqual(live_file.read_text(), entry(5000, "git status"))
        self.assertEqual(live_file.stat().st_mode & 0o777, 0o600, "The rewrite must keep the file's permissions.")

    def test_rejecting_the_review_leaves_the_file_byte_identical(self) -> None:
        self.write_dirty_corpus()
        before = snapshot(self.home.directory)

        status, _, _ = self.home.run(histclean.main, [str(self.home.directory / ".zsh_history")], approve=reject_all)

        self.assertEqual(status, 0)
        self.assertEqual(snapshot(self.home.directory), before)

    def test_rewrite_keeps_undecodable_bytes(self) -> None:
        metafied = entry(1, "echo caf # !keep").encode()[:-1] + b"\x83\xa9\n"
        live_file = self.home.write(".zsh_history", metafied + entry(2, "ls").encode() + entry(3, "ls").encode())

        self.home.run(histclean.main, [str(live_file)], approve=approve_all)

        self.assertEqual(live_file.read_bytes(), metafied + entry(3, "ls").encode())

    def test_a_shell_writing_during_the_review_blocks_the_rewrite(self) -> None:
        self.write_dirty_corpus()
        live_file = self.home.directory / ".zsh_history"
        new_line = entry(8000, "echo typed during review")

        def approve_while_a_shell_appends(flags):
            with live_file.open("a") as file_handle:
                file_handle.write(new_line)
            return flags

        original = live_file.read_text()
        status, _, _ = self.home.run(histclean.main, [str(live_file)], approve=approve_while_a_shell_appends)

        self.assertEqual(status, 1)
        self.assertEqual(live_file.read_text(), original + new_line, "The rewrite lost what the shell wrote.")

    def test_without_a_tty_refuses_and_writes_nothing(self) -> None:
        self.write_dirty_corpus()
        before = snapshot(self.home.directory)

        status, _, _ = self.home.run(histclean.main, [str(self.home.directory / ".zsh_history")], stdin=io.StringIO())

        self.assertEqual(status, 1)
        self.assertEqual(snapshot(self.home.directory), before)


class GroupFlagTest(unittest.TestCase):
    def test_similar_entries_group_across_an_unrelated_entry(self) -> None:
        entries = parse_entries(
            (
                entry(100, 'fd -e md -x rg -l "hist corpus" src')
                + entry(130, 'fd -e md -x rg -l "hist corpus" docs')
                + entry(160, "bat README.md")
                + entry(200, 'fd -e md -x rg -l "corpus" docs')
            ).splitlines()
        )

        flags = analyze(entries)

        self.assertEqual(
            [(type(flag), getattr(flag, "member_indices", None)) for flag in flags],
            [(GroupFlag, [0, 1, 3])],
        )


if __name__ == "__main__":
    unittest.main()
