# agyappmcp — Antigravity 2.0 Desktop App ↔ Claude Code 雙向 MCP Bridge

一套**零第三方套件相依（100% Python 標準函式庫）**的雙向 Model Context Protocol (MCP) 橋樑，讓 **Claude Code** 與 **Google Antigravity 2.0 桌面版 App / `agy` CLI** 可以直接互相呼叫與操控對話視窗。

---

## 核心特色

1. **直接操控 Antigravity 2.0 桌面版 App 原生介面 (`agentapi`)**：
   - 不需依賴 Chrome DevTools Protocol (CDP) 注入，也不需安裝 Node.js / Bun。
   - 直接串接 Antigravity 2.0 官方內建的 `language_server.exe agentapi` 與本機 `transcript.jsonl`，支援在桌面 App 視窗中**開新對話、向既有對話傳送訊息、同步等待 Agent 回覆完成、讀取完整對話紀錄與 Artifacts**。
2. **自動連線環境同步 (Global Sidecar + Lifecycle Hook)**：
   - 透過 [`sync_env.py`](./sync_env.py) 自動在 Antigravity 2.0 啟動或執行對話時，將最新的 `ANTIGRAVITY_LS_ADDRESS` 與 `ANTIGRAVITY_CSRF_TOKEN` 同步至本機 `bridge_env.json`（已列入 `.gitignore`，絕不外洩權杖）。
3. **雙向互通**：
   - **Claude Code → Antigravity (`antigravity` MCP)**：在 Claude Code 中直接呼叫 Antigravity 2.0 桌面 App 或 `agy.exe --print`。
   - **Antigravity → Claude Code (`claude-code` MCP)**：在 Antigravity 2.0 中直接呼叫 `claude.exe -p` 取得第二意見或委派任務。

---

## 快速安裝（全域適用）

將本專案 Clone 至本機固定目錄（例如 `D:\5791\agyappmcp`）後，執行一鍵安裝腳本：

```powershell
git clone https://github.com/rdriftKing/agyappmcp.git D:\5791\agyappmcp
cd D:\5791\agyappmcp
python install_mcp.py
```

`install_mcp.py` 會自動完成：
- 設定 Antigravity 2.0 全域 Sidecar (`~/.gemini/config/sidecars/claude_mcp_bridge/sidecar.json`) 與 Lifecycle Hook (`~/.gemini/config/hooks.json`)。
- 將 `antigravity` MCP 註冊至 Claude Code 全域設定 (`~/.claude.json`, Scope: `user`)。
- 將 `claude-code` MCP 註冊至 Antigravity 全域設定 (`~/.gemini/config/mcp_config.json`) 並熱載入。
- 將 `agy-claude-mcp` 技能安裝至全域技能目錄 (`~/.gemini/config/skills/agy-claude-mcp/SKILL.md`)。

---

## MCP 工具清單

### 1. Claude Code 端可用工具 (`antigravity` MCP)

| 工具名稱 | 功能說明 |
| :--- | :--- |
| `agy_app_status` | 檢查與執行中 **Antigravity 2.0 桌面 App** (`agentapi`) 及 `agy.exe` CLI 的連線狀態與最新對話 ID。 |
| `agy_app_new_conversation` | 直接在 **Antigravity 2.0 桌面 App** 建立新對話並發送 Prompt（預設 `wait_for_response=true` 會等待 Agent 回覆完成並把完整結果傳回 Claude Code）。 |
| `agy_app_send_message` | 直接傳送訊息至 **Antigravity 2.0 桌面 App** 中的既有對話（未填 `conversation_id` 時預設傳送至最新活躍對話），並可等待回覆。 |
| `agy_app_list_conversations` | 列出 Antigravity 2.0 桌面 App 中最近的對話清單（含標題、`conversation_id`、`idle`/`working` 狀態與最後訊息摘要）。 |
| `agy_app_get_conversation` | 讀取指定對話的完整對話紀錄（`USER_INPUT`、`PLANNER_RESPONSE`、思考過程與 Artifact `.md` 檔案清單）。 |
| `agy_app_list_projects` | 列出 Antigravity 2.0 桌面 App 中設定的所有專案 ID 與資料夾路徑。 |
| `agy_cli_ask` | 透過 `agy.exe --print` 在背景執行單次詢問或委派任務（支援指定 `model`、`effort`、`mode`、`conversation_id`）。 |
| `agy_cli_list_models` | 列出 Antigravity 支援的所有模型清單（如 `gemini-4-argon-high`、`gemini-4-neon-xhigh` 等）。 |

### 2. Antigravity 2.0 端可用工具 (`claude-code` MCP)

| 工具名稱 | 功能說明 |
| :--- | :--- |
| `claude_status` | 檢查本機 `claude.exe` 安裝路徑與版本。 |
| `claude_list_sessions` | 列出本機目前所有**正在開啟中的 Claude Desktop App 對話分頁**（名稱、`[ref]` 與 `idle`/`busy` 狀態）。 |
| `claude_send_message` | 經過出站資安閘門檢查後，**直接將訊息傳送到已開啟的 Claude Desktop App 對話視窗並自動喚醒它**（自動附帶 Antigravity `conversation_id` 回信指引，讓 Claude 可直接透過 `agy_app_send_message` 回傳至原視窗）。 |
| `claude_ask` | 透過 `claude.exe -p` 在背景唯讀模式向 Claude Code 發送詢問或請求第二意見，並取回 Claude Code 的回覆。 |

---

## Prompt 使用範例

### 在 Claude Code 裡下 Prompt：
- *「請用 `antigravity` MCP 的 `agy_app_send_message` 傳訊息給目前最新的 Antigravity 對話，請它幫我分析這段邏輯並等待它回覆。」*
- *「請用 `agy_app_new_conversation` 在 Antigravity App 開一個新對話執行 Architecture Review。」*
- *「請用 `agy_app_list_conversations` 與 `agy_app_get_conversation` 讀取剛剛 Antigravity 對話的最新結果與產出的 Artifacts。」*

### 在 Antigravity 2.0 App 裡下 Prompt：
- *「請用 `claude-code` MCP 的 `claude_ask` 詢問 Claude Code 對這個架構的看法，並把它的回覆整理給我。」*
