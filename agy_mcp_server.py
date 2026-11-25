#!/usr/bin/env python3
"""
Antigravity <-> Claude Code MCP Server (agy_mcp_server.py)

Provides Model Context Protocol (MCP) tools that allow Claude Code to:
1. Directly interact with the running Antigravity 2.0 Desktop App via `agentapi`:
   - Start new conversations in the Antigravity 2.0 UI (`agy_app_new_conversation`)
   - Send messages to existing conversations in the Antigravity 2.0 UI (`agy_app_send_message`)
   - List recent conversations and their live status (`agy_app_list_conversations`)
   - Read full conversation transcripts & artifacts (`agy_app_get_conversation`)
   - List configured Antigravity 2.0 projects (`agy_app_list_projects`)
   - Check live connection status (`agy_app_status`)
2. Directly invoke the Antigravity CLI (`agy.exe`):
   - Run non-interactive prompts with model/effort/mode selection (`agy_cli_ask`)
   - List all available AI models (`agy_cli_list_models`)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SERVER_NAME = "antigravity"
SERVER_VERSION = "1.0.0"

BRIDGE_DIR = Path(__file__).resolve().parent
BRIDGE_ENV_FILE = BRIDGE_DIR / "bridge_env.json"

HOME = Path.home()
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", str(HOME / "AppData" / "Local")))
DEFAULT_AGENTAPI_EXE = str(LOCAL_APPDATA / "Programs" / "antigravity" / "resources" / "bin" / "language_server.exe")
DEFAULT_APP_DATA_DIR = str(HOME / ".gemini" / "antigravity")
DEFAULT_CONFIG_DIR = str(HOME / ".gemini" / "config")
DEFAULT_AGY_CLI_EXE = str(LOCAL_APPDATA / "agy" / "bin" / "agy.exe")

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
UUID_SEARCH_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
TITLE_PBTXT_RE = re.compile(r'title:\s*"((?:[^"\\]|\\.)*)"')


def load_bridge_env() -> dict[str, Any]:
    data: dict[str, Any] = {}
    if BRIDGE_ENV_FILE.exists():
        try:
            data = json.loads(BRIDGE_ENV_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    for k in [
        "ANTIGRAVITY_LS_ADDRESS",
        "ANTIGRAVITY_CSRF_TOKEN",
        "ANTIGRAVITY_AGENTAPI_EXE",
        "ANTIGRAVITY_APP_DATA_DIR",
        "ANTIGRAVITY_PROJECT_ID",
        "ANTIGRAVITY_CONVERSATION_ID",
    ]:
        if os.environ.get(k):
            data[k] = os.environ[k]

    if not data.get("ANTIGRAVITY_AGENTAPI_EXE"):
        data["ANTIGRAVITY_AGENTAPI_EXE"] = DEFAULT_AGENTAPI_EXE
    if not data.get("ANTIGRAVITY_APP_DATA_DIR"):
        data["ANTIGRAVITY_APP_DATA_DIR"] = DEFAULT_APP_DATA_DIR
    if not data.get("AGY_CLI_EXE"):
        if os.path.exists(DEFAULT_AGY_CLI_EXE):
            data["AGY_CLI_EXE"] = DEFAULT_AGY_CLI_EXE
        else:
            which_agy = shutil.which("agy")
            data["AGY_CLI_EXE"] = which_agy or DEFAULT_AGY_CLI_EXE
    return data


def get_app_data_dir() -> Path:
    b = load_bridge_env()
    return Path(b.get("ANTIGRAVITY_APP_DATA_DIR", DEFAULT_APP_DATA_DIR))


def resolve_project_id(project_id_or_name: str | None) -> str | None:
    if not project_id_or_name:
        return None
    val = project_id_or_name.strip()
    if not val:
        return None
    if UUID_RE.match(val) or val == "outside-of-project":
        return val
    # Try matching project name or folder name from ~/.gemini/config/projects/*.json
    projects_dir = Path(DEFAULT_CONFIG_DIR) / "projects"
    if projects_dir.exists():
        val_lower = val.lower()
        for p in projects_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                pid = data.get("id", p.stem)
                pname = str(data.get("name", "")).strip()
                if pname.lower() == val_lower or pid.lower() == val_lower:
                    return pid
                resources = (data.get("projectResources") or {}).get("resources") or []
                for r in resources:
                    uri = urllib.parse.unquote(r.get("folderUri", ""))
                    if uri.lower().endswith("/" + val_lower) or uri.lower().endswith("\\" + val_lower):
                        return pid
            except Exception:
                pass
    return val


def run_agentapi(args: list[str], project_id: str | None = None, timeout: int = 30) -> dict[str, Any]:
    b = load_bridge_env()
    exe = b.get("ANTIGRAVITY_AGENTAPI_EXE", DEFAULT_AGENTAPI_EXE)
    if not os.path.exists(exe):
        raise RuntimeError(f"Antigravity language_server executable not found at: {exe}")

    ls_addr = b.get("ANTIGRAVITY_LS_ADDRESS")
    csrf = b.get("ANTIGRAVITY_CSRF_TOKEN")
    if not ls_addr or not csrf:
        raise RuntimeError(
            "Missing ANTIGRAVITY_LS_ADDRESS or ANTIGRAVITY_CSRF_TOKEN in bridge_env.json. "
            "Please open or run a prompt in the Antigravity 2.0 Desktop App so the session hook syncs the token."
        )

    env = os.environ.copy()
    env["ANTIGRAVITY_LS_ADDRESS"] = str(ls_addr)
    env["ANTIGRAVITY_CSRF_TOKEN"] = str(csrf)
    env["ANTIGRAVITY_AGENTAPI_EXE"] = str(exe)
    resolved_pid = resolve_project_id(project_id)
    if resolved_pid:
        env["ANTIGRAVITY_PROJECT_ID"] = str(resolved_pid)
    elif b.get("ANTIGRAVITY_PROJECT_ID"):
        env["ANTIGRAVITY_PROJECT_ID"] = str(b["ANTIGRAVITY_PROJECT_ID"])

    cmd = [exe, "agentapi", *args]
    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0:
        err_msg = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"agentapi failed (exit {proc.returncode}): {err_msg}")

    out = (proc.stdout or "").strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except Exception:
        return {"raw_output": out}


def extract_conversation_id(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for k in ("conversationId", "conversation_id", "id"):
            val = obj.get(k)
            if isinstance(val, str) and UUID_RE.match(val):
                return val
        for v in obj.values():
            found = extract_conversation_id(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = extract_conversation_id(item)
            if found:
                return found
    elif isinstance(obj, str):
        m = UUID_SEARCH_RE.search(obj)
        if m:
            return m.group(0)
    return None


def get_conversation_title(app_data: Path, conv_id: str) -> str:
    pbtxt = app_data / "annotations" / f"{conv_id}.pbtxt"
    if pbtxt.exists():
        try:
            text = pbtxt.read_text(encoding="utf-8", errors="replace")
            m = TITLE_PBTXT_RE.search(text)
            if m:
                return m.group(1).encode("utf-8").decode("unicode_escape", errors="replace")
        except Exception:
            pass
    return ""


def read_transcript_lines(app_data: Path, conv_id: str) -> tuple[list[dict[str, Any]], Path, Path]:
    logs_dir = app_data / "brain" / conv_id / ".system_generated" / "logs"
    compact_path = logs_dir / "transcript.jsonl"
    full_path = logs_dir / "transcript_full.jsonl"
    if not compact_path.exists():
        return [], compact_path, full_path

    steps: list[dict[str, Any]] = []
    try:
        raw_lines = compact_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return [], compact_path, full_path

    full_lines: list[str] | None = None

    for idx, line in enumerate(raw_lines):
        line = line.strip()
        if not line:
            continue
        try:
            step = json.loads(line)
        except Exception:
            continue
        if not isinstance(step, dict):
            continue

        trunc = step.get("truncated_fields")
        if isinstance(trunc, list) and ("content" in trunc or "thinking" in trunc) and full_path.exists():
            if full_lines is None:
                try:
                    full_lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
                except Exception:
                    full_lines = []
            if idx < len(full_lines):
                try:
                    full_step = json.loads(full_lines[idx])
                    if isinstance(full_step, dict):
                        step = full_step
                except Exception:
                    pass
        steps.append(step)
    return steps, compact_path, full_path


def is_turn_idle(steps: list[dict[str, Any]]) -> tuple[bool, str, str]:
    if not steps:
        return False, "", ""

    for i in range(len(steps) - 1, -1, -1):
        step = steps[i]
        stype = step.get("type", "")
        status = step.get("status", "")
        if stype == "ERROR_MESSAGE":
            return True, "", str(step.get("error") or step.get("content") or "Model error")
        if stype == "GENERIC":
            return False, "", ""
        if stype == "USER_INPUT":
            return False, "", ""
        if stype == "PLANNER_RESPONSE":
            calls = step.get("tool_calls") or []
            if len(calls) == 0 and status == "DONE":
                return True, str(step.get("content") or ""), ""
            return False, "", ""
    return False, "", ""


def wait_for_conversation_turn(
    app_data: Path,
    conv_id: str,
    baseline_step_count: int,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    saw_new_step = False

    while time.time() < deadline:
        steps, _, _ = read_transcript_lines(app_data, conv_id)
        if len(steps) > baseline_step_count:
            saw_new_step = True
            new_steps = steps[baseline_step_count:]
            has_planner = any(s.get("type") == "PLANNER_RESPONSE" for s in new_steps)
            if has_planner:
                idle, reply, err = is_turn_idle(steps)
                if idle:
                    return {
                        "completed": True,
                        "conversation_id": conv_id,
                        "reply": reply,
                        "error": err,
                        "total_steps": len(steps),
                    }
        time.sleep(1.0)

    steps, _, _ = read_transcript_lines(app_data, conv_id)
    _, partial_reply, err = is_turn_idle(steps)
    return {
        "completed": False,
        "timed_out": True,
        "saw_new_step": saw_new_step,
        "conversation_id": conv_id,
        "partial_reply": partial_reply,
        "error": err,
        "total_steps": len(steps),
        "note": f"Turn still running after {timeout_seconds}s. Use agy_app_get_conversation with conversation_id='{conv_id}' to fetch the result.",
    }


def find_newest_conversation_since(app_data: Path, before_ids: set[str], start_time: float, timeout: float = 10.0) -> str | None:
    brain_dir = app_data / "brain"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if brain_dir.exists():
            candidates: list[tuple[float, str]] = []
            for d in brain_dir.iterdir():
                if d.is_dir() and UUID_RE.match(d.name):
                    if d.name not in before_ids:
                        candidates.append((d.stat().st_mtime, d.name))
            if candidates:
                candidates.sort(reverse=True)
                return candidates[0][1]
        time.sleep(0.4)
    return None


def get_most_recent_conversation_id(app_data: Path) -> str | None:
    b = load_bridge_env()
    brain_dir = app_data / "brain"
    if brain_dir.exists():
        candidates: list[tuple[float, str]] = []
        for d in brain_dir.iterdir():
            if not (d.is_dir() and UUID_RE.match(d.name)):
                continue
            tr = d / ".system_generated" / "logs" / "transcript.jsonl"
            mtime = tr.stat().st_mtime if tr.exists() else d.stat().st_mtime
            candidates.append((mtime, d.name))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]
    return b.get("ANTIGRAVITY_CONVERSATION_ID")


# ============================================================================
# Tool Implementations
# ============================================================================

def tool_agy_app_status(_args: dict[str, Any]) -> dict[str, Any]:
    b = load_bridge_env()
    app_data = get_app_data_dir()
    latest_conv = get_most_recent_conversation_id(app_data)

    agentapi_ok = False
    agentapi_detail = ""
    if latest_conv and b.get("ANTIGRAVITY_LS_ADDRESS") and b.get("ANTIGRAVITY_CSRF_TOKEN"):
        try:
            res = run_agentapi(["get-conversation-metadata", latest_conv], timeout=10)
            agentapi_ok = bool(res)
            agentapi_detail = "Connected to running Antigravity 2.0 language_server via agentapi."
        except Exception as e:
            agentapi_detail = str(e)
    else:
        agentapi_detail = "Bridge environment not yet populated or no recent conversation found."

    agy_cli = b.get("AGY_CLI_EXE", DEFAULT_AGY_CLI_EXE)
    cli_exists = os.path.exists(agy_cli) or bool(shutil.which(agy_cli))

    return {
        "antigravity_app_connected": agentapi_ok,
        "agentapi_status": agentapi_detail,
        "ls_address": b.get("ANTIGRAVITY_LS_ADDRESS"),
        "app_data_dir": str(app_data),
        "latest_conversation_id": latest_conv,
        "latest_conversation_title": get_conversation_title(app_data, latest_conv) if latest_conv else "",
        "bridge_env_updated_at": b.get("updated_at"),
        "agy_cli_installed": cli_exists,
        "agy_cli_path": agy_cli,
    }


def tool_agy_app_new_conversation(args: dict[str, Any]) -> dict[str, Any]:
    prompt = args.get("prompt", "").strip()
    if not prompt:
        raise ValueError("'prompt' is required.")

    model = args.get("model", "pro").strip() or "pro"
    title = args.get("title", "").strip()
    project_id = args.get("project_id", "").strip() or None
    wait_for_response = bool(args.get("wait_for_response", True))
    timeout_seconds = int(args.get("timeout_seconds", 120))

    app_data = get_app_data_dir()
    brain_dir = app_data / "brain"
    before_ids = {d.name for d in brain_dir.iterdir() if d.is_dir()} if brain_dir.exists() else set()
    start_ts = time.time()

    cmd_args = ["new-conversation", f"--model={model}"]
    if title:
        cmd_args.append(f"--title={title}")
    cmd_args.append(prompt)

    api_res = run_agentapi(cmd_args, project_id=project_id, timeout=30)
    conv_id = extract_conversation_id(api_res)
    if not conv_id:
        conv_id = find_newest_conversation_since(app_data, before_ids, start_ts, timeout=8.0)

    result: dict[str, Any] = {
        "status": "started",
        "conversation_id": conv_id,
        "model": model,
        "title": title,
        "agentapi_response": api_res,
    }

    if wait_for_response and conv_id:
        wait_res = wait_for_conversation_turn(
            app_data=app_data,
            conv_id=conv_id,
            baseline_step_count=0,
            timeout_seconds=timeout_seconds,
        )
        result.update(wait_res)

    return result


def tool_agy_app_send_message(args: dict[str, Any]) -> dict[str, Any]:
    message = args.get("message", "").strip()
    if not message:
        raise ValueError("'message' is required.")

    app_data = get_app_data_dir()
    conv_id = args.get("conversation_id", "").strip()
    if not conv_id:
        conv_id = get_most_recent_conversation_id(app_data) or ""
    if not conv_id:
        raise ValueError("No conversation_id provided and could not determine most recent conversation.")

    title = args.get("title", "").strip()
    project_id = args.get("project_id", "").strip() or None
    wait_for_response = bool(args.get("wait_for_response", True))
    timeout_seconds = int(args.get("timeout_seconds", 120))

    steps_before, _, _ = read_transcript_lines(app_data, conv_id)
    baseline_count = len(steps_before)

    cmd_args = ["send-message"]
    if title:
        cmd_args.extend(["--title", title])
    cmd_args.extend([conv_id, message])

    api_res = run_agentapi(cmd_args, project_id=project_id, timeout=30)
    result: dict[str, Any] = {
        "status": "sent",
        "conversation_id": conv_id,
        "conversation_title": get_conversation_title(app_data, conv_id),
        "baseline_steps": baseline_count,
        "agentapi_response": api_res,
    }

    if wait_for_response:
        wait_res = wait_for_conversation_turn(
            app_data=app_data,
            conv_id=conv_id,
            baseline_step_count=baseline_count,
            timeout_seconds=timeout_seconds,
        )
        result.update(wait_res)

    return result


def tool_agy_app_list_conversations(args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(50, int(args.get("limit", 10))))
    app_data = get_app_data_dir()
    brain_dir = app_data / "brain"
    if not brain_dir.exists():
        return {"conversations": []}

    entries: list[tuple[float, Path]] = []
    for d in brain_dir.iterdir():
        if not (d.is_dir() and UUID_RE.match(d.name)):
            continue
        tr = d / ".system_generated" / "logs" / "transcript.jsonl"
        mtime = tr.stat().st_mtime if tr.exists() else d.stat().st_mtime
        entries.append((mtime, d))

    entries.sort(key=lambda x: x[0], reverse=True)
    conversations = []
    for mtime, d in entries[:limit]:
        conv_id = d.name
        title = get_conversation_title(app_data, conv_id)
        steps, _, _ = read_transcript_lines(app_data, conv_id)
        idle, last_reply, err = is_turn_idle(steps)

        last_user = ""
        for s in reversed(steps):
            if s.get("type") == "USER_INPUT" and s.get("content"):
                last_user = str(s.get("content"))[:200]
                break

        if not last_reply:
            for s in reversed(steps):
                if s.get("type") == "PLANNER_RESPONSE" and s.get("content"):
                    last_reply = str(s.get("content"))
                    break

        conversations.append({
            "conversation_id": conv_id,
            "title": title or (last_user[:60] if last_user else "(Untitled)"),
            "status": "idle" if idle else ("empty" if not steps else "working"),
            "steps_count": len(steps),
            "last_updated": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
            "last_user_input": last_user,
            "last_agent_reply_preview": (last_reply[:300] + "…") if len(last_reply) > 300 else last_reply,
            "error": err,
        })

    return {"conversations": conversations, "total_found": len(entries)}


def tool_agy_app_get_conversation(args: dict[str, Any]) -> dict[str, Any]:
    app_data = get_app_data_dir()
    conv_id = args.get("conversation_id", "").strip()
    if not conv_id:
        conv_id = get_most_recent_conversation_id(app_data) or ""
    if not conv_id:
        raise ValueError("No conversation_id provided and could not determine most recent conversation.")

    max_turns = max(1, min(100, int(args.get("max_turns", 15))))
    include_thinking = bool(args.get("include_thinking", False))

    steps, _, _ = read_transcript_lines(app_data, conv_id)
    idle, _, err = is_turn_idle(steps)

    turns = []
    for s in steps:
        stype = s.get("type")
        if stype in ("USER_INPUT", "PLANNER_RESPONSE", "ERROR_MESSAGE"):
            item: dict[str, Any] = {
                "step_index": s.get("step_index"),
                "type": stype,
                "status": s.get("status"),
                "created_at": s.get("created_at"),
                "content": s.get("content", ""),
            }
            if include_thinking and s.get("thinking"):
                item["thinking"] = s.get("thinking")
            calls = s.get("tool_calls")
            if isinstance(calls, list) and calls:
                item["tool_calls"] = [
                    {"name": c.get("name"), "toolSummary": (c.get("args") or {}).get("toolSummary", "")}
                    for c in calls if isinstance(c, dict)
                ]
            if s.get("error"):
                item["error"] = s.get("error")
            turns.append(item)

    conv_dir = app_data / "brain" / conv_id
    artifacts = []
    if conv_dir.exists():
        for f in conv_dir.glob("*.md"):
            artifacts.append({
                "name": f.name,
                "path": str(f),
                "size_bytes": f.stat().st_size,
            })

    metadata = {}
    try:
        metadata = run_agentapi(["get-conversation-metadata", conv_id], timeout=5)
    except Exception:
        pass

    return {
        "conversation_id": conv_id,
        "title": get_conversation_title(app_data, conv_id),
        "status": "idle" if idle else ("empty" if not steps else "working"),
        "total_steps": len(steps),
        "error": err,
        "artifacts": artifacts,
        "recent_turns": turns[-max_turns:],
        "metadata": metadata,
    }


def tool_agy_app_list_projects(_args: dict[str, Any]) -> dict[str, Any]:
    projects_dir = Path(DEFAULT_CONFIG_DIR) / "projects"
    projects = []
    if projects_dir.exists():
        for p in sorted(projects_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                resources = (data.get("projectResources") or {}).get("resources") or []
                folders = []
                for r in resources:
                    uri = r.get("folderUri", "")
                    if uri.startswith("file:///"):
                        folders.append(urllib.parse.unquote(uri[len("file:///"):]))
                    elif uri:
                        folders.append(uri)
                projects.append({
                    "project_id": data.get("id", p.stem),
                    "name": data.get("name", p.stem),
                    "folders": folders,
                })
            except Exception:
                pass
    return {"projects": projects}


def tool_agy_cli_ask(args: dict[str, Any]) -> dict[str, Any]:
    prompt = args.get("prompt", "").strip()
    if not prompt:
        raise ValueError("'prompt' is required.")

    b = load_bridge_env()
    agy_exe = b.get("AGY_CLI_EXE", DEFAULT_AGY_CLI_EXE)
    if not os.path.exists(agy_exe) and not shutil.which(agy_exe):
        raise RuntimeError(f"Antigravity CLI executable (agy.exe) not found at: {agy_exe}")

    cmd = [agy_exe, "--print"]
    if args.get("model"):
        cmd.extend(["--model", str(args["model"]).strip()])
    if args.get("conversation_id"):
        cmd.extend(["--conversation", str(args["conversation_id"]).strip()])
    elif args.get("continue_last"):
        cmd.append("--continue")
    if args.get("mode"):
        cmd.extend(["--mode", str(args["mode"]).strip()])
    if args.get("effort"):
        cmd.extend(["--effort", str(args["effort"]).strip()])
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


def tool_agy_cli_list_models(_args: dict[str, Any]) -> dict[str, Any]:
    b = load_bridge_env()
    agy_exe = b.get("AGY_CLI_EXE", DEFAULT_AGY_CLI_EXE)
    if not os.path.exists(agy_exe) and not shutil.which(agy_exe):
        raise RuntimeError(f"Antigravity CLI executable (agy.exe) not found at: {agy_exe}")

    proc = subprocess.run(
        [agy_exe, "models"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    models = []
    for line in (proc.stdout or "").splitlines():
        if "\t" in line:
            mid, display = line.split("\t", 1)
            models.append({"id": mid.strip(), "display_name": display.strip()})
    return {"models": models, "raw_output": (proc.stdout or "").strip()}


# ============================================================================
# MCP Tool Registry
# ============================================================================

TOOLS = [
    {
        "name": "agy_app_status",
        "description": "Check live connection status to the running Antigravity 2.0 Desktop App (via agentapi) and Antigravity CLI (agy.exe).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "agy_app_new_conversation",
        "description": "Start a new live conversation inside the Antigravity 2.0 Desktop App UI and optionally wait for the agent's full reply.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The prompt or task to send to the new Antigravity 2.0 conversation.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional conversation title shown in the Antigravity 2.0 sidebar.",
                },
                "model": {
                    "type": "string",
                    "description": "Model tier ('flash_lite', 'flash', 'pro') or specific model ID (e.g. 'gemini-4-argon-high'). Defaults to 'pro'.",
                    "default": "pro",
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional Antigravity 2.0 project ID (see agy_app_list_projects).",
                },
                "wait_for_response": {
                    "type": "boolean",
                    "description": "Wait for the Antigravity 2.0 agent to complete its turn and return its reply. Defaults to true.",
                    "default": True,
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Maximum seconds to wait when wait_for_response is true. Defaults to 120.",
                    "default": 120,
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "agy_app_send_message",
        "description": "Send a message to an existing conversation inside the Antigravity 2.0 Desktop App (defaults to the most recent conversation if conversation_id is omitted) and optionally wait for the agent's reply.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message content to send to the Antigravity 2.0 conversation.",
                },
                "conversation_id": {
                    "type": "string",
                    "description": "Target conversation UUID in Antigravity 2.0. If omitted, sends to the most recently active conversation.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional title/label for the sent message.",
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional project ID.",
                },
                "wait_for_response": {
                    "type": "boolean",
                    "description": "Wait for the Antigravity 2.0 agent to complete its reply and return it. Defaults to true.",
                    "default": True,
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Maximum seconds to wait when wait_for_response is true. Defaults to 120.",
                    "default": 120,
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "agy_app_list_conversations",
        "description": "List recent conversations in the Antigravity 2.0 Desktop App with their conversation_id, title, status (idle/working), step count, and latest message preview.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of recent conversations to return (1-50). Defaults to 10.",
                    "default": 10,
                },
            },
        },
    },
    {
        "name": "agy_app_get_conversation",
        "description": "Read the transcript turns (user inputs and agent responses), artifacts, and metadata of a conversation in the Antigravity 2.0 Desktop App.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "Conversation UUID to read. If omitted, reads the most recently active conversation.",
                },
                "max_turns": {
                    "type": "integer",
                    "description": "Maximum number of recent turns to return. Defaults to 15.",
                    "default": 15,
                },
                "include_thinking": {
                    "type": "boolean",
                    "description": "Include the agent's internal thinking/reasoning blocks. Defaults to false.",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "agy_app_list_projects",
        "description": "List all configured projects and workspace paths in the Antigravity 2.0 Desktop App.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "agy_cli_ask",
        "description": "Run a prompt non-interactively through the Antigravity CLI (agy.exe --print) and return the response.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Prompt or question to send to agy.exe.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model ID (e.g. 'gemini-4-argon-high', 'gemini-4-neon-high', 'gemini-3.8-flash-high').",
                },
                "conversation_id": {
                    "type": "string",
                    "description": "Optional CLI conversation ID to resume (--conversation).",
                },
                "continue_last": {
                    "type": "boolean",
                    "description": "Continue the most recent CLI conversation (--continue). Defaults to false.",
                    "default": False,
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory path.",
                },
                "mode": {
                    "type": "string",
                    "description": "Optional execution mode: 'plan', 'accept-edits', or 'auto'.",
                },
                "effort": {
                    "type": "string",
                    "description": "Optional reasoning effort: 'low', 'medium', 'high', 'xhigh', or 'max'.",
                },
                "dangerously_skip_permissions": {
                    "type": "boolean",
                    "description": "Auto-approve tool permission requests in CLI mode. Defaults to false.",
                    "default": False,
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout in seconds. Defaults to 180.",
                    "default": 180,
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "agy_cli_list_models",
        "description": "List all AI models available in Antigravity (via agy.exe models).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

TOOL_HANDLERS = {
    "agy_app_status": tool_agy_app_status,
    "agy_app_new_conversation": tool_agy_app_new_conversation,
    "agy_app_send_message": tool_agy_app_send_message,
    "agy_app_list_conversations": tool_agy_app_list_conversations,
    "agy_app_get_conversation": tool_agy_app_get_conversation,
    "agy_app_list_projects": tool_agy_app_list_projects,
    "agy_cli_ask": tool_agy_cli_ask,
    "agy_cli_list_models": tool_agy_cli_list_models,
}


# ============================================================================
# JSON-RPC 2.0 Stdio MCP Transport
# ============================================================================

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
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"resources": []},
        }

    if method == "prompts/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"prompts": []},
        }

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
            text_out = json.dumps(res, indent=2, ensure_ascii=False)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text_out}],
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

        if stripped.lower().startswith("content-length:"):
            length = int(stripped.split(":", 1)[1].strip())
            while True:
                hline = sys.stdin.readline()
                if not hline or not hline.strip():
                    break
            body = sys.stdin.read(length)
            try:
                msg = json.loads(body)
            except Exception:
                continue
            resp = handle_request(msg)
            if resp is not None:
                out_bytes = json.dumps(resp, ensure_ascii=False).encode("utf-8")
                sys.stdout.write(f"Content-Length: {len(out_bytes)}\r\n\r\n")
                sys.stdout.write(out_bytes.decode("utf-8"))
                sys.stdout.flush()
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
