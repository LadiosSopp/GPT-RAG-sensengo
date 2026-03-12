# Sales Recommendation Agent 開發歷史記錄

## 專案概述

為東森購物（EHS Shopping）建立 AI 電銷推薦話術系統。系統透過 3 步驟工作流程，結合客戶 Persona、通話紀錄與會員卡權益 RAG，由 GPT-5.2 推理模型自動產生個人化電銷話術。

---

## Phase 1: 架構設計與資料探索（2026-01 ~ 2026-02）

### 🔍 資料盤點

| 資料來源 | 位置 | 內容 | 筆數 |
|----------|------|------|------|
| 客戶 Persona | Azure SQL `ehs-sales-sqlserver` / `customer_persona_raw` | 結構化標籤 + 文字側寫 | 1,185 |
| 通話文本 | Cosmos DB `call-transcripts` | 電銷通話摘要 | 814 |
| 會員卡權益 | Azure AI Search `ragindex` | 權益手冊 / 收費說明 / 話術範本 | 876+ docs |

**發現問題：** Persona SQL (1,185 客戶) 與 Cosmos call-transcripts (814 客戶) 之間 0 筆 overlap。Demo 用客戶需手動複製 Persona。

### 📋 Demo 客戶準備

| Customer ID | 說明 |
|-------------|------|
| `26568707` | 第一位 Demo 客戶 |
| `24702892` | 第二位 Demo 客戶（Persona 從 10303606 複製） |

---

## Phase 2: MCP Server 建置

### 檔案：`gpt-rag-mcp/src/server.py`

基於 FastMCP，提供 StreamableHTTP 介面於 `/mcp`，共 7 個 MCP Tools：

| Tool | 類別 | 說明 |
|------|------|------|
| `query_customer_persona` | SQL Persona | 查詢客戶結構化 Persona 資料 |
| `search_customer_by_field` | SQL Persona | 依欄位搜尋客戶（性別/縣市/OB等級/星座） |
| `query_call_transcripts` | Cosmos | 查詢客戶通話原文 |
| `query_call_summary` | Cosmos | 查詢客戶通話摘要 |
| `search_membership_card` | AI Search | 搜尋會員卡權益 RAG（`ragindex`） |
| `wikipedia_search` | 雜項 | Wikipedia 搜尋 |
| `add` | 雜項 | 測試用加法 |

**關鍵實作：**
- `tools/sql_persona.py` — pyodbc + SQL Auth，Docker 用 `{ODBC Driver 18 for SQL Server}`，本機用 `{SQL Server}`
- `tools/cosmos_transcripts.py` — Azure SDK + AAD Auth
- `tools/aisearch_membership.py` — REST API + Admin Key，連接 AI Search `ragindex`

---

## Phase 3: Orchestrator 整合

### 檔案：`gpt-rag-orchestrator/src/main.py`

FastAPI 應用，新增端點：

| 路由 | 方法 | 用途 |
|------|------|------|
| `/sales/recommendation` | POST | 電銷推薦 API（主要端點） |
| `/demo` | GET | Demo 網頁 UI（3 個頁籤） |
| `/orchestrator` | POST | 原有 GPT-RAG 路由 |

### 檔案：`gpt-rag-orchestrator/src/connectors/sales_recommendation.py`

核心 `SalesRecommendationClient` 類別，實作 3 步驟工作流程：

```
Step 1: MCP → fetch_persona + fetch_call_summary
Step 2: GPT-4o-mini 分析 → 動態 RAG 查詢 → MCP search_membership_card
Step 3: GPT-5.2 reasoning model → 產生完整推薦話術 JSON
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

### 改版（LLM-driven Step 2）— 2026-03-11

改用 **GPT-4o-mini** 動態分析 Persona + Call Log 產生 RAG 查詢。

**新增：**
- `QUERY_GEN_PROMPT` 類別常數 — 指示 gpt-4o-mini 分析消費力、興趣、家庭狀況、通話痛點、禁忌
- `_build_membership_query_with_llm()` — 呼叫 gpt-4o-mini（`max_tokens=200`, `temperature=0.3`），失敗時 fallback 為基本關鍵字
- Debug 新增 `llm_query_generation` 步驟，記錄 LLM 產生的查詢與耗時

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

### Azure OpenAI 模型部署（Resource: `rag-open-ai-test` / RG: `AzureOpenAI`）

| 部署名稱 | 模型 | 版本 | 用途 |
|----------|------|------|------|
| `gpt-52` | GPT-5.2 | 2025-12-11 | Step 3 推薦話術生成（50K TPM / 500 RPM） |
| `gpt-4o-mini` | GPT-4o-mini | 2024-07-18 | Step 2 動態 RAG 查詢生成 |
| `gpt-4o` | GPT-4o | 2024-05-13 | 一般用途 |
| `text-embedding-3-small` | — | — | Embedding |
| `text-embedding-ada-002` | — | — | Embedding（舊） |

**GPT-5.2 限制：** 不支援 `max_tokens` / `temperature` / `response_format`，須用 `max_completion_tokens=4000`。

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
| 2026-03-11 | `orchestrator:sales-20260311140704` | LLM-driven Step 2 (gpt-4o-mini query generation) |

---

## Phase 6: Demo 網頁

### 檔案：`gpt-rag-orchestrator/src/static/demo.html`

瀏覽器存取 `/demo`，3 個頁籤：
1. **推薦結果** — 格式化顯示推薦話術 JSON
2. **Debug 資訊** — 各步驟耗時、I/O 記錄
3. **原始 JSON** — 完整 API 回應

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
| `doc/architecture.mmd` | 架構圖 Mermaid 原始碼 |
| `doc/flow.mmd` | 流程圖 Mermaid 原始碼 |
| `doc/architecture.png` | 架構圖 PNG（~329 KB） |
| `doc/flow.png` | 流程圖 PNG（~315 KB） |
| `doc/render_png.py` | Playwright + local HTTP server + mermaid.js 渲染腳本 |

### 渲染設定
- Playwright Chromium，`device_scale_factor=2`（高解析度）
- `useMaxWidth: false`（避免 SVG 被壓縮）
- 中文字體：Microsoft JhengHei / 微軟正黑體 / Noto Sans TC
- `<meta charset="utf-8">` 確保中文不亂碼
- mermaid `themeVariables.fontFamily` 指定中文字體

### 渲染指令
```powershell
cd c:\SynologyDrive\LTIMindtree\Projects\東森\sensengo
python doc\render_png.py
```

---

## 端到端測試結果（2026-03-11）

**測試客戶：** 26568707（64 歲高雄女性，OB 等級 A）

| 步驟 | 耗時 | 說明 |
|------|------|------|
| fetch_persona | 0.21s | SQL → 客戶 Persona |
| fetch_call_summary | 0.03s | Cosmos → 通話摘要（AAD token 問題，fallback） |
| llm_query_generation | 1.91s | GPT-4o-mini 分析 → 動態查詢 |
| search_membership_card | 0.12s | AI Search RAG 搜尋 |
| gpt_recommendation | 75.84s | GPT-5.2 產生完整推薦話術 |
| **Total** | **78.13s** | |

**LLM 產生的 RAG 查詢範例：**
> 搜尋東森會員卡權益，針對高雄市大社區64歲女性，消費力等級A，關注健康與美容，適合的保健產品優惠、健身活動、旅遊折扣，並考慮家庭共享型權益，避免與乳糖相關的產品及高價商品。

**GPT-5.2 推薦結果包含：**
- 客戶剖析（消費力 A / 保健偏好 / 乳糖禁忌）
- 推薦方案：東森林口會員卡（晶華 × UFC 尊榮生活圈）
- 完整話術：開場白 → 需求探詢 → 產品推薦 → 利益點 → 異議處理（4 種情境） → 收尾 → 追蹤
- 禁忌清單、推薦產品（3 項）、溝通風格建議、成交機率評估

---

## 已知問題與限制

| 問題 | 狀態 | 說明 |
|------|------|------|
| Cosmos AAD Token（Docker） | ⚠️ Workaround | Container 內 `az` CLI 不可用，AAD token 取得失敗→ 通話摘要為空 |
| Persona / Call-transcript 零重疊 | ⚠️ 資料問題 | 實際資料 0 交集，demo 用客戶需手動複製 |
| GPT-5.2 回應時間長 | ℹ️ 正常 | Reasoning model 約 60-80s，已設 timeout 600s |
| Container Apps Ingress Timeout | ✅ 已設 240s | 預設 30s 不足，已調整為 240s |

---

## 技術棧摘要

```
Frontend:  Static HTML (demo.html) → FastAPI StaticFiles
Backend:   FastAPI + Semantic Kernel + MCPStreamableHttpPlugin
MCP:       FastMCP (StreamableHTTP) — 7 tools
Models:    GPT-5.2 (reasoning) + GPT-4o-mini (query gen)
Data:      Azure SQL + Cosmos DB + Azure AI Search
Infra:     Azure Container Apps + ACR + App Configuration
Auth:      Managed Identity (AAD) + API Key fallback
Diagrams:  Mermaid → Playwright → PNG
```
