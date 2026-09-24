---
name: handoff
description: Write a session handoff scratchpad before resetting context or pausing long work. Use when the user asks for a handoff, context dump, or pause summary.
disable-model-invocation: true
---

# Handoff

For multi-PR slice work, end with **hop**'s `## Handoff` block and update progress via **waypoint** (`STATUS.md` / `PLAN.md`). Use this skill for non-slice work or mid-slice context dumps when context is full.

Before closing or resetting context:

- Determine the project name with `basename "$PWD"`.
- Run `mkdir -p ../scratchpad/<project-name>` if needed.
- Create `../scratchpad/<project-name>/handoff-<YYYY-MM-DD>.md` with:

1. **Session goal** — what we were trying to achieve.
2. **Changes made** — modified/created files with a one-line summary each.
3. **Current state** — what works, what doesn't, what is partial.
4. **Decisions made** — key design choices and rationale.
5. **Next steps** — pending tasks by priority.
6. **Critical context** — anything painful to reconstruct cold.
7. **Branch / goal file** — branch name and path to any active goal or contract file if applicable.

Format: Markdown. Be concise but omit nothing critical.
After writing, tell the user the path and a one-sentence summary of where you left off.
