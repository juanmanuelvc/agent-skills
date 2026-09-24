# agent-skills

Personal **Agent Skills** plus **push-blocking hooks** for AI coding agents.
One installable plugin for Cursor, Claude Code, and Codex — not dotfiles or a
project starter kit.

Skills live in a single `skills/` tree. Vendor manifests only point at that
tree; nothing here should be copied into individual project repos. Use each
project's own `AGENTS.md` only for rules the repo cannot reveal on its own.

## What's included

| Skill | Purpose |
|-------|---------|
| `git-workflow` | Protected `main`, trunk-based branches, worktrees; agents commit locally only |
| `pr-drill` | Local PR rehearsal viewer (canvas or HTML) before you push |
| `versioning` | Semver and git-cliff / release-please guidance |
| `handoff` | Session scratchpad under `../scratchpad/<project>/` (manual invoke) |

**Hooks** (`hooks/block-repo-push.py`): block agent `git push`, related
send-pack paths, `gh pr create`, and known MCP push tools. Wired for **Cursor**
and **Claude Code** via plugin manifests. **Codex** has no hook file — policy
is enforced through the `git-workflow` skill and product approvals.

## Layout

```text
skills/                 # single source of truth
hooks/                  # block-repo-push.py + cursor/claude hook JSON
.cursor-plugin/         # Cursor plugin + marketplace manifest
.claude-plugin/         # Claude Code plugin + marketplace manifest
.agents/plugins/        # Codex marketplace manifest
.codex-plugin/          # Codex compatibility manifest
plugin.json             # Agent Plugins portable manifest
```

## Install (recommended — skills + hooks)

Add this GitHub repo as a **marketplace** and install the **agent-skills**
plugin in each host you use:

- **Cursor:** Customize → add team/marketplace from git → install `agent-skills`
  (or test locally: copy/symlink into `~/.cursor/plugins/local/agent-skills` and
  reload). Hooks use `${CURSOR_PLUGIN_ROOT}` so they run from the installed
  plugin copy, not from the project you are editing.
- **Claude Code:** `/plugin marketplace add` (git URL to this repo) →
  `/plugin install agent-skills@agent-skills`
- **Codex:** `codex plugin marketplace add juanmanuelvc/agent-skills --sparse .agents/plugins`
  then install from the plugin browser (skills only; no push hook).

After publishing the repo publicly, replace `juanmanuelvc/agent-skills` with
your actual GitHub coordinates.

## Fallback (skills only — no hooks)

```bash
gh skill install juanmanuelvc/agent-skills --all \
  --agent cursor --agent codex --agent claude-code --scope user
gh skill update
```

This does **not** install push-blocking hooks. Use the marketplace/plugin path
above when you want enforcement in Cursor or Claude Code.

## Protected main

Treat `main` as protected after the initial bootstrap: agents work on
short-lived branches and commit locally; you push and open PRs from your own
terminal.

## License

MIT — see [LICENSE](LICENSE).
