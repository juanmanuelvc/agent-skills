---
name: waypoint
description: Tracks multi-PR implementation from a scratchpad STATUS.md and PLAN.md. Use when the user says "status", pastes a PR handoff, or asks which slice chat to open next. Do not use it to implement product code.
---

# Waypoint

Scratchpad paths (repo directory name = `basename` of the git repo the chat is opened on):

- Status: `../scratchpad/<repo-dirname>/STATUS.md`
- Slice list: `../scratchpad/<repo-dirname>/PLAN.md`

If either file is missing, say so and stop. Read both files before answering.

## Status replies

Five lines or fewer: current slice, blocker, next slice name, branch name, and the one-sentence done-when copied from `PLAN.md`.

## Pasted handoff

Updates `STATUS.md` only (checkboxes, Completed, Blockers, Active Tasks). Do not rewrite `PLAN.md` unless the user says a slice boundary changed.

## Boundaries

- Do not edit the product repo. Do not design the next slice. Point at the next chat.
- If Blockers says the work is waiting on a published package or a human decision, the next slice stays closed. Record platform findings from the handoff under Blockers. Do not propose a local workaround.
