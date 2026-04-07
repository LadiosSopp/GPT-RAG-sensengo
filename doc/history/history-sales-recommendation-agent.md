# Sales Recommendation Agent 開發歷史記錄

## 專案概述

為東森購物（EHS Shopping）建立 AI 電銷推薦話術系統。系統透過 3 步驟工作流程，結合客戶 Persona、通話紀錄與會員卡權益 RAG，由 LLM 推理模型自動產生個人化電銷話術。

---

## Phase 1: 架構設計與資料探索（2026-01 ~ 2026-02）

### 🔍 資料盤點

| 資料來源 | 位置 | 內容 | 筆數 |
|----------|------|------|------|
| 客戶 Persona | Azure SQL `ehs-sales-sqlserver` / `customer_persona_raw` | 結構化標籤（53+ 欄位）+ 文字側寫 | 1,185 → 2,002（含新匯入） |
| 通話文本 | Cosmos DB `call-transcripts` | 電銷通話摘要 | 814 → 1,100+ |
| 會員卡權益 | Azure AI Search `ragindex` | 權益手冊 / 收費說明 / 話術範本 | 876+ docs |

**發現問題：** Persona SQL (1,185 客戶) 與 Cosmos call-transcripts (814 客戶) 之間 0 筆 overlap。Demo 用客戶需手動複製 Persona。

### 📋 Demo 客戶準備

| Customer ID | 說明 |
|-------------|------|
| `26568707` | 第一位 Demo 客戶（64 歲高雄女性，OB 等級 A） |
| `24702892` | 第二位 Demo 客戶（Persona 從 10303606 複製） |

---

## Phase 2: MCP Server 建置

### 檔案：`gpt-rag-mcp/src/server.py`

基於 FastMCP，提供 StreamableHTTP 介面於 `/mcp`。

### MCP Tools（最新）

| Tool | 類別 | 說明 |
|------|------|------|
| `query_customer_persona` | SQL Persona | 查詢客戶結構化 Persona 資料 |
| `search_customer_by_field` | SQL Persona | 依欄位搜尋客戶（性別/縣市/OB等級/星座） |
| `query_call_transcripts` | Cosmos | 查詢客戶通話原文 |
| `query_call_summary` | Cosmos | 查詢客戶通話摘要 |
| `upsert_transcript` | Cosmos | Upsert 通話逐字稿（新增） |
| `search_membership_card` | AI Search | 搜尋會員卡權益 RAG（`ragindex`） |
| `wikipedia_search` | 雜項 | Wikipedia 搜尋 |
| `add` | 雜項 | 測試用加法 |

### SQL Persona 工具擴充（2026-03-17）

`tools/sql_persona.py` 新增函式：
- `get_persona_update_info(customer_id)` → 查詢 persona_updated_at + persona_update_source
- `update_customer_persona(customer_id, persona_text, source)` → 更新 persona 並記錄追蹤欄位
- `update_tags_tracking(customer_id, source)` → 更新 tags 追蹤

**關鍵實作：**
- `tools/sql_persona.py` — pyodbc + SQL Auth，Docker 用 `{ODBC Driver 18 for SQL Server}`，本機用 `{SQL Server}`
- `tools/cosmos_transcripts.py` — Azure SDK + AAD Auth，新增 `upsert_call_transcript()` 支援 source tracking
- `tools/aisearch_membership.py` — REST API + Admin Key，Hybrid search（向量 + 關鍵字）

---

## Phase 3: Orchestrator 整合

### 檔案：`gpt-rag-orchestrator/src/main.py`

FastAPI 應用，端點：

| 路由 | 方法 | 用途 |
|------|------|------|
| `/sales/recommendation` | POST | 電銷推薦 API（主要端點） |
| `/demo` | GET | Demo 網頁 UI |
| `/orchestrator` | POST | 原有 GPT-RAG 路由 |

**API 參數：**
- `customer_id`（必填）
- `call_customer_id`（選填，預設同 customer_id）
- `model_deployment`（選填，Step 3 推薦模型）
- `query_gen_deployment`（選填，Step 2 查詢生成模型）

### 檔案：`gpt-rag-orchestrator/src/connectors/sales_recommendation.py`

核心 `SalesRecommendationClient` 類別，實作 3 步驟工作流程：

```
Step 1: MCP → fetch_persona + fetch_call_summary
Step 2: LLM (QUERY_GEN_DEPLOYMENT) 分析 → 動態 RAG 查詢 → MCP search_membership_card
Step 3: LLM (RECOMMENDATION_DEPLOYMENT) → 產生完整推薦話術 JSON
```

**Semantic Kernel MCPStreamableHttpPlugin** 負責與 MCP Server 通訊。

---

## Phase 4: 3 步驟工作流程演進

### 初版（Rule-based Step 2）

Step 2 使用 `_build_membership_query()` 方法，以規則從 Persona JSON 提取關鍵字：
- 提取 `OB等級`
- 截取 persona 前 150 字
- 提取 `偏好品類`
- 組合為搜尋關鍵字

**缺點：** 無法理解客戶背景脈絡，查詢過於機械化。

### 改版 v1（LLM-driven Step 2）— 2026-03-11

改用 **GPT-4o-mini** 動態分析 Persona + Call Log 產生 RAG 查詢。

### 改版 v2（可配置 Model Deployment）— 2026-03-18

- Step 2 模型改為可配置 `QUERY_GEN_DEPLOYMENT`（預設 `gpt-5-mini`）
- Step 3 模型改為可配置 `RECOMMENDATION_DEPLOYMENT`（預設 `gpt-54`）
- 新增 `membership_suitability` 評估 — **先判斷客戶是否適合推銷會員卡，再決定話術方向**
- 新增 `alternative_strategy` — 不適合推銷時的替代策略
- System Prompt 強化：加入適合度判斷依據（消費力、權益匹配、歷史態度、風險因素）
- 原則新增「先判斷再行動」

**System Prompt 輸出 JSON 結構（最新）：**
```json
{
  "customer_profile_summary": "...",
  "membership_suitability": {
    "is_suitable": true/false,
    "confidence": "高/中/低",
    "positive_factors": [...],
    "negative_factors": [...],
    "verdict": "..."
  },
  "recommended_membership_plan": { ... },
  "sales_script": {
    "opening", "needs_discovery", "product_pitch",
    "benefit_highlight", "objection_handling", "closing", "follow_up"
  },
  "alternative_strategy": "...",
  "taboos": [...],
  "recommended_products": [...],
  "communication_style": "...",
  "success_probability": "..."
}
```

**效果比較：**

| 項目 | Rule-based | LLM-driven |
|------|-----------|------------|
| 查詢內容 | `OB等級A + 偏好品類 + persona前150字` | `高雄市64歲女性，消費力A，健康美容興趣，家庭共享型權益，避免乳糖` |
| 額外耗時 | 0s | ~1.9s |
| 精準度 | 低（機械提取） | 高（語意理解，考慮禁忌） |

---

## Phase 5: Azure 部署

### 基礎設施

| 元件 | 資源名稱 | 位置 |
|------|---------|------|
| Container Apps ENV | `cae-2v3lfktkn4xam-GPRAG` | East US 2 |
| Orchestrator App | `ca-2v3lfktkn4xam-orch-gprag` | External Ingress |
| MCP Server App | `ca-2v3lfktkn4xam-mcp-gprag` | Internal Ingress |
| ACR | `cr2v3lfktkn4xamgprag` | — |
| App Configuration | `appcs-2v3lfktkn4xam-gprag` | label: `gpt-rag` |
| Subscription | `2c9b3248-f263-4104-bd24-6446d4db84b9` | — |

### Azure OpenAI 模型部署

#### 主要資源：`aif-2v3lfktkn4xam-gprag` / RG: `GPRAG` / 區域: **East US 2**（當前使用）

> ⚠️ 2026-03-18 從 `rag-open-ai-test`（eastus）遷移至此資源，詳見 Phase 15。

| 部署名稱 | 模型 | 版本 | SKU | TPM | 用途 | 狀態 |
|----------|------|------|-----|-----|------|------|
| `gpt-54` | GPT-5.4 | 2026-03-05 | GlobalStandard | 80K | **Step 3 推薦話術生成（當前預設）** | ✅ 運行中 |
| `chat` | GPT-5.2 | 2025-12-11 | GlobalStandard | 80K | Step 3 推薦話術生成（舊預設） | ✅ 運行中 |
| `gpt-5-mini` | GPT-5-mini | 2025-08-07 | GlobalStandard | 80K | **Step 2 查詢生成（當前預設）** | ✅ 運行中 |
| `gpt-5-nano` | GPT-5-nano | 2025-08-07 | GlobalStandard | 80K | Step 2 / Step 3 低成本替代（品質 4.5/10） | ✅ 運行中 |
| `text-embedding` | text-embedding-3-large | — | Standard | 40K | Embedding | ✅ 運行中 |

#### 舊資源：`rag-open-ai-test` / RG: `AzureOpenAI` / 區域: **East US**（已不再使用）

| 部署名稱 | 模型 | 版本 | 用途 | 狀態 |
|----------|------|------|------|------|
| `gpt-52` | GPT-5.2 | 2025-12-11 | Step 3（舊） | ⚠️ 閒置 |
| `gpt-5-mini` | GPT-5-mini | 2025-08-07 | Step 2（舊） | ⚠️ 閒置 |
| `gpt-5-nano` | GPT-5-nano | 2025-08-07 | 測試用 | ⚠️ 閒置 |
| `text-embedding-3-small` | — | — | Embedding | ⚠️ 閒置 |
| `text-embedding-ada-002` | — | — | Embedding（舊） | ⚠️ 閒置 |
| ~~`gpt-4o`~~ | ~~GPT-4o~~ | ~~2024-05-13~~ | ~~一般用途~~ | ❌ 已刪除（2026-03-16） |
| ~~`gpt-4o-mini`~~ | ~~GPT-4o-mini~~ | ~~2024-07-18~~ | ~~Step 2（初版）~~ | ❌ 已刪除（2026-03-16） |

**GPT-5 family API 限制（全系列適用，含 mini/nano）：**
- ❌ 不支援 `max_tokens` → 須用 `max_completion_tokens`（包含 reasoning tokens + visible output）
- ❌ 不支援自訂 `temperature` → 僅支援預設值 1（不可傳入 0.7 等自訂值）
- ❌ 不支援 `response_format`
- ⚠️ `max_completion_tokens` 設太小會導致 reasoning tokens 耗盡額度、output 為空（Step 3 目前設 **16384**）

### 部署流程

```powershell
# 1. Build & push image to ACR
$env:NO_COLOR="1"; $env:PYTHONIOENCODING="utf-8"
az acr build --registry cr2v3lfktkn4xamgprag --image "orchestrator:sales-YYYYMMDDHHMMSS" --file Dockerfile . --no-logs

# 2. Update Container App
az containerapp update --name ca-2v3lfktkn4xam-orch-gprag --resource-group GPRAG --image cr2v3lfktkn4xamgprag.azurecr.io/orchestrator:sales-YYYYMMDDHHMMSS
```

### 部署歷史

| 日期 | Image Tag | 內容 |
|------|-----------|------|
| 2026-03-11 | `orchestrator:sales-20260311140704` | LLM-driven Step 2 (gpt-4o-mini query gen) |
| 2026-03-12 | git short HEAD (via deploy.ps1) | membership_suitability 評估邏輯 + Demo UI 適合度卡片 + deploy.ps1 endpoint bug fix |
| 2026-03-13 | `orchestrator:sales-20260313093747` | Demo 新增 Chatbot 側邊欄（會員卡權益問答 RAG）、MCP scale-to-zero |
| 2026-03-18 | `orchestrator:sales-20260318-collapsible` | 可配置模型（gpt-54/gpt-5-mini）+ membership_suitability + 折疊式 UI + max_completion_tokens=16384 |
| 2026-03-18 | `azure-gpt-rag/orchestrator:30d6b7e` | GPT-5.4 預設 + AZURE_OPENAI_ENDPOINT 遷移至 eastus2 |

### 模型遷移歷史（2026-03-16）

| 動作 | 日期 | 說明 |
|------|------|------|
| 建立 `gpt-5-mini` deployment | 03-16 | GPT-5-mini (2025-08-07)，GlobalStandard，capacity 1000K TPM |
| 刪除 `gpt-4o` deployment | 03-16 | GPT-4o approaching retirement |
| 刪除 `gpt-4o-mini` deployment | 03-16 | 替換為 gpt-5-mini |
| 建立 `gpt-5-nano` deployment | 03-17 | GPT-5-nano (2025-08-07)，GlobalStandard，capacity 50 → 1000 → 10000K TPM |
| GPT-5 API 相容性修正 | 03-18 | `max_tokens` → `max_completion_tokens`，移除 `temperature=0.7`，`max_completion_tokens` 4000 → 16384 |

### 目前執行中服務（2026-03-20）

| Container App | Image |
|---------------|-------|
| `ca-2v3lfktkn4xam-orch-gprag` | `azure-gpt-rag/orchestrator:debug-persona`（預設模型：Step 2 `gpt-5-mini` / Step 3 `gpt-54`，Endpoint: `aif-2v3lfktkn4xam-gprag` eastus2） |
| `ca-2v3lfktkn4xam-mcp-gprag` | `azure-gpt-rag/mcp:fix-datetimeoffset`（min replicas=1，11 tools，含 customerid 修正 + Cosmos DefaultAzureCredential + DATETIMEOFFSET converter） |
| `ca-2v3lfktkn4xam-frontend-gprag` | `frontend:prompt-20260225091224` |
| `ca-ingest-gprag` | `dataingest:20260125155500` |

---

## Phase 6: Demo 網頁

### 檔案：`gpt-rag-orchestrator/src/static/demo.html`

瀏覽器存取 `/demo`，頁籤式 UI：
- **推薦話術** — 折疊式顯示：客戶剖析、適合度評估、推薦方案、話術（開場/推薦/異議處理/收尾）、禁忌、推薦產品
- **Debug 資訊** — 各步驟耗時、Token 用量、I/O 記錄
- **原始 JSON** — 完整 API 回應

**功能：** 支援 model_deployment 選擇器（可切換 gpt-52 / gpt-5-nano 等模型）

認證使用 `dapr-api-token` header（預設 `dev-token`）。

**Azure URL：**
```
https://ca-2v3lfktkn4xam-orch-gprag.nicepond-9d5552be.eastus2.azurecontainerapps.io/demo
```

---

## Phase 7: 架構圖與流程圖

### 檔案

| 檔案 | 說明 |
|------|------|
| `doc/architecture.mmd` | 架構圖 Mermaid 原始碼（2026-03-20 更新：模型標籤從 GPT-4o-mini/GPT-5.2 → GPT-5-mini/GPT-5.4） |
| `doc/flow.mmd` | 流程圖 Mermaid 原始碼 |
| `doc/sales-pipeline-current.mmd` | 現行固定 3 步驟 Pipeline |
| `doc/sales-pipeline-proposed.mmd` | 提案動態 Agent Pipeline |
| `doc/transcript-persona-ingest-flow.mmd` | STT Ingest 流程圖 |
| `doc/diagrams/` | 所有渲染後 PNG |

### 渲染後 PNG（doc/diagrams/）

| 檔案 | 說明 |
|------|------|
| `architecture.png` | 系統架構圖（⚠️ 需重新渲染以反映 GPT-5-mini / GPT-5.4 模型更新） |
| `flow-diagram.png` | 3 步驟 Sequence Diagram |
| `flow.png` | 流程圖（舊版） |
| `sales-pipeline-current.png` | 現行固定 Pipeline |
| `sales-pipeline-proposed.png` | 提案動態 Agent Pipeline |
| `transcript-persona-ingest-flow.png` | STT Ingest 流程 |

### 渲染設定
- Playwright Chromium，`device_scale_factor=2`（高解析度）
- `useMaxWidth: false`（避免 SVG 被壓縮）
- 中文字體：Microsoft JhengHei / 微軟正黑體 / Noto Sans TC
- `<meta charset="utf-8">` 確保中文不亂碼
- mermaid `themeVariables.fontFamily` 指定中文字體

### 渲染腳本

| 腳本 | 用途 |
|------|------|
| `doc/render_all.py` | 批次渲染所有 .mmd → PNG |
| `doc/render_one.py` | 單檔渲染（接受路徑參數） |
| `doc/render_mermaid.py` | 非同步 Mermaid 渲染器 |
| `doc/render_flow.py` | Flow 專用渲染 |
| `doc/render_png.py` | 原版渲染腳本（含 local HTTP server） |

---

## Phase 8: Transcript-to-Persona Ingest Pipeline（2026-03-17）

### 概述

STT（語音轉文字）通話逐字稿自動 Ingest → LLM 合併更新客戶 Persona。

### 檔案：`gpt-rag-ingestion/jobs/transcript_persona_indexer.py`

**TranscriptPersonaIndexer 類別：**
1. 從 Blob Storage `call-transcripts-stt/` 下載 JSON
2. 透過 **MCP** `upsert_transcript` 寫入 Cosmos DB（含 call metadata）
3. 透過 **MCP** `query_customer_persona` 查詢現有 persona
4. 呼叫 LLM 合併現有 persona 與新通話洞察（`PERSONA_MERGE_PROMPT`）
5. 透過 **MCP** `update_persona` 更新 persona 文字 + tracking 欄位
6. 歸檔已處理檔案至 `call-transcripts-stt-processed/`
7. 寫入 run summary 至 `jobs/{indexer_name}/{runId}/summary.json`

> ℹ️ **統一 MCP 存取層（Phase 12）：** Indexer 不再直連 Cosmos DB / Azure SQL，所有 DB 存取均透過 MCP Server。

**執行方式：** APScheduler CRON（`CRON_RUN_TRANSCRIPT_PERSONA` 設定值）

**並行處理：** `max_concurrency=4`

### SQL Schema 擴充

`scripts/add_persona_tracking_columns.sql` 新增 4 欄位：

| 欄位 | 類型 | 說明 |
|------|------|------|
| `persona_updated_at` | DATETIMEOFFSET | Persona 最後更新時間 |
| `persona_update_source` | NVARCHAR(100) | 更新來源（如 `transcript_ingest:{call_id}`） |
| `tags_updated_at` | DATETIMEOFFSET | Tags 更新時間 |
| `tags_update_source` | NVARCHAR(100) | Tags 來源（如 `tag_program_v2`） |

含 `persona_updated_at DESC` 非叢集索引。

### 資料匯入腳本（2026-03-18）

| 腳本 | 說明 |
|------|------|
| `scripts/import_persona_from_blob.py` | 從 Blob 下載 Excel (817 rows) → 匯入 SQL |
| `scripts/append_old_persona.py` | CSV 舊 persona 補入 SQL（避免重複） |
| `scripts/backfill_tracking.py` | 回補 tracking 欄位（來源 + 時間戳） |

### 架構文件

- `doc/transcript-persona-ingest-architecture.md` — 完整流程說明
- `doc/transcript-persona-ingest-flow.mmd` → PNG

---

## Phase 9: 模型效能基準測試與品質比較（2026-03-18）

### 基準測試

**檔案：** `doc/benchmark-sales-recommendation.md` + `doc/benchmark-sales-recommendation.json`
**腳本：** `scripts/benchmark_sales_recommendation.py`（457 行）

測試客戶：26568707，每組 10 次。

**測試組合：**

| 組合 | Step 2 Query Gen | Step 3 Recommendation |
|------|-----------------|----------------------|
| Combo 1 | GPT-5-nano | GPT-5.2 |
| Combo 2 | GPT-5-nano | GPT-5-nano |

**效能比較：**

| 指標 | nano + 5.2 | nano + nano |
|------|-----------|------------|
| 平均耗時 | 89.54s | 82.63s |
| 平均 Completion Tokens | 3,233 | 7,448 |
| 平均每次成本 | $0.5038 | $0.0425 |
| 品質分數 | **8.9/10** | 4.5/10 |
| 成功率 | 10/10 | 10/10 |

**模型定價：**

| 模型 | Input ($/1K tokens) | Output ($/1K tokens) |
|------|-------------------|---------------------|
| GPT-5.2 | $0.025 | $0.100 |
| GPT-5-nano | $0.001 | $0.004 |

### 品質比較

**完整分析：** `doc/model-comparison-gpt5nano-vs-gpt52.md`

**GPT-5.2 vs GPT-5-nano 關鍵差異：**

| 面向 | GPT-5.2 ✅ | GPT-5-nano ❌ |
|------|-----------|--------------|
| 客戶輪廓 | 務實、標注高雄地理限制 | 偏「正面包裝」，忽略地理問題 |
| 適合度判斷 | 信心「中」，標注通話歷史缺失風險 | 信心「高」，過度樂觀 |
| 話術自然度 | 口語化、資深電銷人員風格 | 書面語、較生硬 |
| 異議處理 | 4 組（含高雄太遠、不愛直播推銷等場景化異議） | 2 組，偏防禦式回應 |
| 來源標注 | 每條主張標注 (Persona)/(會員卡RAG) | 缺少來源標注 |
| Token 效率 | 3,698 completion tokens | 7,448 completion tokens（2x token 卻品質更低） |
| 風險揭露 | 透明（如「資料不足，信心：中」） | 不足 |
| 推薦附帶商品 | 3 個（無乳糖營養品、肩頸按摩器、先生紅色外套），全來自 Persona 線索 | 僅推會員卡本身和展演票組合，缺乏延伸銷售思維 |

**重大問題標記：**

| 問題 | GPT-5-nano | GPT-5.2 |
|------|-----------|---------|
| 忽略客戶住高雄的地理限制 | **是** ❌ | **否** ✅（異議處理中專門處理） |
| 忽略通話摘要取得失敗 | **是** ❌ | **否** ✅（列為負面因素） |
| 成功率過度樂觀 | **是** ❌（直接標「高」） | **否** ✅（30-45%，並說明限制） |
| 話術可能踩禁忌 | 風險低但「尊榮」語調可能不合 | ✅ 刻意避開 |
| 洩露內部獎金資訊 | 否 | 否 |

**總結評分：**

| 評估維度 | GPT-5-nano | GPT-5.2 |
|----------|:---------:|:-------:|
| 客戶理解深度 | 6/10 | **9/10** |
| 方案推薦合理性 | 6/10 | **8/10** |
| 話術自然度與可用性 | 5/10 | **9/10** |
| 異議處理覆蓋率 | 5/10 | **9/10** |
| 風險揭露與誠實度 | 3/10 | **9/10** |
| 資料引用透明度 | 2/10 | **9/10** |
| Token 效率 | 4/10 | **9/10** |
| **綜合** | **4.5/10** | **8.9/10** |

**結論：** GPT-5.2 在銷售推薦場景全面優於 GPT-5-nano，主要體現在：

1. **不迴避問題** — 面對通話摘要取得失敗、客戶住高雄等不利因素，GPT-5.2 納入策略調整，GPT-5-nano 直接忽略
2. **話術可直接使用** — GPT-5.2 口語化、有溫度有節奏，專員幾乎可照念；GPT-5-nano 偏書面、缺乏差異化
3. **策略更聰明** — 先用小需求（紅外套、肩頸按摩器）建立信任再帶入會員卡，而非一上來就推 13 萬方案
4. **Token 更省** — 用更少的 completion token（3,698 vs 7,448）產出更高品質的結果

**成本 vs 品質取捨：** GPT-5.2 以 ~12x 成本換取 ~2x 品質，適合生產環境；GPT-5-nano 適合開發測試。

> **完整成本結構分析**（含 Container Apps、AI Search、Cosmos DB、App Configuration 等平台費用）請見 `doc/benchmark-sales-recommendation.md` 的「完整成本結構分析」章節。
> **GPRAG Resource Group 實際帳單**（Azure Cost Management 查詢結果）請見 Phase 10.5。

---

## Phase 10: 技術文件整備（2026-03-10 ~ 2026-03-18）

### 新增文件

| 檔案 | 說明 |
|------|------|
| `doc/sales-agent-architecture.md` | 系統架構設計（離線/即時兩階段、Multi-Agent Supervisor、LangGraph） |
| `doc/source-code-guide.md` | GitHub 上游 Repo 對照、客製化差異、取得原始碼方式 |
| `doc/architecture-diagram.md` | 架構圖（含 Mermaid + PNG） |
| `doc/flow-diagram.md` | 流程圖（含 Mermaid + PNG） |
| `doc/sales-pipeline-current.mmd` | 現行固定 3 步驟 Pipeline（Mermaid） |
| `doc/sales-pipeline-proposed.mmd` | 提案動態 Agent Pipeline — LLM 自主選擇工具 |
| `doc/sales-recommendation-sample-26568707.json` | 完整 API 回應範例 |
| `doc/knowledge-transfer.md` | KT 文件 v2.0（林口恩典大樓 RAG 系統） |

### 現行 vs 提案 Pipeline

**現行（Fixed）：** SalesRecommendationClient 硬編碼 3 步驟流程，工具呼叫順序固定。

**提案（Dynamic）：** LLM Agent 自主接收完整工具 schema，自行決定呼叫順序與組合。
- 支援 5 MCP tools + 2 local tools（RAG、Bing grounding）
- 靈活適應不同客戶情境

---

## 端到端測試結果

### 初次測試（2026-03-11）

**測試客戶：** 26568707

| 步驟 | 耗時 | 說明 |
|------|------|------|
| fetch_persona | 0.21s | SQL → 客戶 Persona |
| fetch_call_summary | 0.03s | Cosmos → 通話摘要 |
| llm_query_generation | 1.91s | GPT-4o-mini 分析 → 動態查詢 |
| search_membership_card | 0.12s | AI Search RAG 搜尋 |
| gpt_recommendation | 75.84s | GPT-5.2 產生完整推薦話術 |
| **Total** | **78.13s** | |

### 基準測試（2026-03-18）

**nano + 5.2 組合平均：** 89.54s，$0.5038/次
**nano + nano 組合平均：** 82.63s，$0.0425/次

**LLM 產生的 RAG 查詢範例：**
> 搜尋東森會員卡權益，針對高雄市大社區64歲女性，消費力等級A，關注健康與美容，適合的保健產品優惠、健身活動、旅遊折扣，並考慮家庭共享型權益，避免與乳糖相關的產品及高價商品。

**GPT-5.2 推薦結果包含：**
- 客戶剖析（消費力 A / 保健偏好 / 乳糖禁忌）
- 適合度評估（is_suitable / confidence / positive & negative factors）
- 推薦方案：東森林口會員卡（晶華 × UFC 尊榮生活圈）
- 完整話術：開場白 → 需求探詢 → 產品推薦 → 利益點 → 異議處理（5 種情境） → 收尾 → 追蹤
- 替代策略（不適合時）、禁忌清單、推薦產品、溝通風格建議、成交機率評估

---

## 已知問題與限制

| 問題 | 狀態 | 說明 |
|------|------|------|
| Cosmos AAD Token（Docker） | ✅ 已修正 | Container 內 `az` CLI 不可用 → 改用 `DefaultAzureCredential`（Managed Identity） |
| Persona / Call-transcript 零重疊 | ⚠️ 資料問題 | 實際資料 0 交集，demo 用客戶需手動複製 |
| GPT-5.2 回應時間長 | ℹ️ 正常 | Reasoning model 約 60-90s，已設 timeout 600s |
| Container Apps Ingress Timeout | ✅ 已設 240s | 預設 30s 不足，已調整為 240s |
| GPT-5-nano 品質不足 | ℹ️ 評估完成 | 品質 4.5/10，不適合生產環境，可用於開發測試 |
| GPT-5 family 不支援 max_tokens/temperature | ✅ 已修正 | 全系列統一用 `max_completion_tokens`，不傳 `temperature` |
| GPT-4o/GPT-4o-mini 已退役 | ✅ 已遷移 | Deployments 已刪除，全面遷移至 GPT-5 系列（2026-03-16） |

---

## Phase 10.5: Azure 成本分析與優化（2026-03-13 ~ 03-18）

### 成本異常分析（初次發現 2026-03-13）

Mar 10-12 日間 Azure 日費從 **$81.89 → $150.99**（+$69.10, +84%），主因 Sales Recommendation Agent 系統上線。

### GPRAG Resource Group 實際成本（Azure Cost Management 查詢，2026-03-18）

**2026 年 3 月 1-18 日帳單：~11,662 TWD ≈ ~$360 USD**（幣別為 TWD）

#### 按服務拆解

| 服務 | TWD | ~USD | 佔比 | 說明 |
|------|-----|------|------|------|
| **Foundry Tools (AI Foundry 平台)** | 4,795 | $148 | **41.1%** | AI Foundry 平台費（含 Agentic Retrieval）— 最大開銷 |
| **Azure Cognitive Search × 2** | 2,721 | $84 | **23.3%** | `srch-2v3lfktkn4xam-gprag` + `srch-aif-2v3lfktkn4xam-gprag` 各 ~$42/月 |
| **Foundry Models (OpenAI tokens)** | 1,973 | $61 | **16.9%** | GPT-5.2 / GPT-5-nano 等 LLM token 費用 |
| **Container Apps × 4** | 838 | $26 | **7.2%** | Orchestrator + MCP + Frontend + Ingest |
| **App Configuration** | 695 | $21 | **6.0%** | Standard 層 $1.20/天固定費 |
| **Cosmos DB (AI Foundry)** | 484 | $15 | **4.1%** | `cosmos-aif-*`（AI Foundry 自帶的 Cosmos DB） |
| **Container Registry** | 100 | $3 | **0.9%** | Basic 層 |
| **SQL Database** | 54 | $2 | **0.5%** | `ehs-sales-sqlserver` + `sql-2v3lfktkn4xam-gprag` |
| **其他** | 3 | $0.1 | 0% | Storage / Bandwidth |
| **合計** | **~11,662** | **~$360** | 100% | |

#### 按個別資源拆解（Top 5）

| 資源 | TWD | ~USD |
|------|-----|------|
| `aif-2v3lfktkn4xam-gprag`（AI Foundry + OpenAI） | 6,768 | $209 |
| `srch-2v3lfktkn4xam-gprag`（AI Search Basic） | 1,360 | $42 |
| `srch-aif-2v3lfktkn4xam-gprag`（AI Search Basic — Foundry 建立） | 1,360 | $42 |
| `ca-ingest-gprag`（Container App — DataIngest） | 770 | $24 |
| `appcs-2v3lfktkn4xam-GPRAG`（App Configuration） | 695 | $21 |

#### 每日花費趨勢

| 時段 | 日均花費 (TWD) | ~USD/天 | 說明 |
|------|---------------|---------|------|
| 3/1 ~ 3/9 | ~228 | ~$7 | 僅固定基礎設施費用（AI Search、App Config、Cosmos DB 等） |
| 3/10 | 498 | ~$15 | 開始有 LLM 呼叫 |
| **3/11 ~ 3/18** | **~1,200** | **~$37** | Foundry Tools 費用飆升 + 密集 LLM 測試 |

#### 花錢三大兇手（佔 81%）

1. **AI Foundry 平台費 — $148 (41%)**：`aif-2v3lfktkn4xam-gprag` **不是** OpenAI tokens，而是 AI Foundry 平台服務費。若只做 RAG + sales recommendation，直接用 Azure OpenAI endpoint 可省下此筆。

2. **Azure AI Search × 2 — $84 (23%)**：有兩個 Basic 層 AI Search 24/7 運行：
   - `srch-2v3lfktkn4xam-gprag`（應用 RAG 用）— $42/月
   - `srch-aif-2v3lfktkn4xam-gprag`（AI Foundry 預設建立）— $42/月
   
   後者若不需要 agentic retrieval 可關閉。

3. **OpenAI tokens — $61 (17%)**：實際的 LLM token 費用（GPT-5.2、GPT-5-nano 等呼叫），反而佔比不高。

### 基準測試完整成本結構（2026-03-18）

每次 `/sales/recommendation` API 呼叫觸及的 Azure 服務：

| 步驟 | 服務 |
|------|------|
| Step 1 | Container Apps (Orch → MCP) → Azure SQL + Cosmos DB |
| Step 2 | Container Apps (Orch) → Azure OpenAI (query gen) → MCP → AI Search |
| Step 3 | Container Apps (Orch) → Azure OpenAI (recommendation) |
| 共用 | App Configuration + Key Vault + Application Insights |

**單次呼叫成本拆解：**

| 成本項目 | 組合1 (nano+5.2) | 組合2 (nano+nano) |
|----------|-----------------|------------------|
| Azure OpenAI tokens | **$0.5016** | **$0.0404** |
| Container Apps 計算 | $0.0014 | $0.0014 |
| Cosmos DB / SQL / KV | ~$0.0001 | ~$0.0001 |
| **變動成本合計** | **~$0.5031** | **~$0.0419** |

**成本佔比：** OpenAI tokens 佔變動成本的 **99.7%**，平台費用可忽略。

**固定月費：** AI Search $73.73 × 2 + App Config $36 + ACR $5 ≈ **$188/月**（含多餘的 AI Foundry Search）

**詳細報告：** `doc/benchmark-sales-recommendation.md`（含完整 20 次測試數據與月費估算表）

### 立即落地的優化

| 動作 | 成效 | 狀態 |
|------|------|------|
| **MCP Server scale-to-zero** | 預估省 $60-90/月 | ✅ 已執行 `az containerapp update --min-replicas 0` |
| cooldownPeriod | 300 秒（5 分鐘無流量後縮減） | ✅ |
| 評估關閉多餘的 `srch-aif-*` AI Search | 可省 ~$42/月 | ⚠️ 待評估 |
| 評估是否需要 AI Foundry 平台 | 可省 ~$148/月（最大省錢項） | ⚠️ 待評估 |

### Demo 頁面新增 Chatbot

在 `demo.html` 新增浮動聊天機器人：
- **💬 按鈕**：右下角 FAB，點擊展開/收合
- **對話面板**：標題「💳 會員卡權益問答」、訊息區域、輸入框
- **串接 RAG Agent**：POST `/orchestrator` + `search_index: "ragindex"`（membership 文件索引）
- **SSE 串流**：即時串流顯示回覆，支援多輪對話（`conversation_id`）
- **認證**：`dapr-api-token: dev-token`（與現有 Demo 一致）
- **RWD**：手機螢幕自動調整面板寬度

### 部署

```
Image: orchestrator:sales-20260313093747
Container App: ca-2v3lfktkn4xam-orch-gprag
```

---

## Phase 11: MCP Persona 追蹤工具與模型升級（2026-03-19 ~ 2026-03-20）

### MCP Server 新增 3 個 Persona 追蹤工具

`gpt-rag-mcp/src/server.py` 新增：

| Tool | 類別 | 參數 | 說明 |
|------|------|------|------|
| `query_persona_update_info` | SQL Persona | `customer_id` | 查詢 persona/tags 最後更新時間與來源 |
| `update_persona` | SQL Persona | `customer_id`, `persona_text`, `source` | 更新 persona 文字並記錄追蹤 |
| `update_customer_tags_tracking` | SQL Persona | `customer_id`, `source` | 更新 tags 追蹤欄位 |

**MCP Tools 總數：** 8 → 11 個

`tools/sql_persona.py` 對應新增函式：
- `get_persona_update_info(customer_id)` → 回傳 `persona_updated_at`, `persona_update_source`, `tags_updated_at`, `tags_update_source`
- `update_customer_persona(customer_id, persona_text, source)` → UPDATE persona + tracking 欄位
- `update_tags_tracking(customer_id, source)` → UPDATE tags 追蹤欄位

`tools/cosmos_transcripts.py` 新增：
- `upsert_call_transcript(customer_id, call_id, call_date, status, transcript, source, ingested_at)` → Upsert 逐字稿至 Cosmos DB，支援 `source` 與 `ingested_at` 追蹤

### Orchestrator 模型升級與新端點

#### 新端點：`GET /sales/models`

動態列舉 Azure OpenAI 可用模型部署：
- API 版本：`2022-12-01`（支援列舉所有 deployments）
- 篩選條件：前綴為 `gpt`, `o1`, `o3`, `o4` 的部署
- 回傳格式：`{ "deployments": [...], "defaults": { "query_gen_deployment": "...", "recommendation_deployment": "..." } }`
- 認證：ChainedTokenCredential（Managed Identity → AzureDeveloperCli → AzureCli）+ API Key fallback

#### 模型配置升級

| 項目 | 舊版 | 新版 |
|------|------|------|
| Step 2 Query Gen 模型 | 硬編碼 `gpt-4o-mini` | 可配置 `QUERY_GEN_DEPLOYMENT`（預設 `gpt-5-mini`） |
| Step 3 Recommendation 模型 | 硬編碼 `gpt-52` | 可配置 `RECOMMENDATION_DEPLOYMENT`（預設 `gpt-54`，GPT-5.4） |
| Step 2 `max_tokens` | `max_tokens=200` | `max_completion_tokens=200`（適配 GPT-5 family） |
| Step 3 `max_completion_tokens` | `4000` | `16384`（增加產出上限，確保 reasoning token + output 不溢出） |
| Step 3 `temperature` | 自訂 `0.7` | 移除（GPT-5 family 全系列不支援自訂 temperature） |

#### System Prompt 強化

- 新增「適合度判斷」決策邏輯 — 先評估客戶是否適合推銷會員卡再生成話術
- 評估維度：消費力與價格匹配、權益與需求吻合、歷史態度、風險因素
- 新增 `membership_suitability` JSON 區塊：`is_suitable`, `confidence`, `positive_factors`, `negative_factors`, `verdict`
- 新增 `alternative_strategy` — 不適合時的替代銷售方向
- 原則新增「先判斷再行動」

### Schema 變更

`gpt-rag-orchestrator/src/schemas.py` — `SalesRecommendationRequest` 新增：

| 欄位 | 類型 | 說明 |
|------|------|------|
| `query_gen_deployment` | Optional[str] | Step 2 模型部署名稱 |
| `model_deployment` | Optional[str] | Step 3 模型部署名稱 |

### Demo UI 增強

`gpt-rag-orchestrator/src/static/demo.html` 大幅改版（+399 行）：

- **頁籤式結果展示**：推薦話術 \| Debug \| 原始 JSON
- **折疊式碎片化顯示**（7 個 section）：
  - 客戶剖析 / 適合度評估 / 推薦方案 / 推薦話術（開場→探詢→推薦→異議→收尾→追蹤） / 禁忌清單 / 推薦商品 / 溝通風格 & 成交機率
- **Debug 面板**：各步驟時間軸 + I/O 記錄 + Token 統計 + Timeline Bar 視覺化
- **模型切換器**：兩個 dropdown（Step 2 Query Gen、Step 3 Recommendation），從 `/sales/models` 動態載入
- **Chatbot 側邊欄**：會員卡權益問答（右下角 💬 浮動按鈕），串接 `/orchestrator` + `search_index: "ragindex"` 使用 membership 文件索引，SSE 串流即時顯示，支援多輪會話（`conversation_id` 維持）

### Ingestion Transcript-Persona 排程整合

`gpt-rag-ingestion/main.py` 新增：
- `CRON_RUN_TRANSCRIPT_PERSONA` 排程設定
- `run_transcript_persona()` 任務包裝
- 依序執行已排程工作（保證日誌可追蹤）

### 資料匯入與回補腳本

| 腳本 | 說明 |
|------|------|
| `scripts/import_persona_from_blob.py` | 從 Blob Excel (817 rows) 下載匯入 SQL |
| `scripts/append_old_persona.py` | 舊 CSV persona 補入 SQL（去重） |
| `scripts/backfill_tracking.py` | 回補 persona_updated_at / source 追蹤欄位 |
| `scripts/add_persona_tracking_columns.sql` | SQL Migration — 追蹤欄位 + 非叢集索引 |

### 部署腳本改進

`gpt-rag-orchestrator/scripts/deploy.ps1` 增強：
- App Config endpoint 自動取得（`azd env get-values`）
- ACR 登入前驗證 + Docker Daemon 狀態檢查
- 映像標籤從 Git short HEAD 或隨機生成
- Container App 身份管理（Managed Identity vs System Identity）
- **Bug fix（2026-03-12）：** `Get-ConfigValue` 函式的 `--endpoint` 參數原本使用 `"https://appcs-$($env:RESOURCE_TOKEN).azconfig.io"`（此時 `RESOURCE_TOKEN` 尚未取得），改為直接使用已解析的 `$APP_CONFIG_ENDPOINT` 變數

### Git 分支管理（2026-03-12 ~ 2026-03-20）

| Repo | Remote | 分支 |
|------|--------|------|
| GPT-RAG-sensengo（主 repo） | `LadiosSopp/GPT-RAG-sensengo` | `feature/sales-recommender-agent` |
| gpt-rag-mcp | `LadiosSopp/gpt-rag-mcp-sensengo` 🆕 | `sensengo-main` |
| gpt-rag-orchestrator | `LadiosSopp/gpt-rag-orchestrator-sensengo` | `sensengo-main` |
| gpt-rag-ingestion | `LadiosSopp/gpt-rag-ingestion-sensengo` | `sensengo-main` |
| gpt-rag-ui | `LadiosSopp/gpt-rag-ui-sensengo` | `sensengo-main` |

**PNG 圖檔搬移：** `doc/architecture.png`, `doc/flow.png`, `doc/flow-diagram.png` → `doc/diagrams/` 目錄

---

## 技術棧摘要

```
Frontend:  Static HTML (demo.html) → FastAPI StaticFiles
Backend:   FastAPI + Semantic Kernel + MCPStreamableHttpPlugin
MCP:       FastMCP (StreamableHTTP) — 11 tools (含 upsert_transcript + update_persona + persona 追蹤)
           統一資料存取層: 所有運行時服務均透過 MCP 存取 Cosmos DB / SQL
Models:    GPT-5.4 (reasoning) / GPT-5.2 (reasoning) / GPT-5-nano (lightweight) + GPT-5-mini (query gen)
Data:      Azure SQL + Cosmos DB + Azure AI Search
Ingest:    TranscriptPersonaIndexer (APScheduler CRON) + Blob Storage STT
Infra:     Azure Container Apps + ACR + App Configuration
Auth:      Managed Identity (AAD) + API Key fallback
Diagrams:  Mermaid → Playwright → PNG (doc/diagrams/)
Docs:      Architecture, Flow, Pipeline, Benchmark, Model Comparison, KT, Source Guide
Git:       5 repos — 主 repo + 4 subprojects (各自 sensengo remote/branch)
```

---

## 時間軸

| 日期 | 里程碑 |
|------|--------|
| 2026-01 ~ 02 | Phase 1-3: 架構設計、MCP Server、Orchestrator 整合 |
| 2026-03-03 | knowledge-transfer.md v2.0 |
| 2026-03-10 | sales-agent-architecture.md、source-code-guide.md |
| 2026-03-11 | MCP v2 部署 (`mcp:v2-20260311003507`)、LLM-driven Step 2、首次端到端測試 |
| 2026-03-12 | System Prompt 新增 membership_suitability 評估、Demo UI 適合度卡片、deploy.ps1 endpoint bug fix、部署至 Azure |
| 2026-03-13 | Azure 成本分析（$81.89→$150.99 +84%）、MCP Server scale-to-zero（預估省 $60-90/月）、Demo Chatbot 會員卡權益問答、部署 `orchestrator:sales-20260313093747` |
| 2026-03-17 | Transcript-to-Persona Ingest Pipeline、SQL Schema 擴充（persona_tracking 4 欄位） |
| 2026-03-18 | 可配置模型部署（GPT-5.4 / GPT-5-mini）、membership_suitability、基準測試（20 次 API 呼叫）、模型比較、完整成本結構分析（Azure Cost Management 實際帳單查詢）、Pipeline 提案圖、Demo UI「客戶畫像」→「客戶描述」+ Persona 標籤說明 + 摺疊式面板、部署 `orchestrator:sales-20260318-collapsible` |
| 2026-03-19 ~ 20 | Phase 11: MCP Persona 追蹤工具（3 個新工具）、`/sales/models` 端點、GPT-5.4 升級為預設、`max_completion_tokens=16384`、Demo UI Chatbot 增強、Git 分支管理（5 repos）、資料匯入/回補腳本、架構圖更新（GPT-5-mini / GPT-5.4） |
| 2026-03-18 ~ 19 | **Phase 16: Persona 資料匯入與 MCP 連鎖修正** — Blob Excel 匯入（817 筆）+ 舊 CSV 追加（1185 筆）= 2002 筆、SQL 欄位 `unikey3`→`customerid`、server.py 語法修正、Cosmos `DefaultAzureCredential`、MCP `min-replicas=1`、DATETIMEOFFSET converter、Orchestrator `max_completion_tokens` + 移除 `temperature` |
| 2026-03-18 | Phase 15: GPT-5.4 部署與 AZURE_OPENAI_ENDPOINT 遷移 — eastus → eastus2、前端下拉選單模型同步 |
| 2026-03-20 | Phase 12: 統一 MCP 資料存取層 — Indexer 重構為全面走 MCP（移除 pyodbc / cosmos 直連）、新增輕量 MCPClient、更新 Mermaid 流程圖 + PNG |
| 2026-03-17 ~ 20 | Phase 13: 架構 Q&A — Strategy/MCP/工具呼叫機制釐清、三層決策架構（Orchestrator→Strategy→LLM）、Hybrid Strategy 提案、現行 vs 提案 Pipeline 流程圖 |

### GPT-4 退役與 GPT-5 全面遷移（2026-03-16 ~ 03-18）

| 日期 | 變更 |
|------|------|
| 03-16 | GPT-4o/GPT-4o-mini approaching retirement → 決定全面遷移至 GPT-5 系列 |
| 03-16 | Step 2 查詢生成模型參數化 `QUERY_GEN_DEPLOYMENT`（預設 `gpt-5-mini`） |
| 03-16 | Step 3 推薦話術模型參數化 `RECOMMENDATION_DEPLOYMENT`（fallback chain: API param → config → `gpt-52`） |
| 03-16 | 新增 `GET /sales/models` API — 動態列舉 Azure OpenAI deployments（api-version `2022-12-01`） |
| 03-16 | Demo UI 新增兩個模型下拉選單（Step 2 / Step 3），頁面載入時自動從 `/sales/models` 填充 |
| 03-16 | 建立 `gpt-5-mini` deployment（capacity 1000K TPM），刪除 `gpt-4o` + `gpt-4o-mini` |
| 03-17 | 建立 `gpt-5-nano` deployment（capacity 50 → 1000 → 10000K TPM） |
| 03-18 | GPT-5 API 相容性修正 #1：`max_tokens` → `max_completion_tokens`（GPT-5 全系列不支援 `max_tokens`） |
| 03-18 | GPT-5 API 相容性修正 #2：移除 `temperature=0.7`（GPT-5 全系列僅支援預設值 1） |
| 03-18 | GPT-5 API 相容性修正 #3：`max_completion_tokens` 4000 → 16384（4000 太小，reasoning tokens 耗盡導致 output 為空） |
| 03-18 | **GPT-5.4 部署** — 在 `aif-2v3lfktkn4xam-gprag`（eastus2）建立 `gpt-54` deployment（GlobalStandard, 80K TPM） |
| 03-18 | **AZURE_OPENAI_ENDPOINT 遷移** — 從 `rag-open-ai-test`（eastus）→ `aif-2v3lfktkn4xam-gprag`（eastus2） |
| 03-18 | 在 eastus2 resource 補部署 `gpt-5-mini` + `gpt-5-nano`（確保前端下拉選單完整） |
| 03-18 | Orchestrator 預設模型從 `gpt-52` 改為 `gpt-54`，ACR build tag `30d6b7e` |

---

## Phase 11.5: Demo UI 客戶描述與摺疊式面板（2026-03-18）

### 變更摘要

`gpt-rag-orchestrator/src/static/demo.html` + `src/connectors/sales_recommendation.py`

#### 1. 「客戶畫像」更名為「客戶描述」

- Demo UI 標題：`👤 客戶畫像` → `👤 客戶描述`
- System Prompt JSON 欄位說明：`"2-3 句話的客戶畫像"` → `"2-3 句話的客戶描述"`

#### 2. 新增 Persona 標籤說明

在「客戶描述」區塊內嵌入可展開的 `<details>` 元素「📖 常用 Persona 標籤說明」，以兩欄 Grid 排列 16 個常用標籤及其說明：

| 標籤 | 說明 |
|------|------|
| OB等級 | 電銷消費分級（A 最高 → D 最低） |
| 高健康意識 | 對保健食品/健康管理有高度關注 |
| 高美麗意識 | 對美容保養類產品有高度需求 |
| 健檢標籤 | 曾購買或使用健檢相關服務 |
| 美容標籤 | 曾購買美容相關產品 |
| 保健標籤 | 曾購買保健食品類產品 |
| 是否獨居 | 判斷是否為獨居者（影響話術策略） |
| 寵愛自己名單 | 傾向為自己消費、重視生活品質 |
| 商務菁英 | 具高社經背景的商務客群 |
| 退休保健族 | 退休族群、保健需求較高 |
| 重金珠寶客 | 曾購買高價珠寶、消費力強 |
| 房產投資客 | 有房產投資、資產水平較高 |
| 高社經地位職業 | 職業屬於高社經類別 |
| 有高價保單 | 持有高額保險、反映財力 |
| 三年內有高單一次付清 | 近三年有大額單筆消費紀錄 |
| 有無養寵物 | 是否有寵物、影響推薦商品方向 |

#### 3. 結果分群可摺疊/展開

所有推薦結果區塊改為 collapsible panel：

- 新增 CSS：`.collapsible-section`, `.collapsible-header`, `.collapsible-body`, `.chevron`
- 新增 JS helper：`buildCollapsible(title, bodyHtml, startOpen)`
- 9 個區塊全部使用 collapsible：客戶描述、適合度評估、替代策略、推薦方案、推薦話術、地雷禁忌、推薦商品、溝通風格建議、成交機率
- 預設全部展開（`startOpen=true`），點擊標題列可收合/展開
- ▶ 箭頭 CSS 動畫：展開時旋轉 90°

### 部署

```
Image: orchestrator:sales-20260318-collapsible
Container App: ca-2v3lfktkn4xam-orch-gprag
Deploy: az acr build --no-logs + az containerapp update
```

---

## Phase 12: 統一 MCP 資料存取層（2026-03-20）

### 背景

原始 Phase 8 的 `TranscriptPersonaIndexer` 直接連接 Cosmos DB（`azure.cosmos.aio`）和 Azure SQL（`pyodbc`）。為統一資料存取架構，所有 DB 存取全面改走 MCP Server。

### 變更摺要

#### 重構 `transcript_persona_indexer.py`

| 項目 | 舊版（直連） | 新版（MCP） |
|------|------------|----------|
| Cosmos 寫入 | `azure.cosmos.aio.CosmosClient.upsert_item()` | MCP `upsert_transcript` tool |
| SQL 查詢 persona | `pyodbc` 直接 `SELECT persona FROM ...` | MCP `query_customer_persona` tool |
| SQL 更新 persona | `pyodbc` 直接 `UPDATE ... SET persona = ...` | MCP `update_persona` tool |
| 依賴 | `azure-cosmos`, `pyodbc` | `aiohttp`（已在 requirements） |
| 認證 | Cosmos: ChainedTokenCredential / SQL: pyodbc UID/PWD | MCP Server 統一處理 |
| 配置 | 10+ 個 Cosmos/SQL env vars | `MCP_APP_ENDPOINT` + `MCP_APP_APIKEY` |

#### 新增輕量 MCP Client

`MCPClient` 類別（內建於 indexer）：
- JSON-RPC 2.0 over Streamable HTTP
- 自動 `initialize` 握手 + `mcp-session-id` 管理
- `call_tool(tool_name, **arguments)` → 解析 text content 回傳
- 使用 `aiohttp.ClientSession`（非阻塞）
- 支援 `X-API-KEY` 認證

#### 移除的依賴

- `azure.cosmos.aio` — 不再從 indexer 直接引入
- `pyodbc` — 從 `gpt-rag-ingestion/requirements.txt` 移除

### 架構圖更新

`doc/transcript-persona-ingest-flow.mmd` 更新：
- MCP Server 顯示為中心統一資料存取層
- Indexer 透過 MCP 存取 Cosmos DB 和 Azure SQL
- 標籤程式也透過 MCP 更新追蹤欄位
- 新增 `mcp` 樣式類別（藍紫色）
- 已重新產生 PNG

### 資料存取路徑總覽（更新後）

| 元件 | 存取方式 | 目標 |
|------|----------|------|
| Orchestrator | MCP (Semantic Kernel `MCPStreamableHttpPlugin`) | Cosmos DB + SQL + AI Search |
| Ingestion Indexer | MCP (輕量 `MCPClient` / JSON-RPC) | Cosmos DB + SQL |
| 外部標籤程式 | MCP (`update_customer_tags_tracking` tool) | SQL |
| Demo UI | Orchestrator API | 間接透過 MCP |
| 一次性腳本 | 直接連接（pyodbc / cosmos SDK） | SQL / Cosmos |

> ℹ️ 僅剩 `scripts/` 下的一次性腳本（import/backfill）仍直接連接 DB，所有產品運行時服務均透過 MCP。

---

## Phase 13: 架構 Q&A — Strategy、MCP 與工具呼叫機制釐清（2026-03-17 ~ 03-18）

### 背景

客戶針對系統架構提出多項問題，需釐清 Orchestrator、Strategy、MCP、Agent 之間的關係，以及工具呼叫的決策機制。

### Q1: MCP 工具的呼叫是由 Orchestrator 判斷還是 Strategy 判斷？

**答：三層決策架構。**

| 層級 | 負責什麼 | 誰決定 |
|------|----------|--------|
| Orchestrator | 選擇使用哪個 Strategy | 部署設定（`AGENT_STRATEGY`） |
| Strategy | 準備/註冊可用的工具清單 | 程式碼邏輯 |
| LLM Agent | 根據問題決定呼叫哪個工具 | AI 模型推論 |

- Orchestrator 本身是**最小化派發器**，只根據 `AGENT_STRATEGY` 環境設定選擇 Strategy
- 每個 Strategy 在初始化時註冊該策略可用的所有工具
- **最終決定「要呼叫哪個工具」的是 LLM Agent**，根據使用者問題和工具描述自主判斷

### Q2: AGENT_STRATEGY 設為 mcp 後的流程

**流程確認：**

1. `AGENT_STRATEGY = "mcp"` → Orchestrator 走 `McpStrategy.create()`
2. McpStrategy 初始化時透過 SSE 連接 MCP Server，載入所有工具定義，註冊到 Semantic Kernel
3. 每當 Query 進來，**Semantic Kernel Agent 將問題 + 所有工具定義送給 LLM**
4. LLM 決定呼叫哪個工具 → **Semantic Kernel 自動透過 MCP 協議呼叫 MCP Server 執行** → 結果回饋 LLM
5. LLM 產生最終回覆（或繼續呼叫下一個工具）
6. Orchestrator 只負責接收最終結果並回傳給 UI

**關鍵釐清：** 不是「Orchestrator 呼叫工具」，而是 **Semantic Kernel 框架自動完成工具呼叫迴圈**。McpStrategy 的 `initiate_agent_flow` 只有一行核心：

```python
response = await self.agent.get_response(messages=user_message)
```

### Q3: 如果需要同時走 MCP Strategy 和 Single RAG Strategy？

**現狀：** Orchestrator **無法 per-query 動態分派**，Strategy 在初始化時就決定好了。

**建議方案：建立 Hybrid Strategy（推薦）**

建新 Strategy（如 `MCP_RAG_Strategy`），同時註冊 MCP 工具和 RAG 工具，讓 LLM 自主決定用哪個：

```
AGENT_STRATEGY = "mcp_rag"

MCP_RAG_Strategy
  ├── MCP 工具（透過 MCPSsePlugin 從 MCP Server 載入）
  │   └── query_customer_persona, search_membership_card, ...
  └── RAG 工具（直接在 Strategy 裡註冊）
      └── search_knowledge_base, query_call_transcripts, ...

→ LLM 收到所有工具，根據問題自動決定呼叫哪一個
```

**不建議的方案：** 在 Orchestrator 層加 Router 動態分派（需額外 LLM call 分類，增加延遲與成本，改動核心邏輯風險高）。

### Q4: 工具「註冊」的含義

「註冊」包含兩件事：

1. **定義工具 schema**（名稱、描述、參數） — 每次 LLM API call 時作為 `tools` 參數送出，讓 LLM 知道有哪些工具可用
2. **綁定實際執行函式** — LLM 回應 `tool_call` 時，框架知道要呼叫哪段程式碼

LLM 根據工具的 `description` 判斷要不要用、用哪一個。**工具描述的品質直接影響 LLM 選擇準確度。**

### Q5: 現有銷售推薦系統是否同時註冊了 MCP 和 AI Search？

**否。** 銷售推薦系統（`/sales/recommendation`）**完全不走 Strategy 模式**，它是獨立 endpoint 有自己硬編碼的 3-step pipeline：

| | 聊天對話 (`/orchestrator`) | 銷售推薦 (`/sales/recommendation`) |
|---|---|---|
| **路由** | 走 Strategy Pattern | 獨立 endpoint，不走 Strategy |
| **工具呼叫方式** | LLM 自主決定 | **程式碼硬編碼順序呼叫** |
| **MCP 工具** | McpStrategy 才有 | ✅ 直接呼叫 |
| **AI Search** | SingleAgentRAGStrategyV1 才有 | ✅ 透過 MCP 的 `search_membership_card` 間接使用 |
| **工作流程** | 單輪 Agent 對話 | 固定 3-step pipeline |
| **LLM 次數** | 1 次（可多輪 tool call） | 2 次（Step 2 查詢生成 + Step 3 推薦） |

銷售推薦系統確實同時用了 MCP 和 AI Search，但方式是 **MCP 工具裡面包了 AI Search**（`search_membership_card` 內部呼叫 AI Search），並且是**程式碼按固定順序呼叫**，不是 LLM 自主選擇。

### Q6: 原本 GPT-RAG 的 AI Search 是 LLM 自主呼叫的嗎？

**是。** SingleAgentRAGStrategyV1 中，`search_knowledge_base` 是本地 Python 函式（非 MCP），透過 Azure AI Foundry Agent SDK 的 `FunctionTool` 直接註冊給 Agent：

```python
retrieval_tool = FunctionTool(functions={self.search_client.search_knowledge_base})
project_client.agents.enable_auto_function_calls({self.search_client.search_knowledge_base})
```

LLM 自主判斷是否需要搜尋、帶什麼參數，框架自動執行。

**兩種工具註冊方式對比：**

| | GPT-RAG 的 `search_knowledge_base` | MCP Strategy 的工具 |
|---|---|---|
| 定義位置 | Orchestrator 本地 Python 函式 | MCP Server 遠端定義 |
| 註冊方式 | `FunctionTool(functions={...})` | `MCPSsePlugin.connect()` 自動載入 |
| 執行位置 | Orchestrator process 內 | 透過 SSE/HTTP 遠端呼叫 MCP Server |
| 框架 | Azure AI Foundry Agent SDK | Semantic Kernel + MCP 協議 |

### 架構流程圖

因應上述 Q&A，產出兩張對比流程圖：

| 檔案 | 說明 |
|------|------|
| `doc/sales-pipeline-current.mmd` / `.png` | 現行固定 3-Step Pipeline — 程式碼硬編碼順序呼叫 |
| `doc/sales-pipeline-proposed.mmd` / `.png` | 提案 LLM 自主選擇工具 — Hybrid Strategy，LLM Agent 自主迴圈決定工具呼叫 |

---

## Phase 14: Source Code 指南 — GitHub Repo、客製化差異、Azure 上查看方式（2026-03-18）

### GitHub 官方 Repo（Azure 上游）

本專案基於 Microsoft Azure 的 GPT-RAG 開源方案，由以下五個 GitHub Repo 組成：

| 專案 | GitHub Repo | 說明 |
|------|-------------|------|
| **GPT-RAG（主專案）** | https://github.com/azure/GPT-RAG | 基礎架構 (Infrastructure as Code)、整合部署設定 |
| **gpt-rag-ingestion** | https://github.com/azure/gpt-rag-ingestion | 資料擷取與向量化處理（Chunking、Indexing） |
| **gpt-rag-orchestrator** | https://github.com/azure/gpt-rag-orchestrator | RAG 對話核心邏輯（Prompt、Strategy、Connectors） |
| **gpt-rag-ui** | https://github.com/azure/gpt-rag-ui | 前端 UI（基於 Chainlit） |
| **gpt-rag-mcp** | https://github.com/azure/gpt-rag-mcp | MCP Server（外部工具整合） |

### 客製化專案與範例專案的差異

所有客製化修改皆基於上游 `origin/main` 分支，建立獨立的 `sensengo-main` 分支進行開發。

#### gpt-rag-orchestrator

**新增功能：**
- **銷售推薦 Agent** — 串接 AI Search、Cosmos DB、SQL Server 產生客戶銷售推薦結果
- **通話紀錄查詢** — 從 Cosmos DB 取得客戶通話摘要
- **Debug 模式** — 即時輸出 token 統計、搜尋結果等除錯資訊，支援 SSE streaming
- **精簡版 Prompt 模板** — 用於低延遲場景

**主要修改：**
- RAG 策略加入銷售推薦邏輯與 debug event streaming
- Prompt 客製化為銷售導向、客戶分析
- 搜尋邏輯重構，支援多索引切換

#### gpt-rag-ui

**新增功能：**
- **Debug 面板** — 前端顯示 token 使用量、搜尋結果、延遲統計

**主要修改：**
- 加入搜尋索引切換功能
- 配合新的 orchestrator API 簡化串接邏輯

#### gpt-rag-mcp

**新增功能（銷售推薦 Agent 所需的 MCP 工具）：**
- **AI Search 會員資料查詢** — 查詢會員相關資訊
- **Cosmos DB 通話紀錄查詢** — 取得客戶歷史通話紀錄
- **SQL Server 客戶畫像查詢** — 取得客戶消費行為與標籤

**主要修改：**
- MCP Server 註冊上述三個新工具

#### gpt-rag-ingestion

**主要修改：**
- Blob Storage、SharePoint 等核心 indexer 功能性調整
- 調整 Azure OpenAI 和 App Config 參數設定

### 如何在 Azure 上查看 Source Code

客製化的 source code 已打包在 Docker image 中（每個 Dockerfile 都包含 `COPY . .`），可透過以下方式查看。

#### 目前運行中的服務

| Container App | Image | Source 路徑 |
|---|---|---|
| `ca-2v3lfktkn4xam-orch-gprag` | `azure-gpt-rag/orchestrator:30d6b7e` | `/app/` |
| `ca-2v3lfktkn4xam-frontend-gprag` | `frontend:prompt-20260225091224` | `/app/` |
| `ca-ingest-gprag` | `dataingest:20260125155500` | `/app/` |
| `ca-2v3lfktkn4xam-mcp-gprag` | `azure-gpt-rag/mcp:v2-20260311003507` | `/app/` |

#### 方法一：Azure Portal Console（最簡單）

1. 前往 [Azure Portal](https://portal.azure.com)
2. Resource Group → `GPRAG` → 選擇任一 Container App
3. 左側選單 → **Console**
4. 選擇 shell（bash 或 sh），執行：

```bash
# 列出所有 source 檔案
ls -la /app/

# 查看特定檔案
cat /app/src/main.py

# 查看目錄結構
find /app/src -type f -name "*.py"
```

#### 方法二：Azure CLI 遠端連線

```powershell
# 進入 Orchestrator 容器
az containerapp exec --name ca-2v3lfktkn4xam-orch-gprag --resource-group GPRAG --command bash

# 進入 Frontend 容器
az containerapp exec --name ca-2v3lfktkn4xam-frontend-gprag --resource-group GPRAG --command bash

# 進入 Ingestion 容器
az containerapp exec --name ca-ingest-gprag --resource-group GPRAG --command bash

# 進入 MCP 容器
az containerapp exec --name ca-2v3lfktkn4xam-mcp-gprag --resource-group GPRAG --command bash
```

進入容器後，所有 source code 都在 `/app/` 目錄下。

#### 方法三：從 ACR 拉取 Image 檢視

```powershell
# 登入 ACR
az acr login --name cr2v3lfktkn4xamgprag

# 拉取 image
docker pull cr2v3lfktkn4xamgprag.azurecr.io/orchestrator:sales-20260318-collapsible

# 啟動容器並進入 shell
docker run --rm -it cr2v3lfktkn4xamgprag.azurecr.io/orchestrator:sales-20260318-collapsible bash

# 在容器內查看 source
ls /app/src/
cat /app/src/strategies/single_agent_rag_strategy_v1.py
```

#### 方法四：從 ACR 匯出檔案（不啟動容器）

```powershell
# 建立暫時容器但不啟動
docker create --name temp-orch cr2v3lfktkn4xamgprag.azurecr.io/orchestrator:sales-20260318-collapsible

# 將 /app 目錄複製出來
docker cp temp-orch:/app ./orchestrator-source

# 清理
docker rm temp-orch

# 現在可以在本地查看完整 source
dir ./orchestrator-source/src/
```

#### 權限需求

| 查看方式 | 所需 Azure 權限 |
|----------|-----------------|
| Portal Console | Container App 的 Contributor 或以上角色 |
| Azure CLI exec | Container App 的 Contributor 或以上角色 |
| ACR pull image | ACR 的 AcrPull 角色 |

> **注意**: Azure Container Registry `cr2v3lfktkn4xamgprag` 和 Resource Group `GPRAG` 位於 **East US 2** 區域。

---

## Phase 15: GPT-5.4 部署與 AZURE_OPENAI_ENDPOINT 遷移（2026-03-18）

### 背景

GPT-5.4 模型發佈，需部署到專案中並設為 Step 3 推薦話術的預設模型。原先 `AZURE_OPENAI_ENDPOINT` 指向 `rag-open-ai-test`（eastus），但 eastus 的 GPT-5.4 只有 Provisioned SKU（需預留容量，成本高），eastus2 則有 GlobalStandard（隨用隨付）。因此決定整體遷移至 eastus2 資源。

### GPT-5.4 區域可用性調查

使用 Azure MCP + `az cognitiveservices model list` 查詢 13 個區域：

| 區域 | GPT-5.4 可用 SKU |
|------|-------------------|
| **eastus2** | **GlobalStandard**, DataZoneStandard |
| **southcentralus** | **GlobalStandard** |
| **swedencentral** | **GlobalStandard** |
| eastus | DataZoneProvisionedManaged, GlobalProvisionedManaged（無 Standard） |
| westus3 | DataZoneProvisionedManaged, GlobalProvisionedManaged |
| australiaeast | ProvisionedManaged, GlobalProvisionedManaged |
| japaneast | ProvisionedManaged, GlobalProvisionedManaged |
| westus / westus2 / northcentralus / uksouth / canadaeast / francecentral | 不可用 |

**結論：** eastus2 是離現有基礎設施最近且有 GlobalStandard 的區域，且 GPRAG 資源群組的 `aif-2v3lfktkn4xam-gprag` 已在 eastus2。

### 變更清單

#### 1. 模型部署（eastus2 `aif-2v3lfktkn4xam-gprag`）

| 動作 | 部署名稱 | 模型 | SKU | TPM |
|------|---------|------|-----|-----|
| 🆕 新建 | `gpt-54` | GPT-5.4 (2026-03-05) | GlobalStandard | 80K |
| 🆕 新建 | `gpt-5-mini` | GPT-5-mini (2025-08-07) | GlobalStandard | 80K |
| 🆕 新建 | `gpt-5-nano` | GPT-5-nano (2025-08-07) | GlobalStandard | 80K |
| 既有 | `chat` | GPT-5.2 (2025-12-11) | GlobalStandard | 80K |
| 既有 | `text-embedding` | text-embedding-3-large | Standard | 40K |

> ℹ️ `gpt-5-mini` 和 `gpt-5-nano` 從 eastus 資源同步建立到 eastus2，確保前端下拉選單顯示所有可用模型。

#### 2. App Configuration 更新

```
Key:   AZURE_OPENAI_ENDPOINT
Label: gpt-rag
舊值:  https://rag-open-ai-test.openai.azure.com/        (eastus)
新值:  https://aif-2v3lfktkn4xam-gprag.openai.azure.com/  (eastus2)
```

**影響範圍：**
- `/sales/models` API — 從新 endpoint 讀取可用模型清單
- `/sales/recommendation` Step 2 + Step 3 — LLM 呼叫改走新 endpoint
- 前端下拉選單 — 動態載入新 endpoint 的部署清單

#### 3. Orchestrator 程式碼修改

| 檔案 | 變更 |
|------|------|
| `src/main.py` | `RECOMMENDATION_DEPLOYMENT` 預設值 `gpt-52` → `gpt-54` |
| `src/main.py` | Step 3 註解 `GPT-5.2 reasoning model` → `GPT-5.4 reasoning model` |
| `src/connectors/sales_recommendation.py` | `RECOMMENDATION_DEPLOYMENT` 預設值 `gpt-52` → `gpt-54` |
| `src/connectors/sales_recommendation.py` | timeout 註解 `gpt-5.2` → `gpt-5.4` |

#### 4. 部署

```
Build:     az acr build → cr2v3lfktkn4xamgprag.azurecr.io/azure-gpt-rag/orchestrator:30d6b7e
Update:    az containerapp update → ca-2v3lfktkn4xam-orch-gprag
Revision:  ca-2v3lfktkn4xam-orch-gprag--0000035
Restart:   az containerapp revision restart
```

### 前端下拉選單效果

遷移後，`GET /sales/models` 回傳的部署清單：

| 部署 ID | 模型名稱 | 說明 |
|---------|---------|------|
| `gpt-54` | gpt-5.4 | 推薦話術預設（★） |
| `chat` | gpt-5.2 | 推薦話術備選 |
| `gpt-5-mini` | gpt-5-mini | 查詢生成預設（★） |
| `gpt-5-nano` | gpt-5-nano | 低成本測試用 |

> ℹ️ `text-embedding` 被前端過濾（非 gpt/o1/o3/o4 前綴），不顯示在下拉選單。

### 遷移前後對比

| 項目 | 遷移前 | 遷移後 |
|------|--------|--------|
| AZURE_OPENAI_ENDPOINT | `rag-open-ai-test` (eastus) | `aif-2v3lfktkn4xam-gprag` (eastus2) |
| Step 3 預設模型 | `gpt-52` (GPT-5.2) | `gpt-54` (GPT-5.4) |
| 前端可選模型 | gpt-52, gpt-5-mini, gpt-5-nano | gpt-54, chat (5.2), gpt-5-mini, gpt-5-nano |
| 資源類型 | OpenAI (舊版) | AIServices (新版，含 AI Foundry) |
| Orchestrator Image | `orchestrator:sales-20260318-collapsible` | `azure-gpt-rag/orchestrator:30d6b7e` |

---

## Phase 16: Persona 資料匯入與 MCP 連鎖修正（2026-03-18 ~ 03-19）

### 背景

從 Blob Storage 匯入新 persona Excel 至 Azure SQL 後，推薦功能全面異常。經排查發現匯入觸發了 6 個連鎖問題。

### 資料匯入

| 腳本 | 來源 | 筆數 | 說明 |
|------|------|------|------|
| `import_persona_from_blob.py` | Blob `documents/20260209/500_customer_persona_sanitized.xlsx` | 817 | DROP TABLE 重建，欄位為 `customerid` |
| `append_old_persona.py` | 本地 `persona_random_pick.1K.csv` | 1,185 | 追加舊資料，`unikey3` 對應為 `customerid`，不重複插入 |
| `backfill_tracking.py` | — | 1,641 | 回補 `persona_updated_at` / `persona_update_source` |

**匯入後 SQL 狀態：** 2,002 筆，1,999 不重複 customerid。

### 連鎖問題與修正

| # | 問題 | 根因 | 修正 | 影響檔案 |
|---|------|------|------|----------|
| 1 | SQL 欄位名稱不匹配 | DROP TABLE 重建後欄位從 `unikey3` 變成 `customerid`，MCP 仍查 `WHERE unikey3 = ?` | 所有 SQL 查詢改為 `WHERE customerid = ?` | `gpt-rag-mcp/src/tools/sql_persona.py`, `server.py`, `gpt-rag-orchestrator/src/schemas.py` |
| 2 | MCP server.py 語法錯誤 | 修改時 `@mcp.tool()def` 缺換行，容器啟動 crash | 補上換行 | `gpt-rag-mcp/src/server.py` |
| 3 | Cosmos DB 認證失敗 | Docker 容器無 `az` CLI，`az account get-access-token` 失敗 | 改用 `DefaultAzureCredential()`（Managed Identity） | `gpt-rag-mcp/src/tools/cosmos_transcripts.py` |
| 4 | MCP cold start 超時 | KEDA auto-scale 縮為 0 副本，orchestrator 呼叫時來不及回應 | `az containerapp update --min-replicas 1` | Container App 設定 |
| 5 | DATETIMEOFFSET 型別不支援 | 新增的 tracking 欄位（`persona_updated_at`）為 `DATETIMEOFFSET`，pyodbc 不支援 ODBC type -155 | `conn.add_output_converter(-155, str)` | `gpt-rag-mcp/src/tools/sql_persona.py` |
| 6 | Orchestrator LLM 參數不相容 | GPT-5-mini 不支援 `max_tokens` 和自訂 `temperature` | `max_tokens`→`max_completion_tokens`，移除 `temperature=0.3` | `gpt-rag-orchestrator/src/connectors/sales_recommendation.py`, `aifoundry.py` |

### MCP 部署歷史（6 次）

| Image Tag | 修正內容 |
|-----------|----------|
| `gpt-rag-mcp:fix-customerid` | SQL `unikey3`→`customerid` |
| `azure-gpt-rag/mcp:fix-customerid` | 修正 image repo 路徑 |
| `azure-gpt-rag/mcp:fix-customerid-v2` | 修正 server.py SyntaxError |
| `azure-gpt-rag/mcp:fix-cosmos-auth` | Cosmos `DefaultAzureCredential` |
| `azure-gpt-rag/mcp:fix-datetimeoffset` | DATETIMEOFFSET output converter |

### Orchestrator 部署歷史（3 次）

| Image Tag | 修正內容 |
|-----------|----------|
| `azure-gpt-rag/orchestrator:fix-max-tokens` | `max_tokens`→`max_completion_tokens` |
| `azure-gpt-rag/orchestrator:fix-temperature` | 移除 `temperature=0.3` |
| `azure-gpt-rag/orchestrator:debug-persona` | 加入 persona content preview log |

### 教訓

1. **匯入腳本不應 DROP TABLE** — 應改用 TRUNCATE + INSERT 或 MERGE/UPSERT 保護 schema
2. **部署前需 smoke test** — 至少查一筆 persona 驗證功能正常
3. **新增 SQL 欄位要考慮 pyodbc 相容性** — `DATETIMEOFFSET` 需加 output converter
4. **MCP 容器 min-replicas** — 生產環境應設 ≥ 1 避免 cold start 超時

---

## Phase 17: Demo UI 左右分割佈局 — 會員卡問答面板常駐展開（2026-03-20）

### 背景

原始 Demo 頁面（`/demo`）的會員卡權益問答功能以右下角浮動按鈕（FAB）觸發，需手動點擊展開，且對話視窗較小（400px 寬、最大 540px 高），不利於同時參考推薦話術與進行問答。

### 需求

1. 會員卡權益問答對話視窗**預設展開**
2. 對話視窗**加大至約畫面一半**
3. 推薦話術生成介面縮小，與對話視窗形成**左右分割佈局**

### 修改檔案

`gpt-rag-orchestrator/src/static/demo.html`

### 佈局變更

| 項目 | 修改前 | 修改後 |
|------|--------|--------|
| 整體佈局 | 單欄式，推薦話術佔滿寬度 | `flex` 左右分割（`.main-layout`） |
| 對話視窗 | 浮動面板（`position: fixed`），預設隱藏 | 固定右側面板（`.right-pane`），預設展開 |
| 對話視窗寬度 | 400px | `width: 50%`（min 380px, max 600px） |
| 對話視窗高度 | max-height 540px | 充滿整個視窗高度（`flex: 1`） |
| 推薦話術區域 | 佔滿 `max-width: 1100px` | 左側面板（`.left-pane`），`flex: 1` 自動填滿 |
| FAB 浮動按鈕 | 顯示於右下角 | 隱藏（`display: none`） |
| 關閉按鈕 | 對話標題列有 ✕ 關閉鈕 | 移除（面板常駐） |
| RWD 行為 | 480px 以下調整 FAB 位置 | 768px 以下切換為上下堆疊 |

### CSS 新增

```css
/* 全頁 flex 佈局 */
body { height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
.main-layout { display: flex; flex: 1; overflow: hidden; }
.left-pane { flex: 1; overflow-y: auto; min-width: 0; }
.right-pane { width: 50%; min-width: 380px; max-width: 600px; display: flex;
              flex-direction: column; border-left: 2px solid var(--border); }

/* RWD 768px 以下上下堆疊 */
@media (max-width: 768px) {
  .main-layout { flex-direction: column; }
  .right-pane { width: 100%; height: 50vh; border-left: none; border-top: 2px solid var(--border); }
}
```

### HTML 結構變更

```
修改前：
  <header>
  <div class="container"> ... 推薦話術 ... </div>
  <button class="chat-fab">💬</button>        ← 浮動按鈕
  <div class="chat-panel" id="chatPanel">     ← 浮動面板，預設隱藏

修改後：
  <header>
  <div class="main-layout">
    <div class="left-pane">
      <div class="container"> ... 推薦話術 ... </div>
    </div>
    <div class="right-pane">
      <div class="chat-panel" id="chatPanel">  ← 固定面板，預設展開
    </div>
  </div>
```

### 部署

- **Commit**: `48c8bf1` — `feat: split layout - chat panel expanded on right, recommendation on left`
- **Push**: `sensengo` remote → `sensengo-main` branch
- **Docker image**: `azure-gpt-rag/orchestrator:48c8bf1`
- **Container App**: `ca-2v3lfktkn4xam-orch-gprag` 已更新並重啟
- **部署方式**: `.\scripts\deploy.ps1`（自動化腳本）
