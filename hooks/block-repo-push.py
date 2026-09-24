#!/usr/bin/env python3
"""Deny agent actions that push changes to remote repositories (Cursor + Claude Code)."""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

USER_MESSAGE = (
    "Blocked: agents are not allowed to push changes to repositories. "
    "Push from your own terminal if you want these commits published."
)
AGENT_MESSAGE = (
    "A push-blocking hook denied this action because it would publish "
    "changes to a remote repository. Do not retry with git push, "
    "git send-pack, gh pr create, gh repo create --push, or MCP push "
    "tools. Continue with local commits only; the user must push."
)

SHELLS_WITH_DASH_C = {
    "bash",
    "dash",
    "fish",
    "ksh",
    "sh",
    "zsh",
}
WRAPPERS = {
    "chronic",
    "command",
    "eatmydata",
    "env",
    "exec",
    "nice",
    "nohup",
    "script",
    "stdbuf",
    "sudo",
    "time",
    "timeout",
    "unbuffer",
}
GIT_VALUE_OPTS = {
    "--attr-source",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--list-cmds",
    "--namespace",
    "--super-prefix",
    "--work-tree",
    "-C",
    "-c",
}
GH_VALUE_OPTS = {
    "--dir",
    "--hostname",
    "--repo",
    "-R",
    "-h",
}
BLOCKED_MCP_TOOLS = {
    "commit_files",
    "create_commit",
    "create_or_update_file",
    "create_or_update_files",
    "push_file",
    "push_files",
    "push_to_remote",
    "update_file_contents",
}


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.write("\n")


def is_claude_payload(data: dict[str, Any]) -> bool:
    return str(data.get("hook_event_name") or "") == "PreToolUse"


def deny(data: dict[str, Any]) -> int:
    if is_claude_payload(data):
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": AGENT_MESSAGE,
                }
            }
        )
        return 0
    emit(
        {
            "permission": "deny",
            "user_message": USER_MESSAGE,
            "agent_message": AGENT_MESSAGE,
        }
    )
    return 0


def allow(data: dict[str, Any]) -> int:
    if is_claude_payload(data):
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            }
        )
        return 0
    emit({"permission": "allow"})
    return 0


def cmd_name(token: str) -> str:
    name = Path(token).name
    if name.endswith(".exe"):
        name = name[:-4]
    return name.lower()


def split_shell_segments(command: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    i = 0
    length = len(command)

    def flush() -> None:
        text = "".join(current).strip()
        current.clear()
        if text:
            segments.append(text)

    while i < length:
        ch = command[i]
        if quote:
            current.append(ch)
            if ch == quote and (i == 0 or command[i - 1] != "\\"):
                quote = None
            i += 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            current.append(ch)
            i += 1
            continue
        if command.startswith("&&", i) or command.startswith("||", i):
            flush()
            i += 2
            continue
        if ch in {";", "|", "&", "\n"}:
            flush()
            i += 1
            continue
        current.append(ch)
        i += 1
    flush()
    return segments


def extract_substitutions(command: str) -> list[str]:
    found: list[str] = []
    i = 0
    length = len(command)
    while i < length:
        if command.startswith("$(", i):
            depth = 1
            j = i + 2
            while j < length and depth:
                if command.startswith("$(", j):
                    depth += 1
                    j += 2
                    continue
                if command[j] == ")":
                    depth -= 1
                    j += 1
                    continue
                j += 1
            found.append(command[i + 2 : j - 1])
            i = j
            continue
        if command[i] == "`":
            j = i + 1
            while j < length and command[j] != "`":
                j += 1
            found.append(command[i + 1 : j])
            i = j + 1
            continue
        i += 1
    return found


def tokenize(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def skip_wrapper_args(name: str, tokens: list[str], index: int) -> int:
    i = index
    if name == "env":
        while i < len(tokens) and tokens[i].startswith("-"):
            opt = tokens[i]
            i += 1
            if opt in {"-u", "-C"} and i < len(tokens):
                i += 1
        while i < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]):
            i += 1
        return i
    if name == "timeout":
        while i < len(tokens) and tokens[i].startswith("-"):
            i += 1
        if i < len(tokens) and re.match(r"^\d", tokens[i]):
            i += 1
        return i
    if name == "sudo":
        while i < len(tokens) and tokens[i].startswith("-"):
            opt = tokens[i]
            i += 1
            key = opt.split("=", 1)[0]
            if key in {"-u", "-g", "-C", "-p"} and "=" not in opt and i < len(tokens):
                i += 1
        return i
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 1
    return i


def git_args_push(args: list[str]) -> bool:
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            i += 1
            break
        if not token.startswith("-"):
            break
        key = token.split("=", 1)[0]
        if "=" in token:
            i += 1
            continue
        if key in GIT_VALUE_OPTS:
            i += 2
            continue
        i += 1
    if i >= len(args):
        return False
    subcommand = args[i].lower()
    if subcommand in {"push", "send-pack"}:
        return True
    if subcommand == "lfs":
        return git_lfs_args_push(args[i + 1 :])
    return False


def git_lfs_args_push(args: list[str]) -> bool:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 1
    return i < len(args) and args[i].lower() == "push"


def skip_gh_globals(args: list[str]) -> list[str]:
    i = 0
    while i < len(args):
        token = args[i]
        if not token.startswith("-"):
            break
        key = token.split("=", 1)[0]
        if "=" in token:
            i += 1
            continue
        if key in GH_VALUE_OPTS:
            i += 2
            continue
        i += 1
    return args[i:]


def gh_args_push(args: list[str]) -> bool:
    rest = skip_gh_globals(args)
    if len(rest) >= 2 and rest[0] == "pr" and rest[1] == "create":
        return True
    if len(rest) >= 2 and rest[0] == "repo" and rest[1] == "create":
        return any(arg == "--push" or arg.startswith("--push=") for arg in rest[2:])
    return False


def tokens_push(tokens: list[str]) -> bool:
    i = 0
    while i < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*\+?=", tokens[i]):
        i += 1

    while i < len(tokens):
        name = cmd_name(tokens[i])
        if name not in WRAPPERS:
            break
        i = skip_wrapper_args(name, tokens, i + 1)

    if i >= len(tokens):
        return False

    name = cmd_name(tokens[i])
    rest = tokens[i + 1 :]

    if name in SHELLS_WITH_DASH_C:
        return shell_invocation_pushes(rest)
    if name in {"eval", "xargs", "watch"}:
        return tokens_push(rest) or command_pushes(" ".join(rest))
    if name == "git":
        return git_args_push(rest)
    if name == "git-lfs":
        return git_lfs_args_push(rest)
    if name == "gh":
        return gh_args_push(rest)
    if name == "hub":
        return "push" in {cmd_name(token) for token in rest}
    return False


def shell_invocation_pushes(args: list[str]) -> bool:
    i = 0
    script: str | None = None
    while i < len(args):
        token = args[i]
        if token in {"-c", "--command"} and i + 1 < len(args):
            script = args[i + 1]
            break
        if token.startswith("-"):
            i += 1
            continue
        break
    if script is None:
        return False
    return command_pushes(script)


def command_pushes(command: str | None) -> bool:
    if not command or not str(command).strip():
        return False
    text = str(command)
    if any(command_pushes(part) for part in extract_substitutions(text)):
        return True
    return any(tokens_push(tokenize(segment)) for segment in split_shell_segments(text))


def normalize_mcp_tool_name(name: str) -> str:
    text = name.strip().lower()
    if text.startswith("mcp:"):
        text = text[4:].strip()
    if text.startswith("mcp__"):
        text = text[5:]
    text = text.replace("\\", "/")
    text = text.split("/")[-1]
    text = text.split(".")[-1]
    if "__" in text:
        text = text.split("__")[-1]
    return text


def mcp_tool_pushes(name: str | None) -> bool:
    if not name:
        return False
    normalized = normalize_mcp_tool_name(name)
    if normalized in BLOCKED_MCP_TOOLS:
        return True
    return normalized.endswith("_push_files") or normalized.endswith("_push_file")


def is_mcp_payload(data: dict[str, Any]) -> bool:
    event = str(data.get("hook_event_name") or "")
    if event in {"beforeMCPExecution", "afterMCPExecution"}:
        return True
    tool_name = str(data.get("tool_name") or "")
    if tool_name.startswith("MCP:"):
        return True
    if tool_name.lower().startswith("mcp__"):
        return True
    return bool(data.get("mcp_server_name"))


def extract_shell_command(data: dict[str, Any]) -> str | None:
    if is_mcp_payload(data):
        return None
    tool_name = str(data.get("tool_name") or "")
    if tool_name in {"Shell", "shell", "Bash"}:
        tool_input = data.get("tool_input")
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except json.JSONDecodeError:
                return tool_input
        if isinstance(tool_input, dict):
            for key in ("command", "cmd"):
                value = tool_input.get(key)
                if isinstance(value, str):
                    return value
        return None
    command = data.get("command")
    if isinstance(command, str):
        return command
    return None


def should_block(data: dict[str, Any]) -> bool:
    if mcp_tool_pushes(str(data.get("tool_name") or "") or None):
        return True
    return command_pushes(extract_shell_command(data))


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return deny({})
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return deny({})
    if not isinstance(data, dict):
        return deny({})
    if should_block(data):
        return deny(data)
    return allow(data)


if __name__ == "__main__":
    raise SystemExit(main())
