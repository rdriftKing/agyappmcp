#!/usr/bin/env python3
"""
Claude Code MCP Bridge for Antigravity 2.0 (claude_mcp_server.py)

Registered in Antigravity 2.0's ~/.gemini/config/mcp_config.json as `claude-code`,
allowing Antigravity 2.0 (and agy CLI) to invoke Claude Code (claude -p) via MCP.

2026-11-25 hardened (Amateur main session, user-approved "修 claude_ask"):
  - No permission bypass: `dangerously_skip_permissions` removed; unknown arguments are rejected.
  - Read-only: runs `claude -p --restricted --permission-mode dontAsk --permission-prompts none`,
    allows only Read/Glob/Grep, explicitly denies Bash/PowerShell/Edit/Write/NotebookEdit/WebFetch/WebSearch,
    and loads no MCP servers (--strict-mcp-config).
  - Working directory confined to the Amateur workspace (default: the workspace root).
  - The prompt is passed on stdin, never as an argv token (no flag injection).
  - `continue_last` removed; `resume_session_id` only accepts sessions this tool created
    (so Antigravity cannot load the user's own Claude sessions into context).
  - The reply passes the workspace outbound gate (bridge.gate: keys / confidential markers)
    before it is returned to Antigravity (= Google cloud). Gate unavailable => fail closed.

Self-test (no network, fake claude):  python claude_mcp_server.py --selftest
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SERVER_NAME = "claude-code"
SERVER_VERSION = "1.1.0"

# Workspace root: env AMATEUR_WS overrides; otherwise this machine's Amateur workspace.
WS_DEFAULT = r"D:\5791\Amateur_for_Ray"
READ_ONLY_TOOLS = ("Read", "Glob", "Grep")
DENIED_TOOLS = "Bash PowerShell Edit Write NotebookEdit WebFetch WebSearch"
ALLOWED_ARGS = {"prompt", "cwd", "model", "allowed_tools", "resume_session_id",
                "append_system_prompt", "timeout_seconds"}
TIMEOUT_MAX = 600
SESSIONS_FILE = Path(__file__).resolve().with_name("claude_ask_sessions.json")


class ToolError(Exception):
    pass


def ws_root() -> str:
    root = os.environ.get("AMATEUR_WS") or WS_DEFAULT
    if not os.path.isdir(root):
        raise ToolError(f"Workspace root not found: {root} (set AMATEUR_WS)")
    return os.path.realpath(root)


def find_claude_exe() -> str:
    fake = os.environ.get("CLAUDE_MCP_FAKE_EXE")            # self-test only
    if fake:
        return fake
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


def _exe_argv(exe: str) -> list[str]:
    return [sys.executable, exe] if exe.lower().endswith(".py") else [exe]


def _load_sessions() -> list[str]:
    try:
        data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
        return [str(x) for x in data] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _remember_session(sid: str) -> None:
    ids = _load_sessions()
    if sid and sid not in ids:
        ids = (ids + [sid])[-200:]
        tmp = SESSIONS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(ids), encoding="utf-8")
        tmp.replace(SESSIONS_FILE)


def _gate(text: str) -> list[str]:
    """Workspace outbound gate. Returns block reasons; raises ToolError if the gate cannot run (fail closed)."""
    root = ws_root()
    for p in (os.path.join(root, "_tools_global"), os.path.join(root, "_tools_global", "維護同步")):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import bridge  # noqa: WPS433
        blocked, _ = bridge.gate(text, [], cia_ok=None)
    except Exception as e:  # noqa: BLE001 - gate must fail closed, loudly
        raise ToolError(f"Outbound gate unavailable ({type(e).__name__}: {e}); reply withheld.")
    return blocked


def _confined_cwd(raw: Any) -> str:
    root = ws_root()
    if raw in (None, ""):
        return root
    if not isinstance(raw, str):
        raise ToolError("cwd must be a string")
    p = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(root, raw))
    if not (p == root or p.startswith(root + os.sep)):
        raise ToolError(f"cwd must be inside the workspace ({root}); got {raw}")
    if not os.path.isdir(p):
        raise ToolError(f"cwd does not exist: {raw}")
    return p


def _tools(raw: Any) -> list[str]:
    if raw in (None, ""):
        return list(READ_ONLY_TOOLS)
    items = raw if isinstance(raw, list) else str(raw).replace(",", " ").split()
    items = [str(x).strip() for x in items if str(x).strip()]
    bad = [x for x in items if x not in READ_ONLY_TOOLS]
    if bad or not items:
        raise ToolError(f"allowed_tools may only contain {', '.join(READ_ONLY_TOOLS)}; rejected: {', '.join(bad) or '(empty)'}")
    return items


def _mcp_serve_call(tool_name: str, arguments: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    """Invoke a native peer tool (ListAgents or SendMessage) via `claude mcp serve` over stdio."""
    exe = find_claude_exe()
    p = subprocess.Popen(
        _exe_argv(exe) + ["mcp", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        assert p.stdin is not None and p.stdout is not None
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "antigravity-claude-bridge", "version": SERVER_VERSION},
            },
        }
        p.stdin.write(json.dumps(init_req) + "\n")
        p.stdin.flush()
        p.stdout.readline()

        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        call_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        p.stdin.write(json.dumps(call_req, ensure_ascii=False) + "\n")
        p.stdin.flush()

        raw_line = p.stdout.readline().strip()
        if not raw_line:
            stderr_out = (p.stderr.read() if p.stderr else "").strip()
            raise ToolError(f"Empty response from `claude mcp serve` ({tool_name}): {stderr_out}")
        resp = json.loads(raw_line)
        if "error" in resp:
            raise ToolError(f"`claude mcp serve` error: {resp['error']}")
        result = resp.get("result") or {}
        content = result.get("content") or []
        text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        if result.get("isError"):
            raise ToolError(f"{tool_name} failed: {text}")
        try:
            return json.loads(text)
        except ValueError:
            return {"raw": text}
    finally:
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            pass


def tool_claude_list_sessions(_args: dict[str, Any]) -> dict[str, Any]:
    res = _mcp_serve_call("ListAgents", {})
    # Enrich with session_id, pid, and cwd from ~/.claude/sessions/*.json
    sessions_dir = Path.home() / ".claude" / "sessions"
    by_name: dict[str, list[dict[str, Any]]] = {}
    if sessions_dir.exists():
        for sf in sorted(sessions_dir.glob("*.json")):
            try:
                sdata = json.loads(sf.read_text(encoding="utf-8", errors="replace"))
                sname = str(sdata.get("name") or "").strip()
                info = {
                    "pid": sdata.get("pid"),
                    "session_id": sdata.get("sessionId"),
                    "name": sname,
                    "cwd": sdata.get("cwd"),
                    "status": sdata.get("status"),
                }
                by_name.setdefault(sname, []).append(info)
            except Exception:
                pass
    for sec in res.get("sections") or []:
        for row in sec.get("rows") or []:
            rname = str(row.get("name") or "").strip()
            matches = by_name.get(rname)
            if matches:
                m = matches[0]
                row["session_id"] = m.get("session_id")
                row["pid"] = m.get("pid")
                row["cwd"] = m.get("cwd")
    return res


def _current_agy_conversation_id() -> str:
    env_cid = os.environ.get("ANTIGRAVITY_CONVERSATION_ID", "").strip()
    if env_cid:
        return env_cid
    bridge_env = Path(__file__).resolve().with_name("bridge_env.json")
    if bridge_env.exists():
        try:
            data = json.loads(bridge_env.read_text(encoding="utf-8"))
            return str(data.get("ANTIGRAVITY_CONVERSATION_ID") or "").strip()
        except Exception:
            pass
    return ""


def tool_claude_send_message(args: dict[str, Any]) -> dict[str, Any]:
    to = args.get("to")
    message = args.get("message")
    summary = args.get("summary", "Message from Antigravity 2.0 App")
    if not isinstance(to, str) or not to.strip():
        raise ToolError("'to' (target Claude Desktop session name, e.g. from claude_list_sessions) is required.")
    if not isinstance(message, str) or not message.strip():
        raise ToolError("'message' is required.")

    blocked = _gate(message)
    if blocked:
        raise ToolError("Message withheld by the outbound gate: " + "; ".join(blocked))

    agy_cid = _current_agy_conversation_id()
    routing_note = (
        f"\n\n[Reply routing: Sent from Antigravity 2.0 App"
        + (f" (conversation_id: {agy_cid})" if agy_cid else "")
        + ". Do NOT reply with Claude SendMessage (sender is a one-shot MCP bridge with no inbox, which returns ENOINBOX: dead-owner); "
        + "to reply to Antigravity, call mcp__antigravity__agy_app_send_message"
        + (f' with conversation_id="{agy_cid}" and wait_for_response=false.' if agy_cid else " with wait_for_response=false.")
        + "]"
    )

    payload: dict[str, Any] = {
        "to": to.strip(),
        "message": message + routing_note,
    }
    if isinstance(summary, str) and summary.strip():
        payload["summary"] = summary.strip()[:200]

    return _mcp_serve_call("SendMessage", payload)


def tool_claude_status(_args: dict[str, Any]) -> dict[str, Any]:
    exe = find_claude_exe()
    exists = os.path.exists(exe) or bool(shutil.which(exe))
    version = ""
    if exists:
        try:
            proc = subprocess.run(_exe_argv(exe) + ["--version"], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=10)
            version = (proc.stdout or proc.stderr or "").strip()
        except Exception as e:  # noqa: BLE001
            version = f"Error: {e}"
    return {"claude_installed": exists, "claude_exe_path": exe, "version": version,
            "mode": "read-only (--restricted, dontAsk, Read/Glob/Grep)", "workspace": WS_DEFAULT}


def tool_claude_ask(args: dict[str, Any]) -> dict[str, Any]:
    extra = sorted(set(args) - ALLOWED_ARGS)
    if extra:
        raise ToolError(f"Unsupported argument(s): {', '.join(extra)} (permission bypass and continue_last are not available)")
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ToolError("'prompt' is required.")
    cwd = _confined_cwd(args.get("cwd"))
    tools = _tools(args.get("allowed_tools"))
    t = args.get("timeout_seconds", 180)
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not (1 <= t <= TIMEOUT_MAX):
        raise ToolError(f"timeout_seconds must be 1..{TIMEOUT_MAX}")

    cmd = _exe_argv(find_claude_exe()) + [
        "-p", "--output-format", "json",
        "--restricted", "--strict-mcp-config",
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--allowedTools", ",".join(tools),
        "--disallowedTools", DENIED_TOOLS,
    ]
    model = args.get("model")
    if model:
        if not isinstance(model, str) or not model.replace("-", "").replace(".", "").replace("_", "").isalnum():
            raise ToolError("model must be a plain model name (e.g. sonnet, opus)")
        cmd += ["--model", model]
    rid = args.get("resume_session_id")
    if rid:
        if rid not in _load_sessions():
            raise ToolError("resume_session_id must be a session created by claude_ask itself")
        cmd += ["--resume", rid]
    asp = args.get("append_system_prompt")
    if asp:
        if not isinstance(asp, str):
            raise ToolError("append_system_prompt must be a string")
        cmd += ["--append-system-prompt", asp]

    try:
        proc = subprocess.run(cmd, cwd=cwd, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=float(t))
    except subprocess.TimeoutExpired:
        raise ToolError(f"Claude Code did not finish within {t}s (undeterminable, not a failure verdict).")
    out = (proc.stdout or "").strip()
    try:
        env = json.loads(out)
    except ValueError:
        env = {"result": out}
    response = str(env.get("result") or "")
    sid = env.get("session_id")
    if sid and proc.returncode == 0:
        _remember_session(str(sid))
    blocked = _gate(response)
    if blocked:
        raise ToolError("Reply withheld by the outbound gate: " + "; ".join(blocked))
    return {
        "exit_code": proc.returncode,
        "is_error": bool(env.get("is_error")) or proc.returncode != 0,
        "response": response,
        "session_id": sid,
        "cwd": cwd,
        "allowed_tools": tools,
        "stderr": (proc.stderr or "").strip()[-1000:],
    }


TOOLS = [
    {
        "name": "claude_status",
        "description": "Check Claude Code CLI installation path, version, and the read-only mode this bridge uses.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "claude_ask",
        "description": ("Ask Claude Code a question (claude -p) in READ-ONLY mode inside the Amateur workspace: "
                        "it can only Read/Glob/Grep files, cannot run commands or edit files, and its reply passes a "
                        "confidentiality gate before it is returned."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The question or task for Claude Code."},
                "cwd": {"type": "string", "description": "Optional working directory INSIDE the workspace (default: workspace root)."},
                "model": {"type": "string", "description": "Optional model (e.g. 'sonnet', 'opus')."},
                "allowed_tools": {"type": "string", "description": "Optional subset of: Read, Glob, Grep (default: all three)."},
                "resume_session_id": {"type": "string", "description": "Optional: continue a session previously created by claude_ask (session_id from its result)."},
                "append_system_prompt": {"type": "string", "description": "Optional extra system instructions."},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": TIMEOUT_MAX,
                                    "description": f"Max seconds to wait (default 180, max {TIMEOUT_MAX})."},
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
    {
        "name": "claude_list_sessions",
        "description": "List all currently open/active Claude Desktop App sessions on this machine (via Claude Code native Peer ListAgents) that you can send messages to with claude_send_message.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "claude_send_message",
        "description": "Send a live cross-session message directly into an already-open Claude Desktop App session on this machine (via Claude Code native Peer SendMessage). Passes the outbound confidentiality gate before sending.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Target Claude Desktop session name (or 'name [ref]') as returned by claude_list_sessions (e.g. 'AGY 通訊測試 (fork)').",
                },
                "message": {
                    "type": "string",
                    "description": "The plain text message to deliver to that open Claude Desktop session.",
                },
                "summary": {
                    "type": "string",
                    "description": "Optional short 5-10 word summary label.",
                },
            },
            "required": ["to", "message"],
            "additionalProperties": False,
        },
    },
]

TOOL_HANDLERS = {
    "claude_status": tool_claude_status,
    "claude_ask": tool_claude_ask,
    "claude_list_sessions": tool_claude_list_sessions,
    "claude_send_message": tool_claude_send_message,
}


def handle_request(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params") or {}
    if req_id is None:
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}}
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
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
        if not isinstance(tool_args, dict):
            tool_args = {"__invalid__": True}
        try:
            res = handler(tool_args)
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(res, indent=2, ensure_ascii=False)}], "isError": False}}
        except Exception as e:  # noqa: BLE001 - report every failure to the caller
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"Error executing {tool_name}: {e}"}], "isError": True}}
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


# ── self-test (fake claude, no network) ──────────────────────────────────
FAKE_CLAUDE = r'''
import json, os, sys
argv = sys.argv[1:]
prompt = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "w", encoding="utf-8") as fh:
        json.dump({"argv": argv, "stdin": prompt, "cwd": os.getcwd()}, fh, ensure_ascii=False)
if "FAKE_FAIL" in prompt:
    print(json.dumps({"type": "result", "is_error": True, "result": "auth failed", "session_id": None}))
    sys.exit(1)
reply = "KEY AIza" + "SyA1234567890abcdefghijklmnopqrstuv" if "FAKE_LEAK" in prompt else "ok: " + prompt.strip()[:40]
print(json.dumps({"type": "result", "is_error": False, "result": reply, "session_id": "fake-sess-1"}))
'''


def selftest() -> int:
    res = []

    def case(name, ok, detail=""):
        res.append(bool(ok))
        print(("✅ " if ok else "❌ ") + name + ("" if ok else " | " + str(detail)[:300]))

    tmp = tempfile.mkdtemp(prefix="claude_mcp_selftest_")
    fake = os.path.join(tmp, "fake_claude.py")
    Path(fake).write_text(FAKE_CLAUDE, encoding="utf-8")
    log = os.path.join(tmp, "log.json")
    os.environ["CLAUDE_MCP_FAKE_EXE"] = fake
    os.environ["FAKE_CLAUDE_LOG"] = log
    global SESSIONS_FILE
    keep_sessions, SESSIONS_FILE = SESSIONS_FILE, Path(tmp) / "sessions.json"
    root = ws_root()

    def call(args):
        r = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "claude_ask", "arguments": args}})["result"]
        return r["isError"], r["content"][0]["text"]

    def last():
        return json.loads(Path(log).read_text(encoding="utf-8"))

    try:
        props = TOOLS[1]["inputSchema"]["properties"]
        case("schema: no permission-bypass or continue_last parameter",
             "dangerously_skip_permissions" not in props and "continue_last" not in props, list(props))
        err, t = call({"prompt": "hi", "dangerously_skip_permissions": True})
        case("reject dangerously_skip_permissions", err and "Unsupported" in t, t)
        err, t = call({"prompt": "hi", "continue_last": True})
        case("reject continue_last", err and "Unsupported" in t, t)

        err, t = call({"prompt": "--dangerously-skip-permissions hello"})
        a = last()
        case("normal call succeeds and returns reply", not err and "ok:" in t, t)
        case("prompt goes via stdin, not argv (no flag injection)",
             "--dangerously-skip-permissions hello" in a["stdin"] and "--dangerously-skip-permissions" not in a["argv"], a)
        case("hardened flags present",
             all(x in a["argv"] for x in ("--restricted", "--strict-mcp-config", "--disallowedTools"))
             and a["argv"][a["argv"].index("--permission-mode") + 1] == "dontAsk", a["argv"])
        case("default tools are Read,Glob,Grep only", a["argv"][a["argv"].index("--allowedTools") + 1] == "Read,Glob,Grep", a["argv"])
        case("default cwd is the workspace root", os.path.realpath(a["cwd"]) == root, a["cwd"])

        err, t = call({"prompt": "hi", "allowed_tools": "Bash"})
        case("reject allowed_tools outside Read/Glob/Grep", err and "allowed_tools" in t, t)
        err, t = call({"prompt": "hi", "allowed_tools": "Read,Grep"})
        case("accept a read-only subset", not err and last()["argv"][last()["argv"].index("--allowedTools") + 1] == "Read,Grep", t)

        err, t = call({"prompt": "hi", "cwd": tmp})
        case("reject cwd outside the workspace", err and "inside the workspace" in t, t)
        err, t = call({"prompt": "hi", "cwd": os.path.join(root, ".claude")})
        case("accept cwd inside the workspace", not err, t)

        err, t = call({"prompt": "hi", "resume_session_id": "someone-elses-session"})
        case("reject resuming a session not created by claude_ask", err and "resume_session_id" in t, t)
        err, t = call({"prompt": "hi", "resume_session_id": "fake-sess-1"})
        case("allow resuming its own earlier session", not err and "--resume" in last()["argv"], t)

        err, t = call({"prompt": "FAKE_LEAK"})
        case("outbound gate withholds a reply containing a key (full key not returned)",
             err and "outbound gate" in t and ("SyA1234567890abcdef" not in t), t)
        err, t = call({"prompt": "FAKE_FAIL"})
        case("child failure surfaces exit_code and is_error", not err and '"exit_code": 1' in t and '"is_error": true' in t, t)
        err, t = call({"prompt": "hi", "timeout_seconds": 9999})
        case("reject timeout above the cap", err and "timeout_seconds" in t, t)
    finally:
        SESSIONS_FILE = keep_sessions
        for k in ("CLAUDE_MCP_FAKE_EXE", "FAKE_CLAUDE_LOG"):
            os.environ.pop(k, None)
    n, bad = len(res), res.count(False)
    print(("✅ " if not bad else "❌ ") + f"{n - bad}/{n} passed")
    return 1 if bad else 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        stripped = line.strip()
        if not stripped:
            continue
        try:
            msg = json.loads(stripped)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(msg, dict):
            resp = handle_request(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
