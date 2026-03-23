# 通話記錄查詢功能 — 架構文件

> **建立日期**：2026-02-09  
> **最後更新**：2026-02-11  
> **相關元件**：gpt-rag-orchestrator, Cosmos DB, Azure App Configuration

---

## 1. 功能概述

本功能將會員卡推廣通話記錄（xlsx 格式）匯入 Cosmos DB，並透過 Azure AI Agent SDK 的 **Function Calling** 機制，讓 LLM Agent 能夠自動查詢通話記錄資料庫，回答使用者關於客戶通話、推銷結果、通話內容等問題。

### 支援的查詢類型

- 依客戶編號（客代）查詢通話記錄
- 依推銷狀態（成功/失敗）篩選
- 依日期篩選
- 依關鍵字搜尋逐字稿內容
- 成功/失敗通話的比較分析

---

## 2. 架構圖

```
┌─────────────────────────────────────────────────────────────────────┐
│                         使用者 (Browser)                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTPS
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Frontend (gpt-rag-ui)                             │
│                    ca-2v3lfktkn4xam-frontend-gprag                   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ POST /orchestrator (SSE)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 Orchestrator (gpt-rag-orchestrator)                  │
│                 ca-2v3lfktkn4xam-orch-gprag                         │
│                                                                     │
│  ┌───────────────────────────────────────────────────┐              │
│  │         SingleAgentRAGStrategy v1                  │              │
│  │                                                    │              │
│  │  Agent (LLM) ──── Function Calling ───┐            │              │
│  │       │                                │            │              │
│  │       │ Tool Selection                 │            │              │
│  │       │ (由 Prompt 引導)               │            │              │
│  │       ▼                                ▼            │              │
│  │  ┌──────────────┐   ┌──────────────────────────┐   │              │
│  │  │ FunctionTool │   │ FunctionTool              │   │              │
│  │  │ search_      │   │ query_call_transcripts() │   │              │
│  │  │ knowledge_   │   │                          │   │              │
│  │  │ base()       │   │ CallTranscriptClient     │   │              │
│  │  └──────┬───────┘   └────────────┬─────────────┘   │              │
│  └─────────┼────────────────────────┼─────────────────┘              │
│            │                        │                                │
└────────────┼────────────────────────┼────────────────────────────────┘
             │                        │
             ▼                        ▼
┌────────────────────┐   ┌──────────────────────────────┐
│  Azure AI Search   │   │  Cosmos DB                    │
│  srch-*-gprag      │   │  cosmos-*-gprag               │
│                    │   │                                │
│  • ragindex        │   │  DB: cosmos-db*-gprag          │
│  • ragindex-second │   │  Container: call-transcripts   │
│                    │   │  Partition Key: /customer_id    │
│                    │   │  Mode: Serverless               │
└────────────────────┘   └──────────────────────────────┘
```

### 與 MCP 的對比

本功能使用的是 **FunctionTool（Function Calling）** 方式，而非 MCP：

| 面向 | Function Calling（本功能） | MCP（gpt-rag-mcp） |
|---|---|---|
| 協定 | Azure AI Agent SDK FunctionTool | JSON-RPC over HTTP/SSE |
| 部署位置 | 嵌入 Orchestrator Container App | 獨立 MCP Server Container App |
| 耦合度 | 高（工具程式碼在 Orchestrator 內） | 低（獨立服務，標準化介面） |
| 新增工具 | 修改 Orchestrator + 重新部署 | 修改 MCP Server + 重新部署 |
| 適合場景 | 快速整合、單一工具 | 多工具、多資料源、團隊協作 |

---

## 3. 資料模型

### 3.1 資料來源

- **檔案**：`會員卡推廣名單通話文本_成功失敗各500人_去敏.xlsx`
- **大小**：9.1 MB
- **記錄數**：1,100 筆

### 3.2 Cosmos DB Document Schema

```json
{
  "id": "010a03a3caa92949",           // = call_id，文件唯一識別碼
  "customer_id": "22003659",          // 客代，同時為 Partition Key
  "call_id": "010a03a3caa92949",      // 通話 ID
  "call_date": "2026-01-09",          // 通話日期 (YYYY-MM-DD)
  "status": "成功",                    // 推銷狀態：「成功」或「失敗」
  "transcript": "專員|270|您好...\n顧客|5280|嗯嗯..."  // 通話逐字稿
}
```

### 3.3 資料統計

| 指標 | 值 |
|---|---|
| 總記錄數 | 1,100 |
| 推銷成功 | 676 |
| 推銷失敗 | 424 |
| 逐字稿平均長度 | 9,405 字元 |
| 逐字稿最大長度 | 32,767 字元 |
| 逐字稿最小長度 | 10 字元 |
| 逐字稿中位數 | 4,951 字元 |

### 3.4 逐字稿格式

```
專員|270|您好我是光明信用卡中心
顧客|5280|嗯嗯你好
專員|8940|想跟您介紹我們最新的會員卡優惠
...
```

格式為 `說話者|時間戳(ms)|對話內容`，以換行分隔。

---

## 4. 程式碼結構

### 4.1 新建檔案

#### `scripts/import_call_transcripts.py`

一次性匯入腳本，將 xlsx 資料匯入 Cosmos DB。

- 使用 `openpyxl` 讀取 xlsx
- 使用 `azure.identity.aio.AzureCliCredential`（async 版本，Cosmos async client 要求）
- 以 `upsert_item` 寫入（冪等，重複執行不會產生重複資料）
- 批次大小 50 筆，含進度日誌和錯誤處理

#### `gpt-rag-orchestrator/src/connectors/call_transcripts.py`

Cosmos DB 查詢 Connector，設計為 FunctionTool 供 LLM Agent 呼叫。

**類別**：`CallTranscriptClient`

**方法**：`query_call_transcripts()`

| 參數 | 類型 | 預設 | 說明 |
|---|---|---|---|
| `customer_id` | `str` | `None` | 客代篩選 |
| `status` | `str` | `None` | 推銷狀態：`"成功"` / `"失敗"` |
| `call_date` | `str` | `None` | 日期篩選 (YYYY-MM-DD) |
| `keyword` | `str` | `None` | 逐字稿關鍵字搜尋 |
| `top` | `int` | `10` | 最大回傳筆數 (上限 50) |
| `include_full_transcript` | `str` | `"false"` | `"true"` 回傳完整逐字稿 |

**特性**：
- 動態 SQL 建構，使用參數化查詢防止注入
- 有 `customer_id` 時走單分區查詢（效能優化）
- 無 `customer_id` 時走 cross-partition 查詢
- 預設截斷逐字稿至 2,000 字元，減少 token 消耗
- 截斷時回傳 `transcript_length` 欄位告知原始長度

### 4.2 修改檔案

#### `gpt-rag-orchestrator/src/strategies/single_agent_rag_strategy_v1.py`

3 處修改：

1. **Import**：引入 `CallTranscriptClient`
2. **`__init__`**：
   - 讀取 `CALL_TRANSCRIPTS_ENABLED` App Config 設定
   - 初始化 `CallTranscriptClient`
   - 建立 `FunctionTool`，加入 `self.tools_list`
3. **`initiate_agent_flow`**：
   - 收集 `call_transcript_client` 的 auto_functions
   - 註冊至 `enable_auto_function_calls`
4. **`_get_or_create_agent`**：
   - 在 `prompt_context` 中加入 `call_transcripts_enabled` 變數
   - 控制 Jinja2 模板的條件渲染

#### `gpt-rag-orchestrator/src/prompts/single_agent_rag/main.jinja2`

Prompt 模板重構：

- 新增 **Tool Selection 決策表**：Agent 根據問題類型選擇正確的工具
- 通話相關問題 → 只呼叫 `query_call_transcripts`（不強制搜知識庫）
- 文件/知識問題 → 只呼叫 `search_knowledge_base`
- 混合問題 → 兩個都用
- 新增 `include_full_transcript` 使用指引

---

## 5. Azure 資源設定

### 5.1 Cosmos DB

| 設定 | 值 |
|---|---|
| 帳戶 | `cosmos-2v3lfktkn4xam-gprag` |
| 資料庫 | `cosmos-db2v3lfktkn4xam-gprag` |
| 容器 | `call-transcripts` |
| Partition Key | `/customer_id` |
| 模式 | Serverless（不設 throughput） |
| 認證 | Managed Identity (DefaultAzureCredential) |

### 5.2 App Configuration

| Key | Value | Label |
|---|---|---|
| `CALL_TRANSCRIPTS_ENABLED` | `true` | `gpt-rag` |

設為 `false` 或刪除此 key 可停用通話記錄查詢功能，不需修改程式碼或重新部署。

### 5.3 Container App

| 設定 | 值 |
|---|---|
| Orchestrator | `ca-2v3lfktkn4xam-orch-gprag` |
| 映像 | `cr2v3lfktkn4xamgprag.azurecr.io/orchestrator:20260209152559` |
| Revision | `--0000018` |

---

## 6. Function Calling 流程

```
步驟 1: 使用者輸入
  「找出客戶22003659的通話記錄」
       │
       ▼
步驟 2: Prompt 模板渲染
  Jinja2 模板根據 call_transcripts_enabled=true
  渲染出 Tool Selection 決策表和工具參數說明
       │
       ▼
步驟 3: LLM 判斷 & Function Call
  Agent (GPT-4.1) 分析問題屬於「通話記錄」類型
  產生 function call:
    {
      "name": "query_call_transcripts",
      "arguments": {"customer_id": "22003659"}
    }
       │
       ▼
步驟 4: 自動執行 (enable_auto_function_calls)
  Azure AI Agent SDK 自動呼叫對應的 Python 函式：
    CallTranscriptClient.query_call_transcripts(customer_id="22003659")
       │
       ▼
步驟 5: Cosmos DB 查詢
  SQL: SELECT ... FROM c WHERE c.customer_id = @customer_id
  使用 partition_key="22003659" (單分區查詢)
       │
       ▼
步驟 6: 回傳結果
  JSON: {
    "total_results": 1,
    "records": [{
      "customer_id": "22003659",
      "call_date": "2026-01-09",
      "status": "成功",
      "transcript": "專員|270|您好... [truncated]"
    }]
  }
       │
       ▼
步驟 7: Agent 組織回答
  LLM 根據查詢結果生成使用者友善的回答
  透過 SSE 串流回 Frontend
```

---

## 7. 使用範例

### Frontend 對話範例

| 使用者輸入 | Agent 行為 | 使用工具 |
|---|---|---|
| 找出客戶22003659的通話記錄 | 查 Cosmos DB | `query_call_transcripts` |
| 顯示22003659的完整通話內容 | 查 Cosmos DB (full) | `query_call_transcripts(include_full_transcript="true")` |
| 列出推銷成功的通話 | 查 Cosmos DB | `query_call_transcripts(status="成功")` |
| 搜尋提到信用卡的通話 | 查 Cosmos DB | `query_call_transcripts(keyword="信用卡")` |
| 保險理賠的流程是什麼 | 查知識庫 | `search_knowledge_base` |
| 分析成功通話使用了哪些話術 | 查 Cosmos DB + 分析 | `query_call_transcripts(status="成功", top=20)` |

---

## 8. 功能開關

透過 App Configuration 控制，不需重新部署：

```bash
# 啟用
az appconfig kv set --endpoint https://appcs-2v3lfktkn4xam-gprag.azconfig.io \
  --key CALL_TRANSCRIPTS_ENABLED --value true --label gpt-rag --auth-mode login -y

# 停用
az appconfig kv set --endpoint https://appcs-2v3lfktkn4xam-gprag.azconfig.io \
  --key CALL_TRANSCRIPTS_ENABLED --value false --label gpt-rag --auth-mode login -y
```

> **注意**：App Config 變更需要 Orchestrator Container App 重啟才會生效（Container App 在啟動時載入設定）。

---

## 9. 已知限制

1. **逐字稿 token 消耗**：完整逐字稿最長 32,767 字元，開啟 `include_full_transcript` 且查詢多筆時可能超出 context window
2. **非 MCP 架構**：工具直接嵌入 Orchestrator，新增/修改工具需重新部署 Orchestrator
3. **靜態資料**：通話記錄為一次性匯入，沒有自動同步機制
4. **關鍵字搜尋效能**：`CONTAINS()` 在大量資料時效能較差，若需高頻關鍵字搜尋建議建立 Cosmos DB 全文索引或改用 AI Search
