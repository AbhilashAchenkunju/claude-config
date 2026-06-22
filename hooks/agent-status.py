#!/usr/bin/env python3
"""Write a per-worktree Claude agent status file.

Invoked from ~/.claude/settings.json hooks:
    UserPromptSubmit -> agent-status.py working   (summary = the prompt)
    Stop             -> agent-status.py idle       (keeps last summary)
    Notification     -> agent-status.py blocked    (best-effort; CLI only)

Reads the hook payload as JSON on stdin (provides `cwd`, `session_id`,
`prompt`/`message`) and writes ~/.claude/agent-status/<sanitized-cwd>.json.

One file per worktree (keyed by cwd, overwritten in place) so the file count
stays bounded and concurrent agents in different worktrees never collide. The
Emacs *Agents* buffer just renders these files. Never raises: a failing hook
must not disrupt the agent, so everything is wrapped and we always exit 0.
"""
import json
import os
import subprocess
import sys
import time

STATUS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "agent-status")


def first_line(text, limit=120):
    """First non-empty line of TEXT, trimmed to LIMIT chars."""
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


def git_branch(cwd):
    """Branch name checked out in CWD's worktree, or a detached marker."""
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            branch = out.stdout.strip()
            if branch and branch != "HEAD":
                return branch
            short = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=3,
            )
            if short.returncode == 0 and short.stdout.strip():
                return "detached@" + short.stdout.strip()
            return "detached"
    except Exception:
        pass
    return ""


def main():
    state = sys.argv[1] if len(sys.argv) > 1 else "working"

    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    cwd = payload.get("cwd") or os.getcwd()
    os.makedirs(STATUS_DIR, exist_ok=True)
    key = cwd.replace(os.sep, "%")
    path = os.path.join(STATUS_DIR, key + ".json")

    # Load the existing record so summary survives across state changes
    # (a Stop should keep showing what the agent was last asked to do).
    record = {}
    try:
        with open(path) as fh:
            loaded = json.load(fh)
            if isinstance(loaded, dict):
                record = loaded
    except Exception:
        record = {}

    record.update({
        "cwd": cwd,
        "worktree": os.path.basename(cwd.rstrip(os.sep)) or cwd,
        "branch": git_branch(cwd),
        "session_id": payload.get("session_id") or record.get("session_id", ""),
        "state": state,
        "ts": time.time(),
    })

    if state == "working":
        prompt = (payload.get("prompt") or "").strip()
        if prompt:
            record["summary"] = first_line(prompt)
        record.pop("message", None)
    elif state == "blocked":
        record["message"] = (payload.get("message") or "Needs your input").strip()
    elif state == "idle":
        record.pop("message", None)

    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(record, fh)
    os.replace(tmp, path)  # atomic, so Emacs never reads a half-written file


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
