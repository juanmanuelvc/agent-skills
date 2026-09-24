# PR drill

Local files-changed viewer for walking a branch diff before you push. No remote
pull request required.

## Install

**Recommended:** add the [agent-skills](https://github.com/juanmanuelvc/agent-skills)
marketplace in Cursor, Claude Code, or Codex and install the **agent-skills**
plugin (see the repo root `README.md`).

**Fallback (skills only):**

```bash
gh skill install juanmanuelvc/agent-skills --all \
  --agent cursor --agent codex --agent claude-code --scope user
gh skill update
```

That installs skill content into each host's skill paths; it does **not** install
push-blocking hooks.

## Requirements

- **Python 3** and **git**
- **`gh`** optional: used only to read an existing GitHub PR's base branch
- **Cursor** for the canvas view (`cursor/canvas` is built in, not a pip
  package). Without a workspace `canvases/` directory, the skill writes a
  self-contained HTML file instead.

## Use

Ask the agent to run a PR drill, or invoke `/pr-drill`. The generator lives at
`scripts/generate.py` next to `SKILL.md`:

```bash
python3 "$(dirname "$0")/../scripts/generate.py" --format auto --name "PR-drill-<topic>"
```

From a checkout of this repo, that path is `skills/pr-drill/scripts/generate.py`.

Omit `--base` unless you need to override. The generator uses the GitHub PR
base when `gh` can see one; otherwise it picks the closest well-known
integration branch (the primary remote's HEAD — `origin` or `upstream` — then
`main`, `master`, `develop`, `dev`, `trunk`), preferring a remote-tracking ref
over a stale local one. It will not pick an arbitrary feature branch.

`--format auto` writes a Cursor canvas when a `canvases/` directory exists,
otherwise a self-contained HTML file under `<repo>/.git/`. The Files view
compares the current working tree with the merge-base, so committed, staged,
and unstaged fixes appear. The newest-first commit timeline remains
`git log <merge-base>..HEAD`; working-tree changes are not fake commits.

The **Reload** button refreshes files, diffs, commits, and stats without
clearing reviewed checkboxes, notes, filters, search, or a selection that still
exists. One exception is deliberate: if a file you already reviewed has changed
since you checked it off, Reload returns it to **Pending** so the new changes
are not hidden behind a stale checkmark. Files you have not touched stay
reviewed, and notes are always kept. Canvas generation starts a detached watcher that observes the canvas
sidecar and rewrites only the generated `.canvas.tsx`. If that watcher has
stopped, Reload times out after about five seconds with a restart hint.

HTML generation starts a detached server on `127.0.0.1` and prints its
`viewerUrl`. Open that URL for Reload; a `file://` page cannot fetch refreshed
git data and shows a serve hint instead. Re-running the normal generation
command restarts a missing watcher/server. Existing generated viewers need one
regeneration to add Reload; canvas review state in the sidecar carries over.

For debugging:

```bash
python3 skills/pr-drill/scripts/generate.py --refresh /path/to/viewer
python3 skills/pr-drill/scripts/generate.py --watch /path/to/viewer.canvas.tsx
python3 skills/pr-drill/scripts/generate.py --serve /path/to/viewer.html
```

Conventional-commit `no type prefix` flags appear only when most commits in the
range already use that style.

Do not commit generated `.canvas.tsx` or HTML files.
