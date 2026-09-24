---
name: pr-drill
description: >-
  Rehearse a pull request locally. Generates an interactive "PR drill" files-changed
  viewer from git diff against the integration branch so the user can walk the diff
  before pushing. Use when the user asks to review a branch, drill a PR, inspect a
  diff locally, walk files changed, or preview a merge without creating a remote
  pull request. For an existing GitHub PR URL, use pr-review-canvas instead.
---

# PR drill

Build a **files changed** viewer from the working tree against the merge-base.
This includes committed, staged, and unstaged changes; the commit timeline
continues to use `git log <merge-base>..HEAD`. Do not write review comments or
a verdict unless the user asks. The viewer is for the user to walk the diff
themselves.

## Do this

1. Read this file. Then **run** `scripts/generate.py` — do not reimplement the
   parser, HTML, or canvas UI. The script lives next to this SKILL.md; resolve
   `<skill-dir>` as the directory containing this file (not a hardcoded
   `~/.cursor/skills/pr-drill` path).
2. From the git repo root:

```bash
python3 <skill-dir>/scripts/generate.py \
  --format auto --name "PR-drill-<topic>"
```

   `<skill-dir>` is the directory that contains this SKILL.md. Omit `--base`
   unless the user named a target. The generator picks: GitHub PR base
   (`gh pr view`) if `gh` works; otherwise the well-known integration branch
   whose merge-base is closest to HEAD (the primary remote's HEAD, then
   `main` / `master` / `develop` / `dev` / `trunk`, preferring
   remote-tracking refs over a stale local ref). It does not scan every
   remote feature branch. `--base` overrides. The script prints JSON with
   `base` and `baseReason`.

3. **Naming.** `--name` sets the filename stem, and the Cursor canvas tab title
   is derived from it. Always start with `PR-drill-` and preserve acronym
   capitalization in the topic, lowercasing the rest. Example: branch
   `feat/add-oauth-sso` becomes `PR-drill-OAuth-SSO`. Omit `--name` only when
   the branch has no acronyms.

4. **Cursor (canvases dir found, `--format auto` → `canvas`):**
   - The script writes `<name>.canvas.tsx` into the workspace `canvases/`
     directory (`~/.cursor/projects/<workspace-slug>/canvases/`).
   - It also starts one detached watcher for that canvas. **Reload** increments
     a value in the canvas sidecar; the watcher re-reads git and atomically
     rewrites only the `.canvas.tsx` file. It never writes the sidecar.
   - Reply with a markdown link to that **absolute** `.canvas.tsx` path so it
     opens beside the chat (label like `PR drill`).
   - If `open_resource` is available, also open `file://<absolute-canvas-path>`.
   - Do not mkdir the canvases directory. If the write fails because the dir is
     missing, fall back to `--format html`.

5. **Any other harness (`--format auto` → `html`, or `--format html`):**
   - The script writes a self-contained HTML file (default:
     `<repo>/.git/<name>.html`).
   - It starts a detached localhost server. Reply with the generated
     `viewerUrl` (and the absolute HTML path). Reload works at the localhost
     URL; a directly opened `file://` copy explains how to restart the server.
     Do not dump the HTML into chat.

6. `--format both` writes canvas (if possible) plus HTML. Use that when the
   user wants a file they can open outside Cursor.

## UX to preserve

The generator already implements this. Do not restyle it:

- Header: `PR drill`, then a muted repo line (`owner/name` from origin, else
  the directory name), then the head branch chip, `into`, the base branch chip,
  the sha range, and `· not pushed` when the branch is ahead of its upstream.
- Stats: `Files`, `Commits`, `Lines vs <base>` (green `+N` / red `−N`). Files
  view also shows `Reviewed` / `Pending`. Commits view shows `Flagged messages`.
- View toggle: **Files** (default) / **Commits**. Files is the working tree
  versus merge-base. Commits is `git log <merge-base>..HEAD` for sequence,
  count, and message review — not a filter on the file diff.
- Path search on its own row (Files view).
- One filter line (Files view): **Change type** left (`All` / `Added` /
  `Modified` / `Deleted` if count > 0, pick one); **Review state** right
  (`Reviewed` / `Pending`, mutually exclusive; click the active chip to
  clear and show both).
- Commits view: newest-first timeline with `<sha> · <subject>`, author and
  date. Hover or keyboard focus reveals body, stats, and light flags
  (`fixup leftover`, `WIP`, `no type prefix`, `subject > 72`). `no type prefix`
  is only shown when most commits in the range already look like Conventional
  Commits. Branch commits use accent-filled nodes; a hollow neutral node
  anchors the bottom as `Branched from <base>`. Flags are hints, not a linter
  verdict.
- Default-size pills (not `sm`).
- Reviewed checkboxes and per-file notes persist locally (canvas state or
  `localStorage`). They are never committed.
- Keep the currently open file selected even if filters hide it.
- **Reload** replaces files, diffs, commits, and stats while preserving
  path-keyed reviewed state, notes, selection when that path still exists,
  filters, search, and view mode.
- A reviewed file whose diff changed since it was marked goes back to
  **Pending**, so new changes are never hidden behind an old checkmark. This
  compares a per-file digest of the diff, so untouched files stay reviewed.
  Files reviewed before digests existed adopt the current digest rather than
  being reopened in bulk. Notes are kept either way.
- If a canvas watcher dies, Reload recovers after about five seconds and shows
  a hint to re-run `generate.py`. Existing generated viewers need one
  regeneration to gain Reload; their sidecar review state carries over.

## Defaults

| Flag | Default |
|------|---------|
| `--base` | omitted: GitHub PR base if `gh` works, else closest of remote HEAD / `main` / `master` / `develop` / `dev` / `trunk` |
| `--head` | `HEAD` |
| `--format` | `auto` |
| `--name` | `PR-drill-<branch>` |

Do not add generated HTML or canvas files to git.

For debugging, `--refresh <viewer>` performs one refresh, `--watch <canvas>`
runs the canvas watcher in the foreground, and `--serve <html>` runs the HTML
server in the foreground.

## Portable HTML

`scripts/viewer.html` is a single file, no build, no npm. Open it in any
browser. Cursor canvas (`scripts/canvas.tsx.tpl`) is Cursor-only
(`cursor/canvas`). Keep both generated from the same parsed diff in
`generate.py`.
