---
name: versioning
description: Use this skill when bumping versions, generating or updating a CHANGELOG, tagging releases, or advising on semantic versioning for a project.
---

# Versioning

## Semantic Versioning (semver)

Format: `MAJOR.MINOR.PATCH`

| Bump | When |
|---|---|
| `MAJOR` | Breaking change — existing consumers must update their code |
| `MINOR` | New backwards-compatible feature |
| `PATCH` | Backwards-compatible bug fix or chore |

Pre-release: `1.0.0-alpha.1`, `2.0.0-rc.1`. Use sparingly.

A version of `0.x.y` signals the public API is not yet stable — breaking changes are allowed on `MINOR` bumps.

## Deciding the next version

Look at all commits since the last tag:
- Any `feat` → at least `MINOR` bump
- Any `!` suffix or `BREAKING CHANGE` footer → `MAJOR` bump
- Only `fix`, `chore`, `docs`, `refactor`, `test`, `perf` → `PATCH` bump

## Choosing a release tool

| Situation | Recommended tool |
|---|---|
| Default — personal projects, no published artifacts | `git-cliff` + GitHub Action |
| Projects that publish artifacts (npm, pip, Docker) | `release-please` |

---

## Option A — git-cliff (default)

Best for personal projects and repos that don't publish artifacts.

**Requires:** `git-cliff` installed. See https://git-cliff.org/docs/installation for instructions.

### With GitHub Actions CI (recommended)

Add `cliff.toml` and a workflow that runs on tag push (for example `.github/workflows/changelog.yml` in the project repo). When you push a tag, the action regenerates `CHANGELOG.md` and commits it back automatically.

**Release workflow:**
```bash
git cliff --unreleased
git tag v1.2.0
git push origin main v1.2.0
```

### Without CI

```bash
git cliff --unreleased
git cliff --tag v1.2.0 -o CHANGELOG.md
git add CHANGELOG.md
git commit -m "chore: release v1.2.0"
git tag v1.2.0
git push origin main v1.2.0
```

---

## Option B — release-please (GitHub Action)

Use only for projects that publish artifacts and want a fully automated release pipeline.

1. On every merge to `main`, the action creates or updates a Release PR.
2. Merge the Release PR to cut the tag and GitHub Release.

**Setup** — create `.github/workflows/release-please.yml`:
```yaml
on:
  push:
    branches: [main]

permissions:
  contents: write
  pull-requests: write

jobs:
  release-please:
    runs-on: ubuntu-latest
    steps:
      - uses: googleapis/release-please-action@v4
        with:
          release-type: node   # or: python, go, rust, simple …
```

---

## Rules

- Never skip a version number.
- Tags are immutable — do not move or delete a published tag.
- Without CI: commit `CHANGELOG.md` in the same commit as the version bump.
- With CI (git-cliff action): `CHANGELOG.md` is committed by the action after the tag — this is expected.
- `0.0.x` versions are reserved for initial unstable work before the first real release.
