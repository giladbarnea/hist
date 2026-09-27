# Handoff: hist suite redesign (corpus-first)

> **Status 2026-09-27:** implemented on branch `claude/wizardly-hypatia-edn1cy`. Open decision resolved as the time window (5 minutes, `SIMILAR_COMMAND_WINDOW_SECONDS`). Tests: `tests/test_suite.py`.

Written 2026-09-27 11:51 by the session that diagnosed the `histmerge --all --dry-run` bug. Task is mid-process: diagnosis and design are delivered and accepted in principle. Implementation has not started. No repo file was changed.

## 1. Task overview

**Situation.** The user hit a bug: `histmerge --all --dry-run`, answering `r` (run histclean first) in a loop, creates `.zsh_hist.clean.<ts>` backups that the next `--all` run discovers as inputs, cleans in place, and backs up again. They asked for a zoomed-out design diagnosis, not a patch.

**The user's real job** (their words): "a merged, clean, exhaustive form of the entire history corpus printed onto my terminal so I can grep it". Corpus means all history files, not only `~/.zsh_history`.

**Constraints the user set.**
- Fine to throw away existing ideas. No scope creep. No new features.
- Ignore the comments in `~/.zshrc`. Only official docs and clean empirical tests count.
- Any experimentation or research runs in a forked Fable subagent. Wait for its bottom line.
- Communication: ASD-STE100, one name per thing, short. See `~/.claude/CLAUDE.md`.

**Success criteria.** A simpler, cohesive suite where one run gives the clean union of the corpus on stdout, runs are idempotent, inputs are never mutated, and no backup files are spawned. Then: implement it with TDD.

## 2. Prior state (what existed when this session started)

Repo `~/dev/hist` at commit `5de5cc2`, clean tree. Three commands: `histclean` (interactive TUI, rewrites files in place, writes a backup holding the pre-clean lines), `histmerge` (merge to stdout, gated by a clean check that calls histclean), `histcompare` (timeline). Shared discovery in `src/hist/history_files.py`. Tests exist only for `--cleanup`.

Inherited mental model, now known to be wrong: the README and docstrings call `.zsh_hist.clean.*` files "clean outputs". They hold the dirty original.

## 3. Current state

Delivered to the user, all accepted unless noted:
1. Diagnosis (verified): unit of work is the file, unit of value is the corpus.
2. Design proposal (section 4 below), with one user tweak on the cluster rule.
3. Pseudocode of the implementation and an order of work.
4. Test plan as falsification claims, with one open decision (section 5).
5. zsh flag research by a forked subagent, with a correction of my own earlier "finding 4".

Artifacts:
- Created: `~/.claude/projects/-Users-giladbarnea-dev-hist/memory/hist-corpus-redesign.md` (project memory) and its `MEMORY.md` index line.
- Created in the session scratchpad (`/private/tmp/claude-501/-Users-giladbarnea-dev-hist/10b764bc-5b1a-49b5-9bae-2050d9059f11/scratchpad/`): `repro.py` (pool-growth and sandwich repro), `hist.c` `builtin.c` `init.c` (zsh 5.9 source), `zshlab/lab.py` `zshlab/lab2.py` and `zshlab/runs/` (isolated flag experiments). Scratchpad is session-specific and may be gone.
- Created: this file.
- No repo changes. `.venv` was re-created by `uv run` (ignored by git).

## 4. Important discoveries

**Verified defects in the current suite.**
1. Backups hold the dirty original under a name that says "clean". The name lie spread into `--all` docs, histcompare's "clean" category, and the README.
2. The clean check loop in `histmerge.ensure_histories_are_clean` re-cleans discovered backups in place and spawns backups of backups. Repro: pool 2, 5, 9 files over three runs. Real home: 15 backups between 10:22 and 10:35 on 2026-09-27.
3. `--dry-run` runs the clean check first, so it rewrites the live file. Repro: 6 lines to 2 under `--dry-run`.
4. Discovery matches only dead patterns. Nothing in the user's zshrc or home produces `.zsh_history.<digits>`, `shrinkbackup`, or `~/.zsh_history_backups/`. The real corpus in home matches none: `.zsh_history` (entries from 2026-09-09), `.zsh_history.2026-08-17.consolidated` (42,191 lines, 2025-05-06 to 2026-08-17), `.zsh_history.pinned` (one bare command). The corpus has no entries between 2026-08-17 and 2026-09-09. `--all` sees 15 backups and misses the consolidated file.
5. The "consecutive similar" cluster is a contiguous index range, so an unrelated entry between two similar ones is deleted. Verified: `git status`, `echo hello`, `git status -s` deletes `echo hello`.
6. Three entry regexes: histclean needs ten-digit timestamps, histmerge and histcompare accept any. Test data with short timestamps silently becomes non-entries in histclean.

**Correction.** My assessment's "finding 4" (a zsh process wrote 701 removed lines back) was wrong. The 1691-line backup born 10:23:06 is the live file's original pre-clean content, surfacing as a backup of the first backup during the second run. The first run's chain was 1691 to 975 to 957 to 956 to 955 lines. I had compared a backup that was itself cleaned in place against its own ancestor. The in-place mutation of backups destroyed the evidence.

**zsh facts** (zsh 5.9.2, manual, source, and isolated runs; user config has SHARE_HISTORY on, APPEND_HISTORY off, HIST_SAVE_NO_DUPS and HIST_IGNORE_ALL_DUPS on, SAVEHIST=50000):
- Under SHARE_HISTORY, APPEND_HISTORY does nothing (`hist.c` 2929–2931 folds the append family into one flag). Two interleaved shells gave byte-identical files with it on and off.
- A SHARE_HISTORY shell appends each own line as it runs and, at every normal exit, rewrites the file from the file (dedupe, trim to SAVEHIST, write `.new`, rename). It never writes memory back. After an outside process shrank the file, exit kept the shrunk content. Only `fc -A` and `fc -W` write memory back.
- SHARE off, APPEND on: nothing during the session, own session lines appended at exit, then rewrite from file. SHARE off, APPEND off: replace mode, whole memory written at exit, SAVEHIST ignored, other shells' lines lost.
- The user's combination is inert today and a trap only if SHARE_HISTORY is later turned off. Recommended to the user: delete `unsetopt APPEND_HISTORY` from zshrc (their call, outside the repo).
- `zsh -i -c 'cmd'` records nothing. Textual renders on `sys.__stderr__` (`linux_driver.py` line 51), so an interactive review with stdout piped to grep works.
- zsh's transient files next to the live file: `.zsh_history.new` and `.zsh_history.LOCK`.

**The accepted design.** Merge first, clean the union once, write nothing except stdout.
1. Corpus is `~/.zsh_history` plus `~/.zsh_history.*`, minus `.new` and `.LOCK`. Explicit paths override. No `--all`.
2. Inputs are read-only. No backups.
3. No clean check. One entry parser (blocks, so multi-line entries merge fine). Delete the clean/dirty state, `--check`, the `c/r/q` prompt, histcompare's dirty note.
4. One review session over the union. Analyze once on the original order. No second round, no "run again" message.
5. stdout only. No TTY on stdin: emit the raw union and say so on stderr. Persist by redirecting to a new dated name, then delete the older consolidated file (its removed entries would otherwise return).
6. Keep in-place cleaning for one explicit file (`histclean FILE`): same pipeline, write `.new`, rename. Safe under the user's zsh config (verified). Retire `--cleanup`.
7. Cluster rule, per the user's tweak: keep the lookahead leniency, but members are only the similar entries, delete all but the last member, never touch unrelated entries inside the span. The cluster flag takes the duplicate flag's shape (member list, keep last), one flag type for both.
8. histcompare stays as the read-only view over the corpus. Drop the optimal path.
Flags left: `--dry-run`. `src/hist/zsh_lexer.py` is imported by nothing; delete or leave.

**What did not work.** A home-wide `rg` timed out because `~/.zshrc` is a plain file, so its directory is HOME itself. Use targeted greps. First repro used short timestamps and histclean ignored them (regex needs ten digits).

## 5. Next steps

1. Get the user's decision on the one open question: does "consecutive" mean index distance (today, lookahead 2) or a time window? With a time window, cleaning becomes idempotent and "a second run over its own output proposes nothing" is testable. I recommended the time window.
2. Confirm the one interface change for testability: the pipeline takes a review function (default: the Textual app) so tests replace only the approval boundary.
3. Implement in vertical TDD slices, in this order: `entries.py` parser; cluster fix and GroupFlag (test with `fd`, `fd`, `bat README.md`, `fd`); `corpus.py`; histmerge pipeline (dry-run touches nothing, idempotent runs, cross-file dedupe, heredoc intact, no-TTY raw union); histclean as review plus rename-write (reject leaves the file byte-identical); histcompare on corpus; README and pyproject.
4. Load `tdd` and `write-tests` before writing tests. The falsification claims are in the last assistant message before this handoff, one claim per bad state.

## 6. Context to preserve

- Names in use: corpus (all history files), live file (`~/.zsh_history`), backup (`.zsh_hist.clean.*`), clean check (the gate before merging), union (the merged stream), review (the TUI session), consolidated file (the user's own archive naming). Keep these names.
- Skills used and required: `interaction:ai-to-delegated` before any subagent; `interaction:ai-to-leader` (and its `references/human.md`) before reporting; `pseudocode`, `tdd`, `write-tests` as loaded by the user.
- Baseline reading at session start: every file under `src/hist/` and `tests/`, `README.md`, `pyproject.toml`, `git log --stat`, `ls -la ~ | rg zsh_hist`, `stat`/`md5` of the backups, targeted `rg` over `~/.zshrc` and `~/.oh-my-zsh/lib/history.zsh`, `/etc/zshrc_Apple_Terminal`, and `discover_history_files()` against the real home.
- The user's zshrc lines that matter (code, not comments): `setopt SHARE_HISTORY`, `unsetopt APPEND_HISTORY`, `unsetopt INC_APPEND_HISTORY`, `setopt HIST_SAVE_BY_COPY`, `HISTSIZE=51000`, `SAVEHIST=50000`.
- Promise to the user: "Say the word and I will implement this list." Not yet said.
