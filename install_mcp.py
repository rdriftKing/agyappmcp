#!/usr/bin/env python3
"""
One-click global installer and verifier for Antigravity <-> Claude Code bidirectional MCP servers.
Registers the MCP servers directly from this repository directory (`D:\\5791\\agyappmcp` or wherever cloned),
configures Antigravity 2.0 Global Sidecar & Lifecycle Hook, installs the global `agy-claude-mcp` skill,
and registers the MCP servers in both Claude Code (`~/.claude.json`) and Antigravity 2.0 (`~/.gemini/config/mcp_config.json`).
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
HOME = Path.home()
GEMINI_DIR = HOME / ".gemini"
CONFIG_DIR = GEMINI_DIR / "config"
SIDECAR_DIR = CONFIG_DIR / "sidecars" / "claude_mcp_bridge"
GLOBAL_SKILL_DIR = CONFIG_DIR / "skills" / "agy-claude-mcp"
CLAUDE_GLOBAL_SKILL_DIR = HOME / ".claude" / "skills" / "agy-claude-mcp"
HOOKS_FILE = CONFIG_DIR / "hooks.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
MCP_CONFIG_FILE = CONFIG_DIR / "mcp_config.json"

PYTHON_EXE = sys.executable


def find_claude_exe() -> str | None:
    which_claude = shutil.which("claude")
    if which_claude:
        return which_claude
    ext_dir = HOME / ".vscode" / "extensions"
    if ext_dir.exists():
        matches = sorted(ext_dir.glob("anthropic.claude-code-*/resources/native-binary/claude.exe"), reverse=True)
        if matches:
            return str(matches[0])
    return None


def main():
    print(f"=== Installing Antigravity <-> Claude Code MCP Bridge from {REPO_DIR} ===")

    sync_script = str(REPO_DIR / "sync_env.py")
    agy_server_script = str(REPO_DIR / "agy_mcp_server.py")
    claude_server_script = str(REPO_DIR / "claude_mcp_server.py")

    # 1. Run sync_env.py once to seed bridge_env.json
    subprocess.run([PYTHON_EXE, sync_script], check=False)

    # 2. Configure Antigravity Global Sidecar
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    sidecar_manifest = {
        "display_name": "Claude Code MCP Bridge",
        "description": "Synchronizes live Antigravity 2.0 session environment (LS address & CSRF token) to bridge_env.json.",
        "command": PYTHON_EXE,
        "args": [sync_script, "--sidecar"],
        "restart_policy": "always",
    }
    (SIDECAR_DIR / "sidecar.json").write_text(json.dumps(sidecar_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Configured Sidecar: {SIDECAR_DIR / 'sidecar.json'}")

    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    else:
        cfg = {}
    cfg.setdefault("sidecars", {})["claude_mcp_bridge"] = {"enabled": True}
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Enabled sidecar in {CONFIG_FILE}")

    # 3. Configure Antigravity Global Lifecycle Hook
    if HOOKS_FILE.exists():
        try:
            hooks = json.loads(HOOKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            hooks = {}
    else:
        hooks = {}

    hook_cmd = f'"{PYTHON_EXE}" "{sync_script}" --hook'
    hooks["claude-mcp-env-sync"] = {
        "enabled": True,
        "SessionStart": [{"type": "command", "command": hook_cmd, "timeout": 5}],
        "PreInvocation": [{"type": "command", "command": hook_cmd, "timeout": 5}],
    }
    HOOKS_FILE.write_text(json.dumps(hooks, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Configured Lifecycle Hook in {HOOKS_FILE}")

    # 4. Register claude-code MCP in Antigravity's mcp_config.json
    if MCP_CONFIG_FILE.exists():
        try:
            mcp_cfg = json.loads(MCP_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            mcp_cfg = {}
    else:
        mcp_cfg = {}

    mcp_cfg.setdefault("mcpServers", {})["claude-code"] = {
        "command": PYTHON_EXE,
        "args": [claude_server_script],
    }
    MCP_CONFIG_FILE.write_text(json.dumps(mcp_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Registered 'claude-code' MCP in {MCP_CONFIG_FILE}")

    # 5. Install Global Skill into ~/.gemini/config/skills/agy-claude-mcp and ~/.claude/skills/agy-claude-mcp
    repo_skill_md = REPO_DIR / "skills" / "agy-claude-mcp" / "SKILL.md"
    if repo_skill_md.exists():
        GLOBAL_SKILL_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_skill_md, GLOBAL_SKILL_DIR / "SKILL.md")
        print(f"[OK] Installed Antigravity Global Skill to {GLOBAL_SKILL_DIR / 'SKILL.md'}")

        CLAUDE_GLOBAL_SKILL_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_skill_md, CLAUDE_GLOBAL_SKILL_DIR / "SKILL.md")
        print(f"[OK] Installed Claude Code Global Skill to {CLAUDE_GLOBAL_SKILL_DIR / 'SKILL.md'}")

    # 6. Hot-refresh MCP server if running inside Antigravity 2.0
    ls_addr = os.environ.get("ANTIGRAVITY_LS_ADDRESS")
    csrf = os.environ.get("ANTIGRAVITY_CSRF_TOKEN")
    if ls_addr and csrf:
        try:
            req = urllib.request.Request(
                f"http://{ls_addr}/exa.language_server_pb.LanguageServerService/RefreshMcpServers",
                data=json.dumps({"serverName": "claude-code"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-codeium-csrf-token": csrf},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            print("[OK] Triggered live RefreshMcpServers for 'claude-code'")
        except Exception as e:
            print(f"[WARN] RefreshMcpServers skipped: {e}")

    # 7. Register antigravity MCP in Claude Code
    claude_exe = find_claude_exe()
    if claude_exe:
        subprocess.run([claude_exe, "mcp", "remove", "-s", "user", "antigravity"], capture_output=True)
        res = subprocess.run(
            [claude_exe, "mcp", "add", "-s", "user", "antigravity", "--", PYTHON_EXE, agy_server_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        print(f"[OK] Registered 'antigravity' MCP in Claude Code: {(res.stdout or res.stderr).strip()}")
    else:
        print("[WARN] claude.exe not found; skipped automatic `claude mcp add`.")

    print("=== Global Installation Complete ===")


if __name__ == "__main__":
    main()
