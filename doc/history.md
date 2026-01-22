# GPT-RAG 部署歷史記錄

## 專案資訊
- **部署日期**: 2026-01-08
- **目標資源組**: rg-ethan-test
- **部署類型**: 最小可執行環境 (無網路隔離)
- **來源**: https://github.com/Azure/GPT-RAG.git (已 fork 至 https://github.com/LadiosSopp/cht-rag-2.0.git)

---

## 步驟 1: 環境準備與工具檢查

### 為什麼執行
部署 GPT-RAG 需要以下工具:
- Azure Developer CLI (azd) - 主要部署工具
- Azure CLI (az) - Azure 資源管理和身份驗證
- Docker Desktop - 容器映像建置
- Python 3.11+ - 執行設定腳本

### 執行命令
```powershell
azd version
az version
az account show
docker info
python --version
azd auth login --check-status
```

### 執行結果
✅ **全部通過**

| 工具 | 版本/狀態 |
|------|----------|
| Azure Developer CLI (azd) | 1.22.5 |
| Azure CLI (az) | 2.80.0 |
| Docker | 29.1.3 |
| Python | 3.13.11 |
| Azure 訂閱 | MCAPS-Hybrid-REQ-50761-2023-zhanghe (Enabled) |
| azd 認證 | v-ktseng@microsoft.com ✅ |

---

## 步驟 2: 配額檢查 (eastus2 區域)

### 為什麼執行
在部署前需確認 Azure 訂閱在目標區域有足夠的資源配額，包括:
- Cosmos DB 佈建權限
- Azure OpenAI 模型配額 (GPT-5.2, text-embedding-3-large)

### 執行命令
```powershell
az cognitiveservices usage list --location eastus2 -o table
```

### 執行結果
✅ **eastus2 區域配額充足**
- Azure OpenAI 配額可用
- 可以繼續部署

---

## 步驟 3: 模型配置修改

### 為什麼執行
根據需求將預設的 GPT-4o 模型改為 GPT-5.2

### 修改檔案
1. `infra/main.bicep` - 預設模型配置
2. `infra/main.parameters.json` - 部署參數

### 修改內容
| 項目 | 原值 | 新值 |
|------|------|------|
| 模型名稱 | gpt-4o | gpt-4.1 |
| 版本 | 2024-11-20 | 2025-04-14 |

> ⚠️ **注意**: 原本計畫使用 gpt-5.2，但該模型在 Azure OpenAI 中尚不可用。
> 查詢可用模型後，選擇了最新的 gpt-4.1 (2025-04-14)。

---

## 步驟 4: 初始化 azd 環境

### 為什麼執行
設定部署環境變數:
- AZURE_LOCATION: eastus2
- AZURE_RESOURCE_GROUP: rg-ethan-test
- NETWORK_ISOLATION: false

### 執行命令
```powershell
azd init --environment gpt-rag-ethan
azd env set AZURE_LOCATION eastus2
azd env set AZURE_RESOURCE_GROUP rg-ethan-test
azd env set NETWORK_ISOLATION false
azd env get-values
```

### 執行結果
✅ **環境初始化完成**

```
AZURE_ENV_NAME="gpt-rag-ethan"
AZURE_LOCATION="eastus2"
AZURE_RESOURCE_GROUP="rg-ethan-test"
NETWORK_ISOLATION="false"
```

---

## 步驟 5: 執行 azd up 部署

### 為什麼執行
一次執行完整部署流程:
1. provision - 部署 Azure 基礎設施 (AI Foundry, AI Search, Cosmos DB, Container Apps 等)
2. deploy - 部署應用程式容器

### 執行命令
```powershell
azd up
```

### 執行結果
#### Provision 階段 ✅ 成功
已部署 22 項 Azure 資源:

| 資源類型 | 資源名稱 |
|----------|----------|
| Key Vault | kv-d5teispadppru |
| Log Analytics Workspace | log-d5teispadppru |
| Storage Account | std5teispadppru |
| Container Registry | crd5teispadppru |
| Application Insights | appi-d5teispadppru |
| Cosmos DB | cosmos-d5teispadppru |
| Container Apps Environment | cae-d5teispadppru |
| Azure AI Search | srch-d5teispadppru |
| Container App (Frontend) | ca-d5teispadppru-frontend |
| Container App (MCP) | ca-d5teispadppru-mcp |
| Container App (Data Ingestion) | ca-d5teispadppru-dataingest |
| Container App (Orchestrator) | ca-d5teispadppru-orchestrator |
| AI Foundry | aif-d5teispadppru |
| AI Key Vault | kvf-d5teispadppru |
| Chat Model Deployment | gpt-4.1 (2025-04-14) |
| Embedding Model Deployment | text-embedding-3-large |
| AI Foundry Cosmos DB | aiservices-d5teispadppru_cosmos |
| AI Foundry Search | srch-aifd5teispadppru |
| AI Foundry Storage | aifd5teispadppru |
| AI Foundry Project | project-d5teispadppru |
| AI Foundry Capability Host | caphost-d5teispadppru |
| App Configuration | appcs-d5teispadppru |

#### Deploy 階段 ⚠️ 手動修復
原始 `azd up` 的 deploy 腳本有 App Configuration 解析錯誤 (hostname 變成 `appcs-.azconfig.io`)。

**手動修復步驟:**
1. 從 GitHub 克隆所有組件 repos
2. 使用 Docker 手動建置 4 個容器映像
3. 推送至 Azure Container Registry
4. 使用 `az containerapp update` 更新各 Container App

#### 最終部署結果 ✅ 成功

**Container Registry 映像:**
| Repository | Tag | Digest |
|------------|-----|--------|
| azure-gpt-rag/frontend | 85f9446 | sha256:6410ec0c... |
| azure-gpt-rag/orchestrator | latest | sha256:180fdf20... |
| azure-gpt-rag/mcp | latest | sha256:1936c6df... |
| azure-gpt-rag/dataingest | latest | sha256:cd8f272a... |

**Container Apps 狀態:**
| Name | Status | Image |
|------|--------|-------|
| ca-d5teispadppru-frontend | Running | crd5teispadppru.azurecr.io/azure-gpt-rag/frontend:85f9446 |
| ca-d5teispadppru-orchestrator | Running | crd5teispadppru.azurecr.io/azure-gpt-rag/orchestrator:latest |
| ca-d5teispadppru-mcp | Running | crd5teispadppru.azurecr.io/azure-gpt-rag/mcp:latest |
| ca-d5teispadppru-dataingest | Running | crd5teispadppru.azurecr.io/azure-gpt-rag/dataingest:latest |

---

## 部署完成摘要

### 前端 URL
🌐 **https://ca-d5teispadppru-frontend.calmcoast-6a1d388b.eastus2.azurecontainerapps.io**

### 重要端點
| 服務 | URL |
|------|-----|
| Frontend | https://ca-d5teispadppru-frontend.calmcoast-6a1d388b.eastus2.azurecontainerapps.io |
| Orchestrator | https://ca-d5teispadppru-orchestrator.calmcoast-6a1d388b.eastus2.azurecontainerapps.io |
| MCP | https://ca-d5teispadppru-mcp.calmcoast-6a1d388b.eastus2.azurecontainerapps.io |
| Data Ingestion | https://ca-d5teispadppru-dataingest.calmcoast-6a1d388b.eastus2.azurecontainerapps.io |
| App Configuration | https://appcs-d5teispadppru.azconfig.io |
| AI Foundry | https://aif-d5teispadppru.openai.azure.com/ |
| Container Registry | crd5teispadppru.azurecr.io |

### 已部署模型
| 模型 | 版本 | 用途 |
|------|------|------|
| gpt-4.1 | 2025-04-14 | Chat/Completion |
| text-embedding-3-large | - | Embeddings |

### 部署環境變數
```
AZURE_ENV_NAME="gpt-rag-ethan"
AZURE_LOCATION="eastus2"
AZURE_RESOURCE_GROUP="rg-ethan-test"
AZURE_SUBSCRIPTION_ID="02243ba5-b777-47c6-9ecf-830b204b7593"
NETWORK_ISOLATION="false"
```

---

## 更新記錄

### 2026-01-12: SSE 換行修復

#### 問題描述
LLM 回應的換行符無法正確顯示，所有項目都連在一起。

#### 根本原因
SSE (Server-Sent Events) 格式使用 `\n\n` 作為訊息分隔符，導致內容中的換行符被吞掉。

#### 修復內容
**Orchestrator (`src/main.py`):**
```python
# 編碼換行符以避免 SSE 解析問題
encoded_chunk = chunk.replace("\n", "\\n")
yield f"data: {json.dumps({'content': encoded_chunk})}\n\n"
```

**Frontend (`app.py`):**
```python
# 解碼換行符
content = data.get("content", "").replace("\\n", "\n")
```

#### 部署版本
- **Orchestrator**: `gpt-rag-orchestrator:newline-fix-20260112`

---

### 2026-01-12: 動態狀態計時器

#### 問題描述
用戶請求將靜態的「思考中」訊息改為動態顯示處理階段和計時。

#### 實作內容
**Frontend (`app.py`):**
1. 新增 `asyncio` 背景任務，每 500ms 更新狀態
2. `STATUS_MESSAGES` 改為 tuple 格式: `{"thinking": ("🤔", "LLM 思考中"), ...}`
3. 新增 `format_dynamic_status()` 函數
4. 顯示格式:
   - 已完成: `✓ 🤔 LLM 思考中: 2.3秒`
   - 進行中: `▸ 🔍 搜尋知識庫: 1.5秒 ⏳`

#### 部署版本
- **Frontend**: `gpt-rag-frontend:live-timer-20260112`

---

### 2026-01-13: 對話記憶修復 (第一版)

#### 問題描述
LLM 無法記住對話中的資訊。用戶說「我是大胖」，後續問「你還記得我的名字嗎?」，LLM 卻去搜尋知識庫並回答「沒有足夠資訊」。

#### 根本原因
原始 prompt 指示「**每個問題都先搜尋知識庫**」，導致 LLM 忽略對話歷史。

#### 修復內容 (第一版)
**Prompt (`src/prompts/single_agent_rag/main.jinja2`):**
- 新增 "Conversation Context" 區塊

#### 部署版本
- **Orchestrator**: `gpt-rag-orchestrator:conv-history-20260113`

#### 測試結果
❌ 第一版修復無效，LLM 仍然會搜尋知識庫

---

### 2026-01-13: 對話記憶修復 (第二版) ✅

#### 問題描述
第一版修復後，LLM 仍然優先搜尋知識庫而非使用對話歷史。

#### 根本原因
Prompt 中仍保留「先搜尋再回答」的強制指令。

#### 修復內容 (第二版)
**Prompt (`src/prompts/single_agent_rag/main.jinja2`):**

1. **CRITICAL 優先級**: 對話上下文標示為最高優先級
2. **明確判斷規則**:
   - **不要搜尋**: 用戶名字、偏好、對話相關問題、已討論過的後續問題
   - **要搜尋**: 需要知識庫的新事實問題
3. **搜尋順序變更**:
   - 舊版: 「每個問題都先搜尋知識庫」
   - 新版: 「先檢查對話歷史，只有需要新資訊時才搜尋」

#### 關鍵 Prompt 變更
```jinja
## Conversation Context

**CRITICAL**: You have access to the full conversation history. 
ALWAYS check previous messages FIRST before searching:
- If the user asks about something mentioned in previous messages 
  (e.g., their name, preferences, previous questions), answer directly 
  from the conversation history - DO NOT search the knowledge base
- Questions about the conversation itself should NEVER trigger a search

## When to Search vs. When NOT to Search

**DO NOT search** for:
- Questions about the user (their name, preferences they mentioned)
- Questions about previous conversation
- Follow-up questions that refer to already retrieved information

**DO search** for:
- New factual questions requiring knowledge base information
```

#### 部署版本
- **Orchestrator**: `gpt-rag-orchestrator:conv-memory-v2-20260113`

#### 部署指令
```powershell
# 建置映像
az acr build --registry crd5teispadppru --image gpt-rag-orchestrator:conv-memory-v2-20260113 --file Dockerfile .

# 部署至 Container App
az containerapp update --name ca-d5teispadppru-orchestrator --resource-group rg-ethan-test --image crd5teispadppru.azurecr.io/gpt-rag-orchestrator:conv-memory-v2-20260113
```

#### 測試注意事項
⚠️ 因 Agent Reuse 機制，舊對話會繼續使用舊版 prompt。**測試時請開新對話**。

---

## 目前部署版本

| 元件 | 映像標籤 | 更新日期 |
|------|----------|----------|
| Frontend | `live-timer-20260112` | 2026-01-12 |
| Orchestrator | `conv-memory-v2-20260113` | 2026-01-13 |
| MCP | `latest` | 2026-01-08 |
| Data Ingestion | `latest` | 2026-01-08 |

---

### 2026-01-21: Container Apps 成本優化

#### 問題描述
部署幾天後，Azure Container Apps 成本快速累積到約 $200 USD，遠超預期。

#### 根本原因
Container Apps 使用 **D4 Dedicated Workload Profile**，即使 `min_replicas=0`，workload profile 本身仍持續計費：

| 費用項目 | 單價 | 每日費用 |
|---------|------|---------|
| Management Fee | $0.10/小時 | $2.40/天 |
| D4 vCPU (4核) | $0.0571/小時/核 | $5.48/天 |
| D4 Memory (16 GiB) | $0.0050/小時/GiB | $1.92/天 |
| **單一 D4 Profile 每日總計** | | **~$9.80/天** |

**結論**: ~$9.80/天 × 20天 ≈ $196 USD

#### 解決方案
將 Container Apps 從 D4 Dedicated Plan 改為 **Consumption-only** 環境。

#### 配置變更 (`main.parameters.json`)

**修改前:**
```json
"workloadProfiles": {
  "value": [
    { "name": "Consumption", "workloadProfileType": "Consumption" },
    { "workloadProfileType": "D4", "name": "main", "minimumCount": 0, "maximumCount": 1 }
  ]
}
// 所有 Container Apps: "profile_name": "main"
```

**修改後:**
```json
"workloadProfiles": {
  "value": [
    { "name": "Consumption", "workloadProfileType": "Consumption" }
  ]
}
// 所有 Container Apps: "profile_name": "Consumption"
```

#### 成本比較

| 項目 | D4 Dedicated | Consumption-only |
|------|--------------|------------------|
| 閒置成本 | ~$9.80/天 (~$294/月) | **$0** |
| Scale to Zero | Profile 仍計費 | **完全免費** |

#### 部署狀態
⚠️ **待部署** - 需要重新建立 Resource Group (已刪除 `rg-ethan-test`，但無權限建立新 RG)

#### 後續步驟
1. 請管理員建立 Resource Group `rg-ethan-test` (eastus2)
2. 執行 `azd up` 重新部署

---

### 2026-01-21: 部署參數更新

#### MCP 服務停用
```json
"deployMcp": { "value": "false" }
```
原因: 不需要 MCP 服務，減少資源使用

#### Chat Model 變更
```json
"chatModelName": { "value": "gpt-5.2" },
"chatModelVersion": { "value": "2025-04-14" }
```
原因: 升級至 GPT-5.2 以獲得更好的回答品質

---

### 2026-01-20: 多租戶 Ingestion 測試

#### 測試目的
驗證 GPT-RAG 多租戶架構的 Ingestion 流程

#### 執行步驟
1. 建立租戶專用 Blob Container: `documents-company-a`
2. 建立租戶專用 Search Index: `ragindex-company-a`
3. 上傳 2 個 PDF 至 `documents-company-a`
4. 修改 App Configuration (需使用 `gpt-rag` label):
   - `DOCUMENTS_STORAGE_CONTAINER` = `documents-company-a`
   - `SEARCH_RAG_INDEX_NAME` = `ragindex-company-a`
5. 重啟 Ingestion Container App (建立新 Revision)

#### 重要發現
- ⚠️ App Configuration 有**兩組同名 key**：一組有 `gpt-rag` label，一組沒有
- ⚠️ Ingestion Container 讀取的是帶 `gpt-rag` label 的配置
- ⚠️ 配置在容器啟動時載入並快取，需重啟才能套用新配置

#### 測試結果
✅ 成功！`ragindex-company-a` 有 2 個 chunks

```json
{
  "sourceContainer": "documents-company-a",
  "sourceFiles": 2,
  "indexedItems": 2,
  "totalChunksUploaded": 2
}
```

#### 架構確認
| 操作 | 配置方式 |
|------|----------|
| Ingestion (寫入) | App Configuration 預先指定 |
| Search (查詢) | API `search_index` 參數動態切換 |

---

### 2026-01-21: MCP Container 停用

#### 原因
- 目前只使用 `AGENT_STRATEGY=single_agent_rag`
- MCP Container 處於閒置狀態，浪費資源

#### 執行命令
```powershell
az containerapp update --name ca-d5teispadppru-mcp --resource-group rg-ethan-test --min-replicas 0 --max-replicas 0
```

#### 恢復方式
```powershell
az containerapp update --name ca-d5teispadppru-mcp --resource-group rg-ethan-test --min-replicas 1 --max-replicas 1
# 然後在 App Configuration 設定 AGENT_STRATEGY=mcp
```

---

### 2026-01-20: Document Intelligence 成本異常調查 🔴

#### 問題描述
Azure Document Intelligence 服務產生超過 **$2,000 USD** 的非預期費用，原本預估處理 89 個檔案（約 5,455 頁）成本應為 ~$55。

#### 根本原因分析

| 問題 | 影響 |
|------|------|
| **CRON 設定錯誤** | `*/5 * * * *` (每5分鐘) 而非 `0 */6 * * *` (每6小時) |
| **Container OOM** | 1Gi 記憶體不足，處理大檔案時被 Kill 後重啟 |
| **啟動時自動執行** | 每次重啟都觸發完整索引 |

**API 呼叫統計 (1/8-1/18):**
| 日期 | 呼叫次數 |
|------|---------|
| 1/8 | 851 |
| 1/13 | 2,703 |
| 1/18 | **7,809** |
| **總計** | **~17,215 次** |

#### 修復措施

1. **刪除問題 CRON 設定**
   ```powershell
   az appconfig kv delete --endpoint "https://appcs-d5teispadppru.azconfig.io" \
     --key "CRON_RUN_BLOB_INDEX" --label "gpt-rag-ingestion" --auth-mode login
   ```

2. **增加 Container 資源**
   ```powershell
   az containerapp update --name ca-d5teispadppru-dataingest \
     --resource-group rg-ethan-test --cpu 1.0 --memory 2Gi
   ```
   | 配置 | 修改前 | 修改後 |
   |------|-------|-------|
   | CPU | 0.5 | 1.0 |
   | Memory | 1Gi | 2Gi |

3. **新增啟動控制環境變數** (`main.py` 修改)
   ```python
   run_on_startup = os.getenv("RUN_JOBS_ON_STARTUP", "true").lower() in ("true", "1", "yes")
   if not run_on_startup:
       logging.info("[startup] RUN_JOBS_ON_STARTUP=false, skipping immediate job execution")
   ```
   ```powershell
   az appconfig kv set --endpoint "https://appcs-d5teispadppru.azconfig.io" \
     --key "RUN_JOBS_ON_STARTUP" --value "false" --auth-mode login
   ```

#### 修復驗證
| 檢查項目 | 狀態 |
|---------|------|
| Container App Health | ✅ Healthy |
| 03:00 後 API 呼叫 | ✅ 0 次 |
| 費用上升 | ✅ 已停止 |
| 檔案處理狀態 | ✅ 89/89 已完成 |

#### 教訓總結
1. CRON 表達式要仔細確認 (`*/5` vs `0 */6` 差別巨大)
2. App Configuration 的 label 機制要注意
3. Container 資源配置要考慮峰值需求
4. 設定成本警報是必要的

> 📄 詳細報告: [document-intelligence-cost-analysis.md](document-intelligence-cost-analysis.md)

---

## 2026-01-20: 大檔案索引測試

### 背景
修復 `max_tokens` API 錯誤後，需驗證大檔案處理能力。

### 測試方法
1. 將大檔案從 `documents-large` 複製回 `documents` 容器
2. 等待 CRON 週期 (`*/5 * * * *`) 處理
3. 監控日誌確認處理結果

### 測試結果

| 檔案 | 大小 | 處理時間 | Chunks | 狀態 |
|------|------|----------|--------|------|
| 蔦屋拜訪.pptx | 21 MB | 5.87 秒 | 5 | ✅ |
| 室內高爾夫練習場20250826.pptx | 31.3 MB | 33.61 秒 | 22 | ✅ |
| 中台拍賣市場分析-20250918-F.pptx | 32.5 MB | 16.54 秒 | 31 | ✅ |
| 野獸國合作報告_20250124.pptx | 37.9 MB | 12.78 秒 | 6 | ✅ |
| 世界知名景觀台調查V4.pptx | 41.6 MB | 17.26 秒 | 7 | ✅ |
| 202508_六大會機器人報告V4.pptx | 44.3 MB | 12.62 秒 | 14 | ✅ |
| 世界著名大樓20250314.pptx | **95 MB** | >40 分鐘 | - | ⏳ |
| 競業商場訪查報告_20250506.pptx | **97 MB** | >40 分鐘 | - | ⏳ |

### 關鍵發現

1. **APScheduler 保護機制**: `max_instances=1` 確保同時只有一個 job 執行
   - 當 job 執行中，新 CRON 觸發會顯示 `"maximum number of running instances reached (1)"` 並**跳過**
   - 不會重置正在執行的 job

2. **處理時間參考**:
   - 21-44 MB: 5-35 秒
   - 95+ MB: >40 分鐘 (Document Intelligence 瓶頸)

3. **建議**:
   - <50 MB 檔案可正常處理
   - >50 MB 檔案建議分割或隔離至 `documents-large`

> 📄 詳細測試數據: [ingestion-flow-analysis.md](ingestion-flow-analysis.md#大檔案處理效能測試-2026-01-20)

---

---

## 2026-01-15: 專案架構文件產生

### 背景
為了讓 LLM (Gemini) 能生成專案架構圖，需要一份結構化的架構說明文件。

### 執行內容
1. 分析所有子專案 README.md 及 infra/ Bicep 檔案
2. 整理 Azure 資源清單與用途
3. 繪製 ASCII 架構圖與資料流程圖

### 產出文件
📄 **[architecture-overview.md](architecture-overview.md)** - 專案架構總覽

包含內容:
| 章節 | 說明 |
|------|------|
| Multi-Repository Structure | 5 個子專案的關係與技術堆疊 |
| Azure Resources | 10+ Azure 服務清單及用途 |
| Components | 4 個主要元件 (Frontend, Orchestrator, Ingestion, MCP) 的詳細職責 |
| Data Flow | Query Processing Flow + Document Ingestion Flow (ASCII 圖表) |
| Service Communication | 服務間通訊架構 |
| Gemini Prompts | 3 個可直接使用的圖片生成 prompt |

### 關鍵架構摘要

```
Users → Frontend (Chainlit) → Orchestrator → AI Foundry Agent Service
                                    ↓
                    ┌───────────────┼───────────────┐
                    ↓               ↓               ↓
              Cosmos DB      AI Search      Azure OpenAI
              (歷史)         (檢索)          (LLM)

Documents → Blob Storage → Ingestion Service → AI Search Index
                                ↓
                         Azure OpenAI
                         (Embeddings)
```

---

## 2026-01-21: 環境重建準備

### 背景
需要在 `rg-ethan-test` 重新部署環境。

### 執行命令
```powershell
# 設定 azd 環境
azd env select ethan-test
azd env set AZURE_SUBSCRIPTION_ID "02243ba5-b777-47c6-9ecf-830b204b7593"
azd env set AZURE_LOCATION "eastus2"
azd env set AZURE_RESOURCE_GROUP "rg-ethan-test"

# 嘗試部署
azd provision --no-prompt
```

### 執行結果
❌ **部署失敗** - Resource Group 不存在或權限不足

### 待處理
- 需要管理員建立 Resource Group 或授權

---

## 目前狀態

| 項目 | 狀態 |
|------|------|
| Resource Group `rg-ethan-test` | ❌ 不存在/無權限 |
| 架構文件 | ✅ 已建立 [architecture-overview.md](architecture-overview.md) |
| 配置檔案 | ✅ 已更新為 Consumption-only |
| 重新部署 | ⏸️ 暫停 (需要 RG 權限) |
| Document Intelligence 費用 | ✅ 已停止上升 |

---

## 後續步驟
1. 請管理員建立 Resource Group `rg-ethan-test` (eastus2)
2. 執行 `azd up` 重新部署
3. 部署包含 `RUN_JOBS_ON_STARTUP` 控制的新版 Ingestion
4. 恢復 CRON 為合理頻率 (`0 */6 * * *`)
5. 設定 Azure 成本警報

---

## 2026-01-14: SAS URL 生成與連結處理修復

### 問題描述
1. 檔名包含**括號**（如 `林口商場(含招商).pptx`）時，Markdown 連結無法正確解析
2. 檔名包含**空格**時，URL 被截斷
3. 多個 Markdown 連結用頓號「、」連接時，regex 會錯誤地將它們合併成一個連結
4. LLM 輸出格式為 `(https://...)` 而非 `[title](url)` 時，SAS URL 未生成

### 根本原因

| 問題 | 原因 |
|------|------|
| 括號問題 | `REFERENCE_REGEX` 使用非貪婪 `.+?`，在第一個 `)` 就停止 |
| 空格問題 | `AZURE_BLOB_URL_REGEX` 將 `)` 和空格作為 URL 終止符 |
| 多連結問題 | 貪婪 `.+` 會匹配到最後一個副檔名，跨越多個連結 |
| 圓括號包 URL | `(?<!\()` negative lookbehind 排除了 `(` 後的 URL |

### 修復內容

**gpt-rag-ui/constants.py - REFERENCE_REGEX:**
```python
# 修改前: 非貪婪匹配，遇到第一個 ) 就停止
r'\[([^\]]+)\]\((.+?\.(?:' + extensions + r'))\)'

# 修改後: 使用 negative lookahead 防止跨連結匹配
r'\[([^\]]+)\]\(((?:(?!\)\s*[\[、\u3001]).)+\.(?:' + extensions + r'))\)'
```

**gpt-rag-ui/app.py - AZURE_BLOB_URL_REGEX:**
```python
# 修改前: 排除所有 ( 前綴的 URL
r'(?<!\()(https://...)'

# 修改後: 只排除 ]( 前綴 (Markdown 連結格式)
r'(?<!\]\()(https://...)'
```

### 部署版本
| 元件 | 映像標籤 | 說明 |
|------|----------|------|
| Frontend | `ch18` | 修復連結 regex |

### Git Commits
```
gpt-rag-ui:
- adb279e: fix: Handle parentheses in Markdown link URLs
- d1abc40: fix: Handle filenames with parentheses and spaces in Azure Blob URLs
- 4b06349: fix: Handle URLs wrapped in parentheses for SAS generation
- db4da33: fix: Prevent REFERENCE_REGEX from matching across multiple Markdown links
```

---

## 2026-01-14: Agent Tools 更新機制修復

### 問題描述
重用對話中的 agent 時，agent 沒有調用 `search_knowledge_base` 工具，直接從 LLM 知識回答。

### 根本原因
1. 對話中儲存的 agent 可能沒有正確的 tools 配置
2. 代碼只在 `existing_tool_count < required_tool_count` 時更新 tools
3. 如果 agent 有 1 個錯誤的 tool，不會觸發更新

### 修復內容

**gpt-rag-orchestrator/src/strategies/single_agent_rag_strategy_v1.py:**
```python
# 修改前: 只在工具數量不足時更新
if existing_tool_count < required_tool_count:
    # update tools...

# 修改後: 始終更新 tools 以確保配置正確
if self.tools_list:
    logging.info(f"[Agent Flow] 🔧 Updating agent tools: {existing_tool_count} -> {required_tool_count}")
    # update tools...
```

### 部署版本
| 元件 | 映像標籤 | 說明 |
|------|----------|------|
| Orchestrator | `ch5` | 強制更新 agent tools |

### Git Commits
```
gpt-rag-orchestrator:
- a2c3d09: fix: Always update agent tools when reusing to ensure correct configuration
```

---

## 2026-01-14: System Prompt 優化 (詳細回答)

### 問題描述
LLM 回答內容過於精簡，缺乏詳細資訊。

### 根本原因
System prompt 指示 "Provide a clear, **concise** answer"，導致 LLM 傾向簡短回答。

### 修復內容

**gpt-rag-orchestrator/src/prompts/single_agent_rag/main.jinja2:**
```jinja
# 修改前
- Provide a clear, concise answer based on the retrieved content

# 修改後
- Provide a **comprehensive and detailed answer** based on the retrieved content
- Include all relevant information from the search results - do not omit important details
- If multiple documents provide relevant information, synthesize them into a complete answer
```

### 部署版本
| 元件 | 映像標籤 | 說明 |
|------|----------|------|
| Orchestrator | `ch4` | 詳細回答 prompt |

### Git Commits
```
gpt-rag-orchestrator:
- f71317b: feat: Update prompt to encourage comprehensive detailed answers
```

### 注意事項
⚠️ 修改 prompt 後需刪除 `AGENT_ID_gpt5-chat` 讓系統建立新 agent：
```powershell
az appconfig kv delete --endpoint https://appcs-d5teispadppru.azconfig.io \
  --auth-mode login --key "AGENT_ID_gpt5-chat" --label "gpt-rag" --yes
```

---

## 2026-01-14: Agent ID 管理

### 問題描述
刪除 `AGENT_ID_gpt5-chat` 後，系統仍使用舊 agent（因為有 label）。

### 根本原因
App Configuration 的 key 有 `gpt-rag` label，需要指定 label 才能正確刪除。

### 正確刪除方式
```powershell
# 錯誤: 不指定 label
az appconfig kv delete --key "AGENT_ID_gpt5-chat" --yes  # 無效

# 正確: 指定 label
az appconfig kv delete --key "AGENT_ID_gpt5-chat" --label "gpt-rag" --yes  # 有效
```

### 目前 Agent ID 配置 (2026-01-15)
| Key | Value | 用途 |
|-----|-------|------|
| `AGENT_ID` | asst_1cYzcIQ7Oc878COanHhEp4o0 | 通用 fallback |
| `AGENT_ID_chat` | asst_syVTYFDqqdJHsY2LrNjvHxoI | chat 模型 |
| `AGENT_ID_gpt4.1-nano` | asst_EG2igcfKkCV28P0tr53l1oGp | gpt4.1-nano |
| `AGENT_ID_gpt5-mini` | asst_7Jv3IhnNE5Y0DLF12rMbMAid | gpt5-mini |
| `AGENT_ID_gpt5-nano` | asst_Dfa66wRA4JQduqEI2NPCNkeW | gpt5-nano |

> ⚠️ `AGENT_ID_gpt5-chat` 已刪除，系統會為每個對話動態建立/重用 agent

---

## 目前部署版本 (2026-01-15)

| 元件 | 映像標籤 | 更新日期 | 主要變更 |
|------|----------|----------|----------|
| Frontend | `ch18` | 2026-01-14 | SAS URL + 連結 regex 修復 |
| Orchestrator | `ch5` | 2026-01-14 | Agent tools 強制更新 |
| MCP | 已停用 | - | min_replicas=0 |
| Data Ingestion | `latest` | 2026-01-08 | - |

