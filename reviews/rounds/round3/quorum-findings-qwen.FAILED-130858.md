Need a decision from you before I can finish the audit.

**Blocker:** the shell allowlist in this session permits read-only commands (`grep`, `wc`, `git status` — all working) but rejects every interpreter invocation before it executes. Confirmed by minimal probe: `python3 -c "print(1)"` → *"This command requires approval"*. Same for `python3 -m pytest tests/`, `.venv/bin/pytest`, and `bash -lc 'python3 --version'`. `/tmp` writes are also blocked (`mkdir /tmp/qa/repo` → *"may only create directories in ... ~/quorum"*), so I cannot stage a scratch copy of the repo outside the working dir either.

**Why it matters:** the brief's hard constraint 2 requires every cited number to carry evidence I produced myself (command + output), and §2.B/§2.D explicitly require me to attack `plate.cluster()` by calling it, verify the `PYTHONHASHSEED` accident by running two seeds, and prove `check-leaks` can/can't be bypassed. With no interpreter I can only do static reading — I'd have to downgrade most findings to "static analysis, not executed", which weakens exactly the parts the brief calls highest-value.

**What I need — one of:**

1. **Allow interpreter + temp writes** — approve `python3` / `.venv/bin/pytest` / `.venv/bin/quorum`, and let me create a scratch copy under the session dir (e.g. `<repo>/.audit-tmp/`, deleted after) so `quorum run`'s output writes and the demo e2e don't touch any tracked file. Repo stays byte-clean otherwise.
2. **Tell me to run in place** — approve `python3` and I'll run `pytest` and the four `quorum` commands directly against `demo/` in the repo. This *will* write `demo/out/*` and `.pytest_cache/` (the demo dir already contains prior run residue + `.bak` files). Say the word if that's acceptable given "不改任何现有文件".
3. **Accept a static-only audit** — I finish now from source reading + read-only shell. I'll mark every claim I could not execute and say so plainly up front. Weaker on §2.B/§2.D, and I won't invent outputs I didn't get.

Which one? Defaulting to (1) and stopping here until you answer.
