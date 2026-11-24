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

- `agy_app_status`：檢查與執行中 Antigravity 2.0 App (`agentapi`) 及 `agy.exe` 的連線狀態與最新對話 ID。
- `agy_app_new_conversation`：直接在 **Antigravity 2.0 桌面 App** 開啟新對話並執行任務（參數：`prompt`, `title`, `model`, `project_id`, `wait_for_response`, `timeout_seconds`）。
- `agy_app_send_message`：直接向 **Antigravity 2.0 桌面 App** 中的既有對話傳送訊息並等待回覆（參數：`message`, `conversation_id` 未填預設最新活躍對話, `wait_for_response`）。
- `agy_app_list_conversations`：列出 Antigravity 2.0 App 最近對話清單。
- `agy_app_get_conversation`：讀取指定對話的完整紀錄 (`USER_INPUT`、`PLANNER_RESPONSE`) 與 Artifact `.md` 檔案清單。
- `agy_app_list_projects`：列出 Antigravity 2.0 App 已設定的所有專案 ID 與工作區路徑。
- `agy_cli_ask`：透過 `agy.exe --print` 在背景執行單次詢問（參數：`prompt`, `model`, `effort`, `mode`, `cwd`, `conversation_id`, `continue_last`）。
- `agy_cli_list_models`：執行 `agy.exe models` 列出所有可用模型 ID。

### 2. Antigravity 2.0 App 呼叫 Claude Code (`claude-code` MCP)

在 Antigravity 2.0 App 中透過 `call_mcp_tool`（`ServerName: "claude-code"`）呼叫：
- `claude_status`：檢查本機 `claude.exe` 安裝路徑與版本。
- `claude_ask`：透過 `claude.exe -p` 向 Claude Code 發送詢問或請求第二意見（參數：`prompt`, `cwd`, `model`, `continue_last`, `resume_session_id`, `allowed_tools`）。

### 3. 若在 `D:\5791\Amateur_for_Ray` 工作區作業
- 正式任務交付、草稿提交與審查紀錄請遵守該工作區 `AGENTS.md` 規範，搭配 `amateur-bridge`（`bridge_inbox`、`bridge_send`、`bridge_thread`、`bridge_check_base`）使用。
- 可將兩者串聯：Claude Code 先用 `bridge.py send` 寄出正式任務信件後，呼叫 `agy_app_send_message(message="請執行 bridge_inbox 收信並處理最新任務")` 直接喚醒 Antigravity 2.0 桌面 App 視窗自動開工。
