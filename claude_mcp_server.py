#!/usr/bin/env python3
"""
Claude Code MCP Bridge for Antigravity 2.0 (claude_mcp_server.py)

Registered in Antigravity 2.0's ~/.gemini/config/mcp_config.json as `claude-code`,
allowing Antigravity 2.0 (and agy CLI) to directly invoke Claude Code via MCP.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "claude-code"
SERVER_VERSION = "1.0.0"


def find_claude_exe() -> str:
    which_claude = shutil.which("claude")
    if which_claude and os.path.exists(which_claude):
        return which_claude
    ext_dir = Path.home() / ".vscode" / "extensions"
    if ext_dir.exists():
        matches = sorted(ext_dir.glob("anthropic.claude-code-*/resources/native-binary/claude.exe"), reverse=True)
        if matches:
            return str(matches[0])
        matches_unix = sorted(ext_dir.glob("anthropic.claude-code-*/resources/native-binary/claude"), reverse=True)
        if matches_unix:
            return str(matches_unix[0])
    return "claude"


def tool_claude_status(_args: dict[str, Any]) -> dict[str, Any]:
    exe = find_claude_exe()
    exists = os.path.exists(exe) or bool(shutil.which(exe))
    version = ""
    if exists:
        try:
            proc = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=10)
            version = (proc.stdout or proc.stderr or "").strip()
        except Exception as e:
            version = f"Error: {e}"
    return {
        "claude_installed": exists,
        "claude_exe_path": exe,
        "version": version,
    }


def tool_claude_ask(args: dict[str, Any]) -> dict[str, Any]:
    prompt = args.get("prompt", "").strip()
    if not prompt:
        raise ValueError("'prompt' is required.")

    exe = find_claude_exe()
    cmd = [exe, "-p"]

    if args.get("model"):
        cmd.extend(["--model", str(args["model"]).strip()])
    if args.get("continue_last"):
        cmd.append("--continue")
    elif args.get("resume_session_id"):
        cmd.extend(["--resume", str(args["resume_session_id"]).strip()])
    if args.get("allowed_tools"):
        cmd.extend(["--allowedTools", str(args["allowed_tools"]).strip()])
    if args.get("append_system_prompt"):
        cmd.extend(["--append-system-prompt", str(args["append_system_prompt"]).strip()])
    if args.get("dangerously_skip_permissions"):
        cmd.append("--dangerously-skip-permissions")

    cmd.append(prompt)
    cwd = args.get("cwd") or None
    timeout_seconds = int(args.get("timeout_seconds", 180))

    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )
    return {
        "exit_code": proc.returncode,
        "response": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
        "command": cmd,
    }


TOOLS = [
    {
        "name": "claude_status",
        "description": "Check Claude Code CLI installation path and version.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "claude_ask",
        "description": "Send a prompt or task from Antigravity to Claude Code (via claude -p) and return Claude Code's response.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The prompt, question, or task to send to Claude Code.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory path for Claude Code.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model override for Claude Code (e.g. 'sonnet', 'opus').",
                },
                "continue_last": {
                    "type": "boolean",
                    "description": "Continue the most recent Claude Code conversation in the directory (-c / --continue). Defaults to false.",
                    "default": False,
                },
                "resume_session_id": {
                    "type": "string",
                    "description": "Optional session ID to resume (--resume).",
                },
                "allowed_tools": {
                    "type": "string",
                    "description": "Optional comma/space-separated list of tools to allow in Claude Code (e.g. 'Read,Glob,Grep').",
                },
                "append_system_prompt": {
                    "type": "string",
                    "description": "Optional extra system instructions to append.",
                },
                "dangerously_skip_permissions": {
                    "type": "boolean",
                    "description": "Bypass permission prompts in Claude Code print mode. Defaults to false.",
                    "default": False,
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Maximum seconds to wait for Claude Code response. Defaults to 180.",
                    "default": 180,
                },
            },
            "required": ["prompt"],
        },
    },
]

TOOL_HANDLERS = {
    "claude_status": tool_claude_status,
    "claude_ask": tool_claude_ask,
}


def handle_request(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if req_id is None:
        return None

    if method == "initialize":
        client_proto = params.get("protocolVersion", "2024-11-05")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_proto,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}

    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }
        try:
            res = handler(tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(res, indent=2, ensure_ascii=False)}],
                    "isError": False,
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error executing {tool_name}: {e}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        stripped = line.strip()
        if not stripped:
            continue
        try:
            msg = json.loads(stripped)
        except Exception:
            continue
        if isinstance(msg, dict):
            resp = handle_request(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
