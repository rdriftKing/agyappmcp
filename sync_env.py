#!/usr/bin/env python3
"""
Antigravity 2.0 Environment Synchronizer for Claude Code MCP Bridge.
Captures live ANTIGRAVITY_* environment variables from Antigravity 2.0
(via Sidecar, Lifecycle Hook, or direct invocation) and persists them
to bridge_env.json so external MCP clients (like Claude Code) can
communicate with the running Antigravity 2.0 desktop application via agentapi.
"""

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent
BRIDGE_ENV_FILE = BRIDGE_DIR / "bridge_env.json"

HOME = Path.home()
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", str(HOME / "AppData" / "Local")))
DEFAULT_AGENTAPI_EXE = str(LOCAL_APPDATA / "Programs" / "antigravity" / "resources" / "bin" / "language_server.exe")
DEFAULT_APP_DATA_DIR = str(HOME / ".gemini" / "antigravity")
DEFAULT_AGY_CLI_EXE = str(LOCAL_APPDATA / "agy" / "bin" / "agy.exe")


def load_existing() -> dict:
    if BRIDGE_ENV_FILE.exists():
        try:
            return json.loads(BRIDGE_ENV_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_bridge_env(extra: dict | None = None) -> dict:
    data = load_existing()

    env_keys = [
        "ANTIGRAVITY_LS_ADDRESS",
        "ANTIGRAVITY_CSRF_TOKEN",
        "ANTIGRAVITY_AGENTAPI_EXE",
        "ANTIGRAVITY_APP_DATA_DIR",
        "ANTIGRAVITY_PROJECT_ID",
        "ANTIGRAVITY_CONVERSATION_ID",
        "ANTIGRAVITY_LS_VERSION",
    ]
    for k in env_keys:
        val = os.environ.get(k)
        if val:
            data[k] = val

    if not data.get("ANTIGRAVITY_AGENTAPI_EXE") and os.path.exists(DEFAULT_AGENTAPI_EXE):
        data["ANTIGRAVITY_AGENTAPI_EXE"] = DEFAULT_AGENTAPI_EXE
    if not data.get("ANTIGRAVITY_APP_DATA_DIR") and os.path.exists(DEFAULT_APP_DATA_DIR):
        data["ANTIGRAVITY_APP_DATA_DIR"] = DEFAULT_APP_DATA_DIR
    if not data.get("AGY_CLI_EXE"):
        if os.path.exists(DEFAULT_AGY_CLI_EXE):
            data["AGY_CLI_EXE"] = DEFAULT_AGY_CLI_EXE
        else:
            which_agy = shutil.which("agy")
            if which_agy:
                data["AGY_CLI_EXE"] = which_agy

    if extra:
        for k, v in extra.items():
            if v:
                data[k] = v

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["pid"] = os.getpid()

    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = BRIDGE_ENV_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_file.replace(BRIDGE_ENV_FILE)
    return data


def run_hook():
    extra = {}
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                payload = json.loads(raw)
                conv_id = payload.get("conversationId")
                if conv_id:
                    extra["ANTIGRAVITY_CONVERSATION_ID"] = conv_id
                cwd = payload.get("cwd")
                if cwd:
                    extra["LAST_CWD"] = cwd
    except Exception:
        pass

    save_bridge_env(extra)
    sys.stdout.write("{}\n")
    sys.stdout.flush()


def run_sidecar():
    save_bridge_env({"SIDECAR_ACTIVE": True})
    try:
        while True:
            time.sleep(30)
            save_bridge_env({"SIDECAR_ACTIVE": True})
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    if "--hook" in sys.argv:
        run_hook()
    elif "--sidecar" in sys.argv:
        run_sidecar()
    else:
        saved = save_bridge_env()
        print(f"Synced Antigravity environment to {BRIDGE_ENV_FILE}")
        print(f"LS Address: {saved.get('ANTIGRAVITY_LS_ADDRESS')}")
        print(f"Conversation ID: {saved.get('ANTIGRAVITY_CONVERSATION_ID')}")
