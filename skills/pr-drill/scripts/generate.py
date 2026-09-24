#!/usr/bin/env python3
"""Generate a local files-changed review from git diff.

Emits a self-contained HTML viewer (any browser) and/or a Cursor .canvas.tsx.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.server
import json
import os
import re
import subprocess
import sys
import time
import zlib
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
VIEWER_HTML = SCRIPT_DIR / "viewer.html"
CANVAS_TPL = SCRIPT_DIR / "canvas.tsx.tpl"
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


COMMAND_TIMEOUT_SECONDS = 30
WATCH_INTERVAL_SECONDS = 0.25
SERVE_POLL_SECONDS = 1.0


def run(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(
        args, cwd=cwd, text=True, timeout=COMMAND_TIMEOUT_SECONDS
    ).rstrip("\n")


def git_ok(args: list[str], cwd: Path) -> str | None:
    try:
        return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.DEVNULL).rstrip("\n")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def ref_exists(repo: Path, ref: str) -> bool:
    return git_ok(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], repo) is not None


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def remote_names(repo: Path) -> list[str]:
    raw = git_ok(["git", "remote"], repo)
    if not raw:
        return []
    names = [line.strip() for line in raw.splitlines() if line.strip()]
    preferred = [name for name in ("origin", "upstream") if name in names]
    rest = [name for name in names if name not in preferred]
    return preferred + rest


def primary_remote(repo: Path) -> str | None:
    names = remote_names(repo)
    return names[0] if names else None


def is_remote_ref(repo: Path, ref: str) -> bool:
    return any(ref.startswith(f"{name}/") for name in remote_names(repo))


def remote_counterpart(repo: Path, base: str) -> str | None:
    if re.fullmatch(r"[0-9a-f]{7,40}", base, re.I):
        return None
    if is_remote_ref(repo, base):
        return None
    remote = primary_remote(repo)
    if remote is None:
        return None
    return f"{remote}/{base}"


def prefer_closer_remote(repo: Path, base: str, head: str) -> str:
    """Use the remote-tracking ref when it is a closer ancestor of HEAD.

    A stale local main otherwise turns `git diff main...HEAD` into every commit
    that landed on the remote default after the local branch was last updated.
    """
    remote = remote_counterpart(repo, base)
    if remote is None or not ref_exists(repo, remote):
        return base
    if not ref_exists(repo, base):
        return remote

    mb_local = git_ok(["git", "merge-base", base, head], repo)
    mb_remote = git_ok(["git", "merge-base", remote, head], repo)
    if mb_remote and not mb_local:
        return remote
    if mb_local and not mb_remote:
        return base
    if not mb_local or not mb_remote:
        return base
    if mb_local == mb_remote:
        if is_ancestor(repo, base, remote) and not is_ancestor(repo, remote, base):
            return remote
        return base
    if is_ancestor(repo, mb_local, mb_remote):
        return remote
    if is_ancestor(repo, mb_remote, mb_local):
        return base
    return remote


INTEGRATION_NAMES = ("main", "master", "develop", "dev", "trunk")


def remote_head_ref(repo: Path) -> str | None:
    for remote in remote_names(repo):
        symbolic = git_ok(
            ["git", "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD"],
            repo,
        )
        if symbolic is not None and symbolic.startswith("refs/remotes/"):
            return symbolic.removeprefix("refs/remotes/")
    return None


def commits_ahead(repo: Path, base: str, head: str) -> int | None:
    merge_base = git_ok(["git", "merge-base", base, head], repo)
    if merge_base is None:
        return None
    count = git_ok(["git", "rev-list", "--count", f"{merge_base}..{head}"], repo)
    return int(count) if count is not None else None


def github_pr_base(repo: Path, head: str) -> str | None:
    args = ["gh", "pr", "view", "--json", "baseRefName", "--jq", ".baseRefName"]
    if head != "HEAD":
        args.append(head)
    try:
        raw = subprocess.check_output(
            args,
            cwd=repo,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=8,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return raw or None


def closest_integration_base(repo: Path, head: str) -> str | None:
    """Pick a well-known integration branch, not an arbitrary remote feature branch."""
    candidates: list[str] = []
    default = remote_head_ref(repo)
    if default:
        candidates.append(default)
    for name in INTEGRATION_NAMES:
        for remote in remote_names(repo):
            candidates.append(f"{remote}/{name}")
        candidates.append(name)

    best: str | None = None
    best_ahead: int | None = None
    seen: set[str] = set()
    for ref in candidates:
        if ref in seen or not ref_exists(repo, ref):
            continue
        seen.add(ref)
        ahead = commits_ahead(repo, ref, head)
        if ahead is None:
            continue
        remote_wins_tie = (
            best is not None
            and ahead == best_ahead
            and is_remote_ref(repo, ref)
            and not is_remote_ref(repo, best)
        )
        if best is None or ahead < best_ahead or remote_wins_tie:
            best = ref
            best_ahead = ahead
    return best


def guess_base(repo: Path, head: str) -> tuple[str, str]:
    pr_base = github_pr_base(repo, head)
    if pr_base:
        return prefer_closer_remote(repo, pr_base, head), "github-pr"
    integration = closest_integration_base(repo, head)
    if integration:
        chosen = prefer_closer_remote(repo, integration, head)
        if chosen == remote_head_ref(repo):
            return chosen, "remote-head"
        return chosen, "closest-integration"
    return "HEAD", "fallback-head"


def resolve_base(repo: Path, base: str | None, head: str) -> tuple[str, str]:
    if base:
        return prefer_closer_remote(repo, base, head), "explicit"
    return guess_base(repo, head)


def parse_diff(raw: str) -> list[dict]:
    files: list[dict] = []
    current: dict | None = None
    old_ln = new_ln = 0

    def flush() -> None:
        nonlocal current
        if current and current.get("path") and current["path"] != "/dev/null":
            adds = sum(1 for line in current["lines"] if line["type"] == "added")
            dels = sum(1 for line in current["lines"] if line["type"] == "removed")
            current["additions"] = adds
            current["deletions"] = dels
            files.append(current)
        current = None

    for line in raw.splitlines():
        if line.startswith("diff --git "):
            flush()
            current = {"path": "", "status": "modified", "lines": []}
            continue
        if current is None:
            continue
        if line.startswith("+++ b/") and not line.startswith("+++ b/dev/null"):
            current["path"] = line[6:]
            continue
        if line.startswith("--- a/") and line != "--- a/dev/null":
            if not current["path"]:
                current["path"] = line[6:]
            continue
        if line.startswith("new file mode"):
            current["status"] = "added"
            continue
        if line.startswith("deleted file mode"):
            current["status"] = "deleted"
            continue
        if line.startswith("@@"):
            match = HUNK_RE.match(line)
            if match:
                old_ln = int(match.group(1))
                new_ln = int(match.group(2))
                current["lines"].append(
                    {"type": "unchanged", "content": line, "lineNumber": new_ln}
                )
            continue
        if line.startswith(("index ", "--- ", "+++ ", "similarity ", "rename ", "\\")):
            continue
        if line.startswith("+"):
            current["lines"].append(
                {"type": "added", "content": line[1:], "lineNumber": new_ln}
            )
            new_ln += 1
        elif line.startswith("-"):
            current["lines"].append(
                {"type": "removed", "content": line[1:], "lineNumber": old_ln}
            )
            old_ln += 1
        else:
            content = line[1:] if line.startswith(" ") else line
            current["lines"].append(
                {"type": "unchanged", "content": content, "lineNumber": new_ln}
            )
            old_ln += 1
            new_ln += 1
    flush()
    return files


def repo_label(repo: Path) -> str:
    url = None
    for remote in remote_names(repo):
        url = git_ok(["git", "remote", "get-url", remote], repo)
        if url:
            break
    if url:
        cleaned = url.strip().rstrip("/")
        if cleaned.endswith(".git"):
            cleaned = cleaned[:-4]
        if "://" in cleaned:
            path = cleaned.split("://", 1)[1]
            parts = [part for part in path.split("/") if part]
            if len(parts) >= 2:
                return f"{parts[-2]}/{parts[-1]}"
        elif ":" in cleaned:
            path = cleaned.split(":", 1)[1]
            parts = [part for part in path.split("/") if part]
            if len(parts) >= 2:
                return f"{parts[-2]}/{parts[-1]}"
    return repo.name


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return cleaned or "head"


def cursor_canvases_dir(repo: Path) -> Path | None:
    explicit = os.environ.get("CURSOR_CANVASES_DIR")
    if explicit:
        return Path(explicit)
    projects = Path.home() / ".cursor" / "projects"
    if not projects.is_dir():
        return None
    resolved = repo.resolve()
    slug_name = str(resolved).lstrip("/").replace("/", "-")
    direct = projects / slug_name / "canvases"
    if direct.parent.is_dir():
        return direct
    name = resolved.name
    matches = [path / "canvases" for path in projects.iterdir() if path.name.endswith(name)]
    if len(matches) == 1:
        return matches[0]
    return None


CONVENTIONAL_SUBJECT = re.compile(
    r"^(feat|fix|refactor|docs|test|chore|ci|style|perf|build|revert)(\([^)]+\))?!?: \S"
)
SHORTSTAT_RE = re.compile(
    r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?"
)


def commit_flags(subject: str, *, include_type: bool) -> list[str]:
    flags: list[str] = []
    lowered = subject.lower()
    if lowered.startswith("fixup!") or lowered.startswith("squash!"):
        flags.append("fixup")
    if lowered.startswith("wip") or lowered.startswith("[wip]"):
        flags.append("wip")
    if include_type and not CONVENTIONAL_SUBJECT.match(subject):
        flags.append("no-type")
    if len(subject) > 72:
        flags.append("long-subject")
    return flags


def collect_commits(repo: Path, merge_base: str | None, head_ref: str) -> list[dict]:
    spec = f"{merge_base}..{head_ref}" if merge_base else head_ref
    raw = git_ok(
        ["git", "log", "--format=%H%x1f%h%x1f%s%x1f%an%x1f%aI%x1f%b%x1e", spec],
        repo,
    )
    if not raw:
        return []

    stats: dict[str, tuple[int, int, int]] = {}
    stats_raw = git_ok(["git", "log", "--format=%H", "--shortstat", spec], repo) or ""
    current_sha: str | None = None
    for line in stats_raw.splitlines():
        if re.fullmatch(r"[0-9a-f]{40}", line):
            current_sha = line
            continue
        match = SHORTSTAT_RE.search(line)
        if match and current_sha:
            stats[current_sha] = (
                int(match.group(1)),
                int(match.group(2) or 0),
                int(match.group(3) or 0),
            )

    commits: list[dict] = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        parts = record.split("\x1f", 5)
        while len(parts) < 6:
            parts.append("")
        sha, short, subject, author, date, body = parts
        files_n, adds, dels = stats.get(sha, (0, 0, 0))
        commits.append(
            {
                "sha": sha,
                "shortSha": short,
                "subject": subject,
                "body": body.strip("\n"),
                "author": author,
                "date": date,
                "files": files_n,
                "additions": adds,
                "deletions": dels,
                "flags": [],
            }
        )
    conventional = sum(1 for item in commits if CONVENTIONAL_SUBJECT.match(item["subject"]))
    include_type = conventional >= max(1, (len(commits) + 1) // 2)
    for item in commits:
        item["flags"] = commit_flags(item["subject"], include_type=include_type)
    return commits


def file_digest(lines: list[dict]) -> str:
    """Fingerprint a file's diff so reload can re-open files that changed since review."""
    digest = hashlib.sha256()
    for line in lines:
        digest.update(f"{line['type']}\x1f{line['content']}\x1e".encode())
    return digest.hexdigest()[:16]


def collect_payload(repo: Path, base_ref: str, head_ref: str) -> dict:
    branch = git_ok(["git", "rev-parse", "--abbrev-ref", head_ref], repo) or head_ref
    head_sha = run(["git", "rev-parse", "--short", head_ref], repo)
    base_sha = run(["git", "rev-parse", "--short", base_ref], repo)
    merge_base = git_ok(["git", "merge-base", base_ref, head_ref], repo)
    diff_base = merge_base or base_ref
    raw = run(["git", "diff", "-U3", diff_base], repo)
    files = parse_diff(raw)
    additions = sum(item["additions"] for item in files)
    deletions = sum(item["deletions"] for item in files)
    commits = collect_commits(repo, merge_base, head_ref)
    upstream = git_ok(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], repo)
    unpushed = True
    if upstream:
        counts = git_ok(["git", "rev-list", "--left-right", "--count", f"{upstream}...{head_ref}"], repo)
        if counts:
            ahead = int(counts.split()[1])
            unpushed = ahead > 0
    store_key = f"pr-drill:{repo.resolve()}:{base_ref}"
    return {
        "repo": repo_label(repo),
        "branch": branch,
        "base": base_ref,
        "baseSha": base_sha,
        "headSha": head_sha,
        "unpushed": unpushed,
        "dirty": bool(git_ok(["git", "status", "--porcelain"], repo)),
        "storeKey": store_key,
        "additions": additions,
        "deletions": deletions,
        "commits": commits,
        "files": [
            {
                "path": item["path"],
                "status": item["status"],
                "additions": item["additions"],
                "deletions": item["deletions"],
                "digest": file_digest(item["lines"]),
            }
            for item in files
        ],
        "diffs": {item["path"]: item["lines"] for item in files},
    }


def generated_at() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


def atomic_write_text(dest: Path, content: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    temporary.write_text(content)
    temporary.replace(dest)


def drill_meta(repo: Path, base_ref: str, head_ref: str, fmt: str) -> dict[str, str]:
    return {
        "repo": str(repo.resolve()),
        "base": base_ref,
        "head": head_ref,
        "format": fmt,
    }


def write_html(payload: dict, dest: Path, meta: dict[str, str]) -> None:
    template = VIEWER_HTML.read_text()
    payload = {
        **payload,
        "drillMeta": meta,
        "generatedAt": generated_at(),
    }
    encoded = json.dumps(payload).replace("<", "\\u003c")
    atomic_write_text(dest, template.replace("__PAYLOAD__", encoded))


def write_canvas(payload: dict, dest: Path, meta: dict[str, str]) -> None:
    source = CANVAS_TPL.read_text()
    replacements = {
        "__DRILL_META__": json.dumps(meta),
        "__GENERATED_AT__": json.dumps(generated_at()),
        "__REPO__": json.dumps(payload["repo"]),
        "__BRANCH__": json.dumps(payload["branch"]),
        "__BASE__": json.dumps(payload["base"]),
        "__BASE_SHA__": json.dumps(payload["baseSha"]),
        "__HEAD_SHA__": json.dumps(payload["headSha"]),
        "__UNPUSHED__": json.dumps(payload["unpushed"]),
        "__DIRTY__": json.dumps(payload["dirty"]),
        "__FILES__": json.dumps(payload["files"], indent=2),
        "__COMMITS__": json.dumps(payload["commits"], indent=2),
        "__DIFFS__": json.dumps(payload["diffs"]),
    }
    for token, value in replacements.items():
        source = source.replace(token, value)
    atomic_write_text(dest, source)


META_RE = re.compile(r"^const DRILL_META = (\{.*\});$", re.MULTILINE)


def read_viewer_meta(dest: Path) -> dict[str, str]:
    source = dest.read_text()
    if dest.name.endswith(".canvas.tsx"):
        match = META_RE.search(source)
        if match is None:
            raise ValueError(f"{dest} has no PR drill metadata; regenerate it first")
        value: Any = json.loads(match.group(1))
    else:
        payload_match = re.search(r"^\s*(?:const|let) DATA = (\{.*\});$", source, re.MULTILINE)
        if payload_match is None:
            raise ValueError(f"{dest} has no PR drill payload; regenerate it first")
        payload = json.loads(payload_match.group(1))
        value = payload.get("drillMeta")
    if not isinstance(value, dict) or not all(
        isinstance(value.get(key), str) for key in ("repo", "base", "head", "format")
    ):
        raise ValueError(f"{dest} has invalid PR drill metadata")
    return value


def refresh_viewer(dest: Path) -> dict:
    meta = read_viewer_meta(dest)
    repo = Path(meta["repo"])
    payload = collect_payload(repo, meta["base"], meta["head"])
    if meta["format"] == "canvas":
        write_canvas(payload, dest, meta)
    elif meta["format"] == "html":
        write_html(payload, dest, meta)
    else:
        raise ValueError(f"unsupported viewer format: {meta['format']}")
    return payload


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def claim_pid_file(pid_path: Path) -> bool:
    for _ in range(2):
        try:
            descriptor = os.open(pid_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                existing = int(pid_path.read_text().strip())
            except (FileNotFoundError, ValueError):
                existing = 0
            if existing and process_is_running(existing):
                return False
            try:
                pid_path.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(descriptor, "w") as handle:
            handle.write(str(os.getpid()))
        return True
    return False


def release_pid_file(pid_path: Path) -> None:
    try:
        if int(pid_path.read_text().strip()) == os.getpid():
            pid_path.unlink()
    except (FileNotFoundError, ValueError):
        pass


def canvas_sidecar(canvas: Path) -> Path:
    return canvas.with_suffix("").with_suffix(".canvas.data.json")


def watch_canvas(canvas: Path) -> int:
    meta = read_viewer_meta(canvas)
    repo = Path(meta["repo"])
    pid_path = repo / ".git" / f"pr-drill-{canvas.name.removesuffix('.canvas.tsx')}.watch.pid"
    if not claim_pid_file(pid_path):
        return 0
    sidecar = canvas_sidecar(canvas)
    last_mtime_ns = -1
    try:
        last_tick: Any = json.loads(sidecar.read_text()).get("pr-drill-reload-tick", 0)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        last_tick = 0
    try:
        while canvas.exists():
            try:
                mtime_ns = sidecar.stat().st_mtime_ns
                if mtime_ns != last_mtime_ns:
                    last_mtime_ns = mtime_ns
                    state = json.loads(sidecar.read_text())
                    tick = state.get("pr-drill-reload-tick", 0)
                    if tick != last_tick:
                        last_tick = tick
                        try:
                            refresh_viewer(canvas)
                        except (OSError, ValueError, subprocess.SubprocessError) as error:
                            print(f"refresh failed: {error}", file=sys.stderr)
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass
            time.sleep(WATCH_INTERVAL_SECONDS)
    finally:
        release_pid_file(pid_path)
    return 0


def serve_port(html: Path) -> int:
    return 49152 + zlib.crc32(str(html.resolve()).encode()) % (65535 - 49152)


def serve_html(html: Path) -> int:
    meta = read_viewer_meta(html)
    repo = Path(meta["repo"])
    stem = html.name.removesuffix(".html")
    pid_path = repo / ".git" / f"pr-drill-{stem}.serve.pid"
    if not claim_pid_file(pid_path):
        return 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/api/payload":
                try:
                    current_meta = read_viewer_meta(html)
                    payload = collect_payload(
                        Path(current_meta["repo"]),
                        current_meta["base"],
                        current_meta["head"],
                    )
                    body = json.dumps(
                        {
                            **payload,
                            "drillMeta": current_meta,
                            "generatedAt": generated_at(),
                        }
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    self.send_error(500, str(error))
                return
            if self.path in ("/", f"/{html.name}"):
                body = html.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)

        def log_message(self, format: str, *args: Any) -> None:
            return

    try:
        with http.server.ThreadingHTTPServer(("127.0.0.1", serve_port(html)), Handler) as server:
            server.timeout = SERVE_POLL_SECONDS
            while html.exists():
                server.handle_request()
    finally:
        release_pid_file(pid_path)
    return 0


def start_detached(mode: str, dest: Path) -> None:
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), mode, str(dest)],
        cwd=dest.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def default_stem(payload: dict) -> str:
    branch = payload["branch"].split("/")[-1]
    return f"PR-drill-{slug(branch)}"


def choose_formats(fmt: str, canvases: Path | None) -> list[str]:
    if fmt == "auto":
        return ["canvas"] if canvases is not None else ["html"]
    if fmt == "both":
        return ["canvas", "html"]
    return [fmt]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a local PR files-changed review.")
    runtime = parser.add_mutually_exclusive_group()
    runtime.add_argument("--refresh", metavar="PATH", help="Refresh an existing PR drill viewer")
    runtime.add_argument("--watch", metavar="CANVAS", help="Watch a canvas reload sidecar")
    runtime.add_argument("--serve", metavar="HTML", help="Serve an HTML viewer on localhost")
    parser.add_argument("--repo", default=".", help="Git repository root (default: cwd)")
    parser.add_argument(
        "--base",
        default=None,
        help="Base ref (default: GitHub PR base if gh is available, else remote HEAD or main/master/develop/dev/trunk)",
    )
    parser.add_argument("--head", default="HEAD", help="Head ref (default: HEAD)")
    parser.add_argument(
        "--format",
        choices=("auto", "canvas", "html", "both"),
        default="auto",
        help="auto: Cursor canvas when a canvases dir is found, else HTML",
    )
    parser.add_argument("--out", default=None, help="Output path (single format only)")
    parser.add_argument(
        "--name",
        default=None,
        help="Output filename stem, e.g. PR-drill-OAuth-SSO (casing is preserved)",
    )
    args = parser.parse_args()

    if args.refresh:
        try:
            payload = refresh_viewer(Path(args.refresh).resolve())
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print(json.dumps({"ok": True, "files": len(payload["files"]), "commits": len(payload["commits"])}))
        return 0
    if args.watch:
        try:
            return watch_canvas(Path(args.watch).resolve())
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    if args.serve:
        try:
            return serve_html(Path(args.serve).resolve())
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists() and git_ok(["git", "rev-parse", "--show-toplevel"], repo) is None:
        print("error: not a git repository", file=sys.stderr)
        return 1
    toplevel = git_ok(["git", "rev-parse", "--show-toplevel"], repo)
    if toplevel:
        repo = Path(toplevel)

    base_ref, base_reason = resolve_base(repo, args.base, args.head)
    payload = collect_payload(repo, base_ref, args.head)
    canvases = cursor_canvases_dir(repo)
    formats = choose_formats(args.format, canvases)
    if args.out and len(formats) > 1:
        print("error: --out requires a single --format (canvas or html)", file=sys.stderr)
        return 1

    stem = args.name or default_stem(payload)
    written: dict[str, str] = {}
    viewer_url: str | None = None
    for kind in formats:
        if kind == "canvas":
            dest = Path(args.out) if args.out else (canvases or repo) / f"{stem}.canvas.tsx"
            meta = drill_meta(repo, base_ref, args.head, "canvas")
            write_canvas(payload, dest, meta)
            start_detached("--watch", dest)
            written["canvas"] = str(dest)
        else:
            dest = Path(args.out) if args.out else repo / ".git" / f"{stem}.html"
            meta = drill_meta(repo, base_ref, args.head, "html")
            write_html(payload, dest, meta)
            start_detached("--serve", dest)
            viewer_url = f"http://127.0.0.1:{serve_port(dest)}/"
            written["html"] = str(dest)

    result = {
        "ok": True,
        "branch": payload["branch"],
        "base": payload["base"],
        "baseReason": base_reason,
        "files": len(payload["files"]),
        "commits": len(payload["commits"]),
        "additions": payload["additions"],
        "deletions": payload["deletions"],
        "canvasesDir": str(canvases) if canvases else None,
        "viewerUrl": viewer_url,
        **written,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
