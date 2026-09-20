# Auto-push to GitHub

Every local commit auto-pushes to `origin/<current-branch>` via a git `post-commit` hook.

## What's installed

- **Source of truth:** `scripts/git-hooks/post-commit` (tracked in the repo).
- **Active hook:** `.git/hooks/post-commit` (local, not tracked).
- **Installer:** `make install-hooks` copies the former to the latter and makes it executable.

## Behavior

After `git commit`:

1. If `NO_AUTO_PUSH=1` is set, skip. Useful for batching or messy local work.
2. If HEAD is detached, skip (nothing to push cleanly).
3. If mid-rebase, mid-merge, or mid-cherry-pick, skip (to avoid pushing incomplete state).
4. Otherwise `git push origin <current-branch>`.
5. If push fails (rejected, offline, auth), the commit itself is **not** rolled back — the hook prints a hint and exits. Fix, then push manually.

## Usage

### Normal flow (zero friction)

```bash
git add <files>
git commit -m "message"
# hook pushes automatically
```

### Skip auto-push for one commit

```bash
NO_AUTO_PUSH=1 git commit -m "wip, don't push yet"
```

### Reinstall after a fresh clone

```bash
make install-hooks
```

Git hooks live in `.git/hooks/`, which is **not** tracked, so every clone starts without them. Run this once after cloning.

## Why a post-commit hook (and not alternatives)

| Option | Why not |
|---|---|
| `pre-push` hook | Doesn't auto-trigger — only fires when the user runs `git push`. |
| Git alias (`cp = !git commit && git push`) | User has to remember to use it. |
| GitHub Actions | Runs after push — doesn't solve the push step itself. |
| `core.hooksPath` to a tracked dir | Viable alternative; we went with an explicit `make install-hooks` to keep the install step visible. |

If you'd rather skip the install step, set once:

```bash
git config core.hooksPath scripts/git-hooks
```

Then every clone of this repo uses the tracked hooks directly. Trade-off: harder to override per-clone.

## Disabling

```bash
rm .git/hooks/post-commit
```

Or revert to sample:

```bash
mv .git/hooks/post-commit.sample .git/hooks/post-commit 2>/dev/null || true
```

## Safety notes

- The hook **never** force-pushes.
- It pushes to `origin` only — additional remotes are ignored.
- It does **not** push tags; tags still need an explicit `git push --tags`.
- Never combine auto-push with committing `.env` or other secrets. The `.gitignore` guards against the common cases; still eyeball `git status` before you commit.
