# hist

Zsh history hygiene tools. They work on the **corpus**: `~/.zsh_history` plus every `~/.zsh_history.*` file, minus zsh's transient `.new` and `.LOCK` files. Explicit paths override the corpus.

## Commands

- `histmerge`: merge the corpus into one time-sorted union, review it once in a TUI, and print the kept entries to stdout. Inputs are read-only. `--dry-run` prints per-file and union counts only.
- `histclean FILE`: the same review for one file, written back in place by rename.
- `histcompare`: visualize the corpus's coverage, overlaps, and gaps.

## Keep a consolidated history

```bash
histmerge > ~/.zsh_history.2026-09-27.consolidated
rm ~/.zsh_history.2026-08-17.consolidated
```

Delete the older consolidated file. Otherwise its removed entries return to the union on the next run.

## Review rules

- Exact duplicate entries across files collapse to one.
- A duplicate command keeps only its last copy.
- An entry is removed when a similar command runs after it within 5 minutes. Unrelated entries in between are never touched.
- Entries that share one timestamp never supersede each other. zsh gives imported entries one load time, so their real times are unknown.
- An entry marked `# !keep` is never removed.

## Install

```bash
uv tool install -e .
```
