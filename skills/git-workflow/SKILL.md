---
name: git-workflow
description: Use this skill for git operations — branches, worktrees, rebasing, resolving conflicts, or preparing work to merge. Agents commit locally only; the user publishes from their own terminal.
---

# Git Workflow

## Protected main

- `main` (or `master`) is always releasable and **protected**.
- Never commit, push, merge, or rebase onto `main` from an agent session.
- Merge happens only via GitHub PR after human review and confirmation.

## Push and publish (agents)

- Agents **commit locally** when the user asks (or when a skill requires it).
- Agents do **not** run `git push`, `git send-pack`, or push-related git-lfs commands.
- Agents do **not** run `gh pr create`, `gh repo create --push`, or MCP tools that push to remotes.
- If a hook denies publish actions, **do not retry** — continue with local commits only.
- The **user** pushes branches, opens PRs, and merges from their own terminal.

## Branch flow (trunk-based)

No persistent integration branches (`develop`, `agent`, etc.).
One logical change per short-lived branch.

1. Update and branch from `main`:
   ```bash
   git fetch origin
   git checkout -b type/scope/slug origin/main
   ```
2. Naming: `type/scope/slug` — e.g. `feat/auth/oauth-login`, `fix/cart/dupe-items`.
   Scope optional: `feat/oauth-login`.
3. Before the user opens a PR: rebase onto latest `origin/main` on the **feature branch only** (local commits).
4. After merge: delete the remote branch; remove any worktree.

## Worktrees

Prefer a worktree for multi-step or parallel work:

```bash
git worktree add -b feat/<slug> ../<project>-<slug> origin/main
```

Cleanup after merge:

```bash
git worktree remove ../<project>-<slug>
```

## Commits

Use Conventional Commits (one line, no `Co-Authored-By` trailer unless the user asks).
Stage only relevant files; never skip hooks unless the user explicitly requests it.

## Pull requests

Keep PRs small; link issues with `Closes #N` when applicable.
The user creates and merges PRs — use `pr-drill` to rehearse the diff locally first if helpful.

## Conflict resolution

1. Understand both sides before resolving.
2. Prefer the version that matches the project's current direction.
3. If unsure, ask — do not guess.
4. After resolving, run tests before continuing.

## Useful one-liners

```bash
git rebase origin/main          # on feature branch only
git reset --soft HEAD~1         # undo last commit, keep staged
git diff HEAD~1 --name-only
git stash -u
```
