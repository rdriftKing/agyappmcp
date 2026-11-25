---
name: agy-claude-mcp
description: >-
  安裝、設定與使用 Antigravity (agy App / CLI) 與 Claude Code 之間的雙向 MCP 溝通橋樑（包含直接控制 Antigravity 2.0 桌面 App 對話的 antigravity MCP、從 Antigravity 呼叫 Claude Code 的 claude-code MCP，以及 Amateur 工作區的 amateur-bridge 檔案信箱 MCP）。當使用者或 Agent 需要讓 Claude Code 與 Antigravity 互相溝通、建立/傳送跨 App 對話、或重新安裝此 MCP 時，請啟用此技能。
---

# Antigravity × Claude Code 雙向 MCP 安裝與使用指南

本技能提供 **Antigravity (2.0 桌面 App / IDE / CLI)** 與 **Claude Code** 的雙向 MCP 溝通架構、全域安裝流程與工具呼叫規範。

- **全域專案路徑**：`D:\5791\agyappmcp`
- **GitHub 儲存庫**：`https://github.com/rdriftKing/agyappmcp.git`

---

## 一、一鍵安裝與修復（全域適用）

若在新電腦、新帳號或環境重置後需要安裝或修復雙向 MCP，請執行：

```powershell
python "D:\5791\agyappmcp\install_mcp.py"
```

此腳本會自動將 `D:\5791\agyappmcp` 下的 [`agy_mcp_server.py`](file:///D:/5791/agyappmcp/agy_mcp_server.py)、[`claude_mcp_server.py`](file:///D:/5791/agyappmcp/claude_mcp_server.py) 與 [`sync_env.py`](file:///D:/5791/agyappmcp/sync_env.py) 註冊至 Claude Code (`~/.claude.json`) 與 Antigravity 2.0 (`~/.gemini/config/mcp_config.json`、`hooks.json`、`sidecars/claude_mcp_bridge/sidecar.json`)。

---

## 二、工具清單與呼叫方式

### 1. Claude Code 呼叫 Antigravity 2.0 App (`antigravity` MCP)

> **給 Claude Code 的重要提示**：此 MCP Server 註冊名稱為 `antigravity`，在 Claude Code 內部的完整工具名稱為 `mcp__antigravity__<工具名>`。若工具為延遲載入（Deferred Tools），請先呼叫 `ToolSearch` 搜尋 `"antigravity"` 或 `"agy_app"` 載入工具 schema，再直接呼叫以下工具（**不要**用 Bash 猜測路徑）：

- `mcp__antigravity__agy_app_status`（`agy_app_status`）：檢查與執行中 Antigravity 2.0 App (`agentapi`) 及 `agy.exe` 的連線狀態與最新對話 ID。
- `mcp__antigravity__agy_app_new_conversation`（`agy_app_new_conversation`）：直接在 **Antigravity 2.0 桌面 App** 開啟新對話並執行任務（參數：`prompt`, `title`, `model`, `project_id`, `wait_for_response`, `timeout_seconds`）。
- `mcp__antigravity__agy_app_send_message`（`agy_app_send_message`）：直接向 **Antigravity 2.0 桌面 App** 中的既有對話傳送訊息並等待回覆（參數：`message`, `conversation_id` 未填預設最新活躍對話, `wait_for_response`）。
- `mcp__antigravity__agy_app_list_conversations`（`agy_app_list_conversations`）：列出 Antigravity 2.0 App 最近對話清單。
- `mcp__antigravity__agy_app_get_conversation`（`agy_app_get_conversation`）：讀取指定對話的完整紀錄 (`USER_INPUT`、`PLANNER_RESPONSE`) 與 Artifact `.md` 檔案清單。
- `mcp__antigravity__agy_app_list_projects`（`agy_app_list_projects`）：列出 Antigravity 2.0 App 已設定的所有專案 ID 與工作區路徑。
- `mcp__antigravity__agy_cli_ask`（`agy_cli_ask`）：透過 `agy.exe --print` 在背景執行單次詢問（參數：`prompt`, `model`, `effort`, `mode`, `cwd`, `conversation_id`, `continue_last`）。
- `mcp__antigravity__agy_cli_list_models`（`agy_cli_list_models`）：執行 `agy.exe models` 列出所有可用模型 ID。

### 2. Antigravity 2.0 App 呼叫 Claude Code (`claude-code` MCP)

在 Antigravity 2.0 App 中透過 `call_mcp_tool`（`ServerName: "claude-code"`）呼叫：
- `claude_status`：檢查本機 `claude.exe` 安裝路徑與版本。
- `claude_list_sessions`：列出這台電腦上所有**正在開啟中的 Claude Desktop App 對話視窗**（回傳每個對話的 `name` 與 `[ref]`）。
- `claude_send_message`：**直接傳送即時訊息到任何一個已經開啟的 Claude Desktop App 對話視窗並自動喚醒它**（參數：`to` 填入 `claude_list_sessions` 查到的對話名稱如 `"AGY 通訊測試 (fork)"`, `message` 填入訊息內容）。工具會先通過資安出站閘門檢查，並自動附上當前 Antigravity `conversation_id` 的回信路由提示，讓 Claude 處理完後可直接用 `agy_app_send_message(wait_for_response=false)` 回傳到同一個 Antigravity 對話視窗！
- `claude_ask`：透過 `claude -p` 以**唯讀模式**詢問 Claude Code（只能 Read／Glob／Grep，不能執行指令或改檔；工作資料夾限 Amateur 工作區；回覆先過機密閘門才回傳）。參數：`prompt`, `cwd`（限工作區內）, `model`, `allowed_tools`（只能是 Read／Glob／Grep 的子集）, `resume_session_id`（只能接續 claude_ask 自己建立的 session）, `append_system_prompt`, `timeout_seconds`（上限 600）。⛔ 已移除 `dangerously_skip_permissions`、`continue_last`（2026-11-25）。

### 3. 若在 `D:\5791\Amateur_for_Ray` 工作區作業
- 正式任務交付、草稿提交與審查紀錄請遵守該工作區 `AGENTS.md` 規範，搭配 `amateur-bridge`（`bridge_inbox`、`bridge_send`、`bridge_thread`、`bridge_check_base`）使用。
- 可將兩者串聯：Claude Code 先用 `bridge.py send` 寄出正式任務信件後，呼叫 `agy_app_send_message(message="請執行 bridge_inbox 收信並處理最新任務")` 直接喚醒 Antigravity 2.0 桌面 App 視窗自動開工。
