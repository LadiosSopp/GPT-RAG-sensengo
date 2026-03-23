# 通話逐字稿 Ingest → 人物側寫更新 架構說明

## 概述

本文件說明 STT（語音轉文字）通話逐字稿如何從 Blob Storage 被定期 Ingest，
並更新客戶在 Azure SQL DB 中的人物側寫（persona），同時追蹤更新時間與來源。

## 架構流程圖

> Mermaid 原始檔：[transcript-persona-ingest-flow.mmd](transcript-persona-ingest-flow.mmd)
> 渲染指令：`python doc/tools/render_one.py doc/architecture/transcript-persona-ingest-flow.mmd doc/diagrams/transcript-persona-ingest-flow.png`

```
┌────────────────┐     ┌─────────────────────────┐
│  STT 語音系統   │────▶│  Blob Storage            │
│  (Speech-to-   │     │  call-transcripts-stt/   │
│   Text)        │     │  ├─ {call_id}.json       │
└────────────────┘     │  ├─ {call_id}.json       │
                       └──────────┬──────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │  gpt-rag-ingestion          │
                    │  TranscriptPersonaIndexer   │
                    │  (APScheduler CRON)         │
                    │                             │
                    │  CRON_RUN_TRANSCRIPT_PERSONA │
                    └──┬──────────┬──────────────┘
                       │          │
              ┌────────▼──┐  ┌───▼──────────────┐
              │ Cosmos DB  │  │ Azure OpenAI     │
              │ call-      │  │ (LLM Persona     │
              │ transcripts│  │  Merge)          │
              └────────────┘  └───┬──────────────┘
                                  │
                       ┌──────────▼──────────────┐
                       │ Azure SQL DB             │
                       │ customer_persona_raw     │
                       │                          │
                       │ persona (更新文字)        │
                       │ persona_updated_at       │
                       │ persona_update_source    │
                       │ tags_updated_at          │
                       │ tags_update_source       │
                       └──────────┬──────────────┘
                                  │
                       ┌──────────▼──────────────┐
                       │ Blob Storage             │
                       │ call-transcripts-stt-    │
                       │ processed/               │
                       │ (已處理檔案歸檔)          │
                       └──────────────────────────┘
```

## 詳細流程

### Step 1: STT 系統產出逐字稿

語音 STT 系統將通話錄音轉為逐字稿後，以 JSON 格式存入 Blob Storage：

**Container**: `call-transcripts-stt`

**檔案格式**: `{call_id}.json`

```json
{
    "customer_id": "22003659",
    "call_id": "010a03a3caa92949",
    "call_date": "2026-03-17",
    "status": "成功",
    "transcript": "專員|270|您好我是光明信用卡中心\n顧客|5280|嗯嗯你好\n..."
}
```

### Step 2: 定時 Ingest（TranscriptPersonaIndexer）

`gpt-rag-ingestion` 中的 `TranscriptPersonaIndexer` 透過 APScheduler CRON 定時執行：

**CRON 設定**: App Config key `CRON_RUN_TRANSCRIPT_PERSONA`

每次執行時：
1. **列舉** `call-transcripts-stt` container 中所有 `.json` 檔案
2. **並行處理** 每個檔案（max_concurrency=4）

### Step 3: 單檔處理流程

對每個 JSON 檔案：

| 步驟 | 動作 | 目標 |
|------|------|------|
| 3a | 下載 & 解析 JSON | 驗證 customer_id, call_id 等必填欄位 |
| 3b | Upsert 逐字稿至 Cosmos DB | `call-transcripts` container（供查詢用） |
| 3c | 查詢現有 persona | SQL DB `customer_persona_raw.persona` |
| 3d | LLM 合併 persona | 用 Azure OpenAI 分析逐字稿，與現有側寫合併 |
| 3e | 更新 SQL persona | 寫回 `persona` + `persona_updated_at` + `persona_update_source` |
| 3f | 搬移已處理檔案 | `call-transcripts-stt` → `call-transcripts-stt-processed` |

### Step 4: LLM Persona 合併

系統使用以下 prompt 讓 LLM 合併現有側寫與新通話內容：

- 保留原側寫中仍然有效的資訊
- 從通話中提取新的偏好、態度、關注點、購買意向
- 如有矛盾以最新通話為準
- 輸出簡潔扼要的合併側寫（≤ 500 字）

## 資料庫追蹤欄位

### SQL Table: `customer_persona_raw` 新增欄位

| 欄位 | 類型 | 說明 |
|------|------|------|
| `persona_updated_at` | DATETIMEOFFSET | 人物側寫文字最後更新時間 |
| `persona_update_source` | NVARCHAR(100) | 更新來源（如 `transcript_ingest:{call_id}`） |
| `tags_updated_at` | DATETIMEOFFSET | 標籤最後更新時間 |
| `tags_update_source` | NVARCHAR(100) | 標籤更新來源（如 `tag_program_v2`） |

### 更新來源識別格式

| 來源 | persona_update_source 範例 | 說明 |
|------|---------------------------|------|
| 逐字稿 Ingest | `transcript_ingest:010a03a3caa92949` | 自動化流程，含 call_id |
| 手動更新 | `manual` | 人工手動修改 |
| 標籤程式 | `tag_program_v2` | 外部標籤處理程式（寫入 tags 欄位） |

## 相關設定

### App Configuration Keys

| Key | 說明 | 範例 |
|-----|------|------|
| `CRON_RUN_TRANSCRIPT_PERSONA` | Ingest 排程 CRON | `0 */30 * * *`（每 30 分鐘） |
| `TRANSCRIPT_BLOB_CONTAINER` | STT 來源 container | `call-transcripts-stt` |
| `TRANSCRIPT_PROCESSED_CONTAINER` | 已處理歸檔 container | `call-transcripts-stt-processed` |
| `TRANSCRIPT_COSMOS_CONTAINER` | Cosmos DB container | `call-transcripts` |
| `TRANSCRIPT_PERSONA_DEPLOYMENT` | LLM deployment 名稱 | （預設使用 CHAT_DEPLOYMENT_NAME） |
| `TRANSCRIPT_MAX_CONCURRENCY` | 並行處理上限 | `4` |
| `SQL_SERVER` | SQL Server 位址 | `ehs-sales-sqlserver.database.windows.net` |
| `SQL_DATABASE` | 資料庫名稱 | `salesagent` |
| `SQL_USERNAME` | SQL 使用者 | `sqladmin` |
| `SQL_PASSWORD` | SQL 密碼 | （需安全管理） |

## MCP 工具

新增兩個 MCP Tool 供查詢與更新追蹤資訊：

| Tool | 說明 |
|------|------|
| `query_persona_update_info(customer_id)` | 查詢人物側寫/標籤的最後更新時間和來源 |
| `update_customer_tags_tracking(customer_id, source)` | 供標籤程式更新 tags 追蹤欄位 |

## 檔案清單

| 檔案 | 說明 |
|------|------|
| `gpt-rag-ingestion/jobs/transcript_persona_indexer.py` | Ingest Job 主程式 |
| `gpt-rag-ingestion/main.py` | 排程註冊（新增 `run_transcript_persona`） |
| `gpt-rag-ingestion/requirements.txt` | 新增 `pyodbc` 依賴 |
| `gpt-rag-mcp/src/tools/sql_persona.py` | 新增追蹤查詢與更新函數 |
| `gpt-rag-mcp/src/server.py` | 新增兩個 MCP Tool |
| `scripts/add_persona_tracking_columns.sql` | SQL Migration 腳本 |

## SQL Migration

在啟用新功能前，需先執行 SQL migration：

```bash
# 透過 Azure Portal Query Editor 或 sqlcmd 執行
sqlcmd -S ehs-sales-sqlserver.database.windows.net -d salesagent \
       -U sqladmin -P '...' \
       -i scripts/add_persona_tracking_columns.sql
```

## 標籤程式整合介面

外部標籤處理程式在更新完標籤欄位後，應呼叫以下方式記錄追蹤：

### 方式一：直接 SQL

```sql
UPDATE customer_persona_raw
SET tags_updated_at = SYSDATETIMEOFFSET(),
    tags_update_source = 'tag_program_v2'
WHERE unikey3 = @customer_id
```

### 方式二：MCP Tool

```python
# 透過 MCP Server 呼叫
update_customer_tags_tracking(customer_id="22003659", source="tag_program_v2")
```

## 運行日誌

每次 Ingest 執行會在 `jobs` container 寫入 summary：

```
jobs/transcript-persona-indexer/{runId}/summary.json
```

```json
{
    "indexerType": "transcript-persona-indexer",
    "runId": "20260317T103000Z",
    "runStartedAt": "2026-03-17T10:30:00+00:00",
    "runFinishedAt": "2026-03-17T10:31:15+00:00",
    "sourceContainer": "call-transcripts-stt",
    "blobsFound": 5,
    "success": 4,
    "failed": 1,
    "personaUpdated": 4,
    "status": "finished"
}
```
