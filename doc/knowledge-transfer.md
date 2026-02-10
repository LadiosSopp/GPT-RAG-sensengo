# GPT-RAG Sensengo 專案 Knowledge Transfer 文件

> **專案名稱**: GPT-RAG Sensengo (林口恩典大樓企業資訊 Agent)  
> **客戶**: 東森集團企業 (sensengo.com.tw)  
> **建立日期**: 2026年2月6日  
> **版本**: 1.0

---

## 📋 目錄

1. [專案概覽](#1-專案概覽)
2. [系統架構](#2-系統架構)
3. [部署指南](#3-部署指南)
4. [開發指南](#4-開發指南)
5. [維運指南](#5-維運指南)
6. [疑難排解](#6-疑難排解)
7. [附錄](#7-附錄)

---

## 1. 專案概覽

### 1.1 專案背景

東森集團正在興建「林口恩典大樓」(Grace Tower)，包含辦公室、酒店、餐廳、商場、教堂、展演空間等設施。此專案需要一個企業級 RAG (Retrieval-Augmented Generation) 系統，協助內部員工查詢專案相關資訊並進行商業規劃。

### 1.2 專案目標

| 目標 | 說明 |
|------|------|
| **正確性與創造性平衡** | Agent 需能精確回答資料，同時具備創意發想能力 |
| **多模態支援** | 處理 Word、PowerPoint、Excel、圖片等多種檔案格式 |
| **檔案管理** | 支援上傳、刪除、版本控管 |
| **跨裝置存取** | 支援桌面、手機、平板等多種裝置 |

### 1.3 技術選型

本專案採用 Microsoft GPT-RAG 解決方案加速器，基於以下技術：

| 層級 | 技術 |
|------|------|
| **AI 框架** | Azure AI Foundry Agent Service (azure-ai-agents>=1.2.0b4) |
| **LLM 模型** | GPT-5.2 (GlobalStandard) |
| **向量搜尋** | Azure AI Search (azure-search-documents 11.5~11.7) |
| **Embedding** | text-embedding-3-large |
| **後端框架** | FastAPI 0.115+ / Uvicorn 0.34+ / Python 3.12 |
| **前端框架** | Chainlit 2.6.0 |
| **AI 擴展** | Semantic Kernel 1.34+ (含 MCP 支援) |
| **容器運行** | Azure Container Apps (Consumption) |
| **IaC 工具** | Bicep + Azure Developer CLI (azd 1.22+) |

### 1.4 專案 Repository 結構

```text
sensengo/
├── GPT-RAG/                    # 主部署專案 (IaC)
├── gpt-rag-ui/                 # 前端服務
├── gpt-rag-orchestrator/       # 核心 RAG 編排引擎
├── gpt-rag-ingestion/          # 文件處理與索引服務
├── gpt-rag-mcp/                # Model Context Protocol 擴充 (選用)
├── doc/                        # 專案文件
└── scripts/                    # 輔助腳本
```

---

## 2. 系統架構

### 2.1 高層架構圖

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                     Container Apps Environment (cae-xxx)                      │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐                    ┌──────────────────┐                │
│  │    Frontend      │  HTTP/SSE          │   Orchestrator   │                │
│  │  (External       │◄──────────────────►│  (Internal       │                │
│  │   Ingress)       │                    │   Ingress)       │                │
│  │   Port: 80       │                    │   Port: 80       │                │
│  └──────────────────┘                    └──────────────────┘                │
│          ▲                                        │                          │
│          │                                        │                          │
│      Internet                                     │                          │
│      Users                     ┌──────────────────┼──────────────────┐       │
│                                │                  │                  │       │
│                                ▼                  ▼                  ▼       │
│                    ┌──────────────────┐  ┌──────────────┐  ┌──────────────┐  │
│                    │   MCP Server     │  │  Cosmos DB   │  │ AI Foundry   │  │
│                    │  (Optional)      │  │ (對話歷史)   │  │ Agent Svc    │  │
│                    └──────────────────┘  └──────────────┘  └──────────────┘  │
│                                                                    │         │
│  ┌──────────────────┐                                              │         │
│  │  Data Ingestion  │                                              ▼         │
│  │  (Internal       │──────────────────────────────────►┌──────────────────┐ │
│  │   Ingress)       │    Chunking + Embedding           │  Azure AI Search │ │
│  └──────────────────┘                                   │  (向量索引)      │ │
│          │                                              └──────────────────┘ │
│          ▼                                                                   │
│  ┌──────────────────┐                                                        │
│  │  Blob Storage    │                                                        │
│  │  (documents)     │                                                        │
│  └──────────────────┘                                                        │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Azure 資源清單

| 資源類型 | 命名規則 | SKU/層級 | 用途 |
|---------|---------|----------|------|
| **AI Foundry** | `aif-{token}-GPRAG` | Standard | AI 模型管理平台 |
| **Azure OpenAI** | (AI Foundry 內建) | GlobalStandard | LLM 推理 |
| **Azure AI Search** | `srch-{token}-GPRAG` | Basic | 向量與混合搜尋 |
| **Cosmos DB** | `cosmos-{token}-GPRAG` | Serverless | 對話歷史儲存 |
| **Container Apps** | `ca-{token}-*-GPRAG` | Consumption | 微服務運行 |
| **Container Apps Env** | `cae-{token}-GPRAG` | - | 共用環境 |
| **Container Registry** | `cr{token}GPRAG` | Standard | Docker 映像 |
| **Storage Account** | `st{token}GPRAG` | Standard LRS | 文檔儲存 |
| **App Configuration** | `appcs-{token}-GPRAG` | Standard | 集中配置 |
| **Key Vault** | `kv-{token}-GPRAG` | Standard | 密鑰管理 |
| **Log Analytics** | `log-{token}-GPRAG` | Pay-as-you-go | 日誌收集 |
| **Application Insights** | `appi-{token}-GPRAG` | Pay-as-you-go | 應用監控 |

> **Token 說明**: `{token}` 是由 azd 自動產生的唯一識別碼，例如 `2v3lfktkn4xam`

### 2.3 Container Apps 服務

| 服務 | Container App 名稱 | 功能 | Ingress |
|------|-------------------|------|---------|
| **Frontend** | `ca-{token}-frontend-GPRAG` | Chainlit 聊天介面 | External |
| **Orchestrator** | `ca-{token}-orch-GPRAG` | RAG 核心引擎 | Internal |
| **DataIngest** | `ca-ingest-GPRAG` | 文件處理與索引 | Internal |
| **MCP** | `ca-{token}-mcp-GPRAG` | 工具擴充 (選用) | Internal |

### 2.4 AI 模型部署

| 模型 | 部署名稱 | SKU | 容量 (TPM) | 用途 |
|------|---------|-----|-----------|------|
| **GPT-5.2** | `chat` | GlobalStandard | 80K | 對話生成 |
| **text-embedding-3-large** | `text-embedding` | Standard | 40K | 向量嵌入 |

### 2.5 資料流程

#### 查詢處理流程

```
1. 使用者在 Chainlit 介面輸入問題
          ↓
2. Frontend 發送 HTTP POST 到 Orchestrator (SSE 串流)
          ↓
3. Orchestrator 從 Cosmos DB 載入對話歷史
          ↓
4. Orchestrator 呼叫 Azure AI Foundry Agent Service
          ↓
5. Agent 決定呼叫 search_knowledge_base 工具
          ↓
6. AI Search 執行向量相似度搜尋，返回相關文件片段
          ↓
7. LLM (GPT-5.2) 根據檢索結果生成回應
          ↓
8. 回應透過 SSE 串流傳回 Frontend
          ↓
9. 對話儲存到 Cosmos DB
```

#### 文件 Ingestion 流程

```
1. 使用者上傳文件到 Blob Storage (documents container)
          ↓
2. Ingestion Service 依 CRON 排程觸發
          ↓
3. 讀取文件並依類型選擇 Chunker
   ├── PDF/DOCX/PPTX → Document Intelligence
   ├── XLSX → SpreadsheetChunker
   └── 其他 → LangChain Chunker
          ↓
4. 文件切分成 Chunks (預設 2048 tokens)
          ↓
5. Azure OpenAI 生成向量嵌入 (text-embedding-3-large)
          ↓
6. Chunks + Vectors 上傳到 Azure AI Search
          ↓
7. 寫入 Job 執行記錄
```

### 2.6 多租戶架構 (選用)

系統支援多租戶隔離，每個租戶可有獨立的文件容器和搜尋索引：

| 操作 | 配置方式 | 說明 |
|------|----------|------|
| **Ingestion (寫入)** | App Configuration 指定 | 批次處理，需預先設定目標 Index |
| **Search (查詢)** | API 動態切換 | 每次查詢可指定不同 Index |

**資源命名範例**：

| 租戶 | Blob Container | Search Index |
|------|----------------|--------------|
| 預設 | `documents` | `ragindex-{token}` |
| Company A | `documents-company-a` | `ragindex-company-a` |

**Ingestion 配置**：設定 App Configuration (需 `gpt-rag` label)
```
DOCUMENTS_STORAGE_CONTAINER = documents-company-{x}
SEARCH_RAG_INDEX_NAME = ragindex-company-{x}
```

**Search 動態切換**：Orchestrator API 支援 `search_index` 參數
```json
{
  "ask": "你的問題",
  "search_index": "ragindex-company-a"
}
```

---

## 3. 部署指南

### 3.1 先決條件

#### 工具安裝

| 工具 | 版本 | 安裝指令 |
|------|------|----------|
| Azure CLI | 2.80+ | `winget install Microsoft.AzureCLI` |
| Azure Developer CLI | 1.22+ | `winget install Microsoft.Azd` |
| Docker | 29+ | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
| Python | 3.12 | `winget install Python.Python.3.12` |
| Git | 最新 | `winget install Git.Git` |

#### Azure 權限

- 訂閱層級 **Owner** 或 **Contributor + User Access Administrator**
- 需註冊以下 Resource Provider：
  - `Microsoft.AppConfiguration`
  - `Microsoft.DocumentDB`
  - `Microsoft.ContainerService`
  - `Microsoft.CognitiveServices`

### 3.2 部署步驟

#### Step 1: 登入 Azure

```powershell
# 登入指定租戶
az login --tenant {tenant-id}

# 設定訂閱
az account set --subscription "{subscription-name}"

# 驗證權限
az role assignment list --assignee $(az ad signed-in-user show --query id -o tsv) --query "[].roleDefinitionName" -o table
```

#### Step 2: 設定 azd 環境

```powershell
cd GPT-RAG

# 初始化環境
azd init -e {environment-name}

# 設定區域
azd env set AZURE_LOCATION eastus2
```

#### Step 3: 佈建基礎設施

```powershell
# 執行 Bicep 部署
azd provision
```

預期結果：約 20-25 個 Azure 資源建立完成

#### Step 4: 部署應用程式

```powershell
# 部署所有服務
azd deploy
```

如果 `azd deploy` 失敗，可手動部署：

```powershell
# 登入 ACR
az acr login --name cr{token}

# 建置並推送 Frontend
cd ../gpt-rag-ui
$ts = Get-Date -Format "yyyyMMddHHmmss"
docker build -t cr{token}.azurecr.io/azure-gpt-rag/frontend:$ts .
docker push cr{token}.azurecr.io/azure-gpt-rag/frontend:$ts

# 更新 Container App
az containerapp update --name ca-{token}-frontend --resource-group GPRAG `
  --image cr{token}.azurecr.io/azure-gpt-rag/frontend:$ts
```

### 3.3 部署後驗證

#### 驗證清單

- [ ] Container Apps 狀態為 Running
- [ ] Frontend URL 可正常存取
- [ ] AI Search 索引已建立
- [ ] App Configuration 參數正確

#### 驗證指令

```powershell
# 檢查 Container Apps 狀態
az containerapp list --resource-group GPRAG --query "[].{name:name, state:properties.runningStatus}" -o table

# 檢查 AI Search 索引
$searchEndpoint = "https://srch-{token}.search.windows.net"
$token = az account get-access-token --resource "https://search.azure.com" --query accessToken -o tsv
Invoke-RestMethod -Uri "$searchEndpoint/indexes?api-version=2023-11-01" `
  -Headers @{ "Authorization" = "Bearer $token" }
```

---

## 4. 開發指南

### 4.1 本地開發環境設定

#### 環境變數

在每個服務目錄建立 `.env` 檔案：

```bash
# .env
APP_CONFIG_ENDPOINT=https://appcs-{token}-gprag.azconfig.io
AZURE_TENANT_ID={tenant-id}
AZURE_CLIENT_ID={client-id}  # 僅 User Assigned MI 需要
AZURE_CLIENT_SECRET={client-secret}  # 本地開發用
```

#### VS Code Launch 設定

各服務已包含 `launch.json`，可直接使用 F5 偵錯。

### 4.2 Debug 面板功能

Frontend 內建 Debug 面板，可顯示詳細的執行資訊：

**啟用方式**：
- 預設為啟用
- 輸入 `/debug off` 可關閉
- 輸入 `/debug` 或 `/debug on` 重新啟用

**顯示內容**：

| 面板 | 內容 |
|------|------|
| **Timing** | 各階段執行時間 (Thread/Agent 管理、LLM 思考、工具執行等) |
| **Prompting Details** | System Prompt、Tool Calls、Search Results、LLM Calls |

**UI 佈局**：左右分割 (問答區 55%、Debug Panel 45%)

### 4.3 關鍵程式碼路徑

#### Frontend (gpt-rag-ui)

| 檔案 | 說明 |
|------|------|
| `app.py` | Chainlit 事件處理 (on_chat_start, on_message) |
| `main.py` | FastAPI 入口，整合 Chainlit |
| `orchestrator_client.py` | 與 Orchestrator 的 HTTP/SSE 通訊 |
| `connectors/appconfig.py` | App Configuration 連線 |
| `public/debug-panels.js` | Debug 面板前端邏輯 |

#### Orchestrator (gpt-rag-orchestrator)

| 檔案 | 說明 |
|------|------|
| `src/main.py` | FastAPI 入口 |
| `src/orchestration/orchestrator.py` | 核心協調邏輯 |
| `src/strategies/single_agent_rag_strategy_v1.py` | 預設 Agent 策略 |
| `src/tools/aisearch_tool.py` | AI Search 檢索工具 |

#### Data Ingestion (gpt-rag-ingestion)

| 檔案 | 說明 |
|------|------|
| `main.py` | FastAPI + APScheduler 入口 |
| `jobs/blob_storage_indexer.py` | Blob 索引主邏輯 |
| `chunking/chunker_factory.py` | Chunker 選擇工廠 |
| `chunking/chunkers/doc_analysis_chunker.py` | Document Intelligence 切分 |
| `chunking/chunkers/spreadsheet_chunker.py` | Excel 切分 |

### 4.4 Agent 策略切換

系統支援三種 Agent 策略：

| 策略 | 設定值 | 說明 |
|------|--------|------|
| **Single Agent RAG** | `single_agent_rag` | 預設模式，單一 Agent + RAG 工具 |
| **MCP** | `mcp` | Model Context Protocol 擴充工具 |
| **NL2SQL** | `nl2sql` | 自然語言轉 SQL 查詢 |

切換方式：在 App Configuration 設定 `AGENT_STRATEGY`

```powershell
az appconfig kv set --endpoint "https://appcs-{token}.azconfig.io" `
  --key "AGENT_STRATEGY" --value "single_agent_rag" --label "gpt-rag" --auth-mode login -y
```

### 4.5 設定參數清單

#### 核心設定

| Key | 說明 | 預設值 |
|-----|------|--------|
| `AGENT_STRATEGY` | Agent 策略 | `single_agent_rag` |
| `CHAT_DEPLOYMENT_NAME` | LLM 部署名稱 | `chat` |
| `EMBEDDING_DEPLOYMENT_NAME` | Embedding 部署名稱 | `embedding` |
| `SEARCH_RAGINDEX_TOP_K` | 搜尋結果數量 | `3` |
| `SEARCH_APPROACH` | 搜尋方法 (hybrid/vector/term) | `hybrid` |
| `ORCHESTRATOR_URI` | Orchestrator 內部 URL | (自動設定) |

#### Ingestion 設定

| Key | 說明 | 預設值 |
|-----|------|--------|
| `CRON_RUN_BLOB_INDEX` | Blob 索引排程 | `0 */6 * * *` |
| `CRON_RUN_BLOB_PURGE` | Blob 清理排程 | `0 0 * * *` |
| `RUN_JOBS_ON_STARTUP` | 啟動時執行 Job | `true` |
| `DOCUMENTS_STORAGE_CONTAINER` | 文件容器名稱 | `documents` |
| `SEARCH_RAG_INDEX_NAME` | 搜尋索引名稱 | `ragindex-{token}` |

#### Chunking 設定

| Key | 說明 | 預設值 |
|-----|------|--------|
| `CHUNKING_NUM_TOKENS` | 一般文件 Chunk 大小 | `2048` |
| `TOKEN_OVERLAP` | Chunk 重疊 tokens | `100` |
| `CHUNKING_MIN_CHUNK_SIZE` | 最小 Chunk 大小 | `100` |
| `SPREADSHEET_CHUNKING_NUM_TOKENS` | Excel Chunk 大小 | `0` (無限制) ⚠️ |
| `SPREADSHEET_CHUNKING_BY_ROW` | 按列切分 Excel | `false` |

> ⚠️ **注意**: `SPREADSHEET_CHUNKING_NUM_TOKENS=0` 表示不限制大小，可能產生超大 Chunk (如 31,772 字元)。建議設為 `2048`。

#### Chunker 對應表

| 檔案類型 | Chunker |
|----------|---------|
| `.pdf`, `.docx`, `.pptx`, `.png`, `.jpg` | DocAnalysisChunker (使用 Document Intelligence) |
| `.xlsx`, `.xls` | SpreadsheetChunker |
| `.json` | JSONChunker |
| `.vtt` | TranscriptionChunker |
| `.md`, `.txt`, `.html`, `.py` | LangChainChunker |

---

## 5. 維運指南

### 5.1 日常維運作業

#### 上傳新文件

1. 透過 Azure Portal 或 azcopy 上傳至 Blob Storage 的 `documents` 容器
2. 等待 CRON 排程觸發 (預設每 6 小時)
3. 或手動觸發 Ingestion：

```powershell
# 呼叫 Ingestion API
Invoke-RestMethod -Uri "https://ca-ingest-gprag.xxx.azurecontainerapps.io/jobs/run-blob-indexer" -Method POST
```

#### 查看 Ingestion 狀態

```powershell
# 檢查 Job 記錄
az storage blob list --account-name st{token} --container-name jobs --output table
```

#### 重啟服務

```powershell
# 方法 1: 新增環境變數觸發新 Revision
$ts = Get-Date -Format "yyyyMMddHHmmss"
az containerapp update --name ca-{token}-frontend --resource-group GPRAG `
  --set-env-vars "RESTART_TS=$ts"

# 方法 2: 重新部署
az containerapp revision restart --name ca-{token}-frontend --resource-group GPRAG `
  --revision {revision-name}
```

### 5.2 監控與告警

#### Application Insights 查詢

```kusto
// 查看請求延遲
requests
| where timestamp > ago(1h)
| summarize avg(duration), percentile(duration, 95) by bin(timestamp, 5m)
| render timechart

// 查看錯誤
exceptions
| where timestamp > ago(1h)
| summarize count() by type, outerMessage
| order by count_ desc
```

#### 成本監控

| 服務 | 預估每日成本 | 說明 |
|------|-------------|------|
| AI Search (Basic) | ~$2.8 USD | 固定費用 |
| App Configuration | ~$1.2 USD | 固定費用 |
| Cosmos DB | ~$0.5 USD | 依使用量 |
| Container Apps | ~$0 | Scale to zero |
| **Azure OpenAI** | **依使用量** | 主要成本 |
| **Document Intelligence** | **依使用量** | Ingestion 時產生 |

⚠️ **成本警告**: Document Intelligence 按頁計費 ($10/1000頁)，大量 Ingestion 時需注意

### 5.3 備份與還原

#### Cosmos DB 備份

Cosmos DB Serverless 自動啟用連續備份，可透過 Azure Portal 進行 Point-in-time 還原。

#### AI Search 備份

```powershell
# 匯出索引定義
$indexName = "ragindex-{token}"
$searchEndpoint = "https://srch-{token}.search.windows.net"
$token = az account get-access-token --resource "https://search.azure.com" --query accessToken -o tsv

Invoke-RestMethod -Uri "$searchEndpoint/indexes/$indexName?api-version=2023-11-01" `
  -Headers @{ "Authorization" = "Bearer $token" } | ConvertTo-Json -Depth 10 > index-backup.json
```

---

## 6. 疑難排解

### 6.1 常見問題

#### 問題 1: Frontend 顯示 "An internal server error occurred."

**可能原因**:
1. Cosmos DB 防火牆阻擋
2. TPM 配額用完
3. Orchestrator 連線失敗

**排查步驟**:
```powershell
# 1. 檢查 Cosmos DB 網路設定
az cosmosdb show --name cosmos-{token} --resource-group GPRAG `
  --query "publicNetworkAccess"

# 2. 檢查 Orchestrator 日誌
az containerapp logs show --name ca-{token}-orch --resource-group GPRAG --tail 100
```

#### 問題 2: Ingestion 失敗 - AuthorizationFailure

**原因**: Storage Account `publicNetworkAccess` 設為 Disabled

**解決**:
```powershell
az storage account update --name st{token} --resource-group GPRAG `
  --public-network-access Enabled
```

#### 問題 3: Container App OOM Killed

**症狀**: Container 頻繁重啟，Exit Code 137

**解決**: 增加記憶體配置
```powershell
az containerapp update --name ca-ingest-gprag --resource-group GPRAG `
  --cpu 1.0 --memory 2Gi
```

#### 問題 4: 回應延遲過長 (~43 秒)

**分析**: 這是 Agent 架構的正常現象

| 階段 | 時間 | 說明 |
|------|------|------|
| Cosmos DB | ~4s | 載入對話歷史 |
| Agent 思考 | ~7s | 決定呼叫工具 |
| RAG 檢索 | ~1.5s | 搜尋 + Embedding |
| **LLM 生成** | **~27s** | 主要瓶頸 |

**優化建議**:
- 使用較小的模型 (如 GPT-4.1 Mini)
- 減少 `SEARCH_RAGINDEX_TOP_K`
- 簡化 System Prompt

### 6.2 已知問題

| 問題 | 狀態 | Workaround |
|------|------|------------|
| ManagedIdentityCredential 失敗 | 已修復 | 確保 `AZURE_CLIENT_ID` 為 None (不要設 "*") |
| SpreadsheetChunker 無限制大小 | 待處理 | 設定 `SPREADSHEET_CHUNKING_NUM_TOKENS=2048` |
| Azure Policy 自動關閉 Public Access | 持續發生 | 定期檢查並手動開啟 |
| upload_documents 未檢查結果 | 已修復 | `blob_storage_indexer.py` 已加入錯誤檢查 |

### 6.3 成本異常案例

#### Document Intelligence 成本失控 ($2,000+ USD)

**根本原因**：
1. CRON 設定錯誤 (`*/5 * * * *` 每 5 分鐘執行)
2. Container OOM (1Gi 記憶體不足) 導致重啟循環
3. 每次重啟觸發完整索引

**預防措施**：
```powershell
# 1. 正確的 CRON 設定
CRON_RUN_BLOB_INDEX = "0 */6 * * *"  # 每 6 小時

# 2. 足夠的記憶體
az containerapp update --name ca-ingest-gprag --resource-group GPRAG --cpu 1.0 --memory 2Gi

# 3. 停用啟動時自動執行
RUN_JOBS_ON_STARTUP = false

# 4. 設定 Azure 成本警報
```

---

## 7. 附錄

### 7.1 相關文件

| 文件 | 說明 |
|------|------|
| [architecture-overview.md](architecture-overview.md) | 系統架構詳細說明 |
| [deployment-troubleshooting.md](deployment-troubleshooting.md) | 部署問題排解 |
| [cost-estimation-summary.md](cost-estimation-summary.md) | 成本估算摘要 |
| [streaming-latency-analysis.md](streaming-latency-analysis.md) | 延遲分析報告 |
| [ingestion-flow-analysis.md](ingestion-flow-analysis.md) | Ingestion 流程分析 |
| [history.md](history.md) | 專案開發歷史記錄 |

### 7.2 重要聯絡資訊

| 角色 | 說明 |
|------|------|
| **Azure 訂閱** | ehs-ai-lab (2c9b3248-f263-4104-bd24-6446d4db84b9) |
| **Tenant** | 東森集團企業 (45f5172d-7608-4bd1-a52a-c3a7de0423d3) |
| **Resource Group** | GPRAG |
| **部署區域** | East US 2 |

### 7.3 版本歷史

| 版本 | 日期 | 變更說明 |
|------|------|----------|
| 1.0 | 2026-02-06 | 初版 KT 文件 |

---

*文件結束*
