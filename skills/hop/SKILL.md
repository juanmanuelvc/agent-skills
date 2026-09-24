---
name: hop
description: Implements exactly one scratchpad PLAN.md slice in the product repo, then stops with a handoff. Use when the user names a slice, says "this PR only", or starts a chat whose first message is a slice name from PLAN.md.
---

# Hop

Scratchpad paths (repo directory name = `basename` of the git repo the chat is opened on):

- Status: `../scratchpad/<repo-dirname>/STATUS.md`
- Slice list: `../scratchpad/<repo-dirname>/PLAN.md`

If either file is missing, say so and stop. Read both files before starting.

## Slice selection

- Find the named slice. If the user did not name one, ask which slice. Do not start the following slice.
- If that slice is under Blockers, or an earlier slice in `PLAN.md` is still unchecked, stop and say what is blocking.

## Branch and scope

- Branch from the integration branch named in `STATUS.md`. Branch name: `feat/<slice-name>`.
- Implement only that slice's done-when. If a dependency's API cannot express the slice, stop and write the mismatch in the handoff. Do not wrap or reimplement that dependency.
- Do not deploy. Do not merge. Small commits on the slice branch. Open a PR into the integration branch when the user asks.

End every slice, finished or stopped, with this handoff and nothing after it:

## Handoff
- Slice:
- Branch:
- PR:
- Commits:
- Tests:
- Done-when met: yes/no
- Leftovers:
- Platform findings:

After the handoff block, tell the user to paste it into a **waypoint** chat so `STATUS.md` stays current.
