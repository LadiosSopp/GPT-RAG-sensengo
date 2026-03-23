# GPT-RAG 專案 Source Code 指南

## 1. GitHub 官方 Repo（Azure 上游）

本專案基於 Microsoft Azure 的 GPT-RAG 開源方案，由以下五個 GitHub Repo 組成：

| 專案 | GitHub Repo | 說明 |
|------|-------------|------|
| **GPT-RAG（主專案）** | https://github.com/azure/GPT-RAG | 基礎架構 (Infrastructure as Code)、整合部署設定 |
| **gpt-rag-ingestion** | https://github.com/azure/gpt-rag-ingestion | 資料擷取與向量化處理（Chunking、Indexing） |
| **gpt-rag-orchestrator** | https://github.com/azure/gpt-rag-orchestrator | RAG 對話核心邏輯（Prompt、Strategy、Connectors） |
| **gpt-rag-ui** | https://github.com/azure/gpt-rag-ui | 前端 UI（基於 Chainlit） |
| **gpt-rag-mcp** | https://github.com/azure/gpt-rag-mcp | MCP Server（外部工具整合） |

---

## 2. 客製化專案與範例專案的差異

所有客製化修改皆基於上游 `origin/main` 分支，建立獨立的 `sensengo-main` 分支進行開發。

### 2.1 gpt-rag-orchestrator

#### 新增功能
- **銷售推薦 Agent** — 串接 AI Search、Cosmos DB、SQL Server 產生客戶銷售推薦結果
- **通話紀錄查詢** — 從 Cosmos DB 取得客戶通話摘要
- **Debug 模式** — 即時輸出 token 統計、搜尋結果等除錯資訊，支援 SSE streaming
- **精簡版 Prompt 模板** — 用於低延遲場景

#### 主要修改
- RAG 策略加入銷售推薦邏輯與 debug event streaming
- Prompt 客製化為銷售導向、客戶分析
- 搜尋邏輯重構，支援多索引切換

---

### 2.2 gpt-rag-ui

#### 新增功能
- **Debug 面板** — 前端顯示 token 使用量、搜尋結果、延遲統計

#### 主要修改
- 加入搜尋索引切換功能
- 配合新的 orchestrator API 簡化串接邏輯

---

### 2.3 gpt-rag-mcp

#### 新增功能（銷售推薦 Agent 所需的 MCP 工具）
- **AI Search 會員資料查詢** — 查詢會員相關資訊
- **Cosmos DB 通話紀錄查詢** — 取得客戶歷史通話紀錄
- **SQL Server 客戶畫像查詢** — 取得客戶消費行為與標籤

#### 主要修改
- MCP Server 註冊上述三個新工具

---

### 2.4 gpt-rag-ingestion

#### 主要修改
- Blob Storage、SharePoint 等核心 indexer 功能性調整
- 調整 Azure OpenAI 和 App Config 參數設定

---

## 3. 如何在 Azure 上查看 Source Code

客製化的 source code 已打包在 Docker image 中（每個 Dockerfile 都包含 `COPY . .`），可透過以下方式查看。

### 3.1 目前運行中的服務

| Container App | Image | Source 路徑 |
|---|---|---|
| `ca-2v3lfktkn4xam-orch-gprag` | `orchestrator:sales-20260318-collapsible` | `/app/` |
| `ca-2v3lfktkn4xam-frontend-gprag` | `frontend:prompt-20260225091224` | `/app/` |
| `ca-ingest-gprag` | `dataingest:20260125155500` | `/app/` |
| `ca-2v3lfktkn4xam-mcp-gprag` | `azure-gpt-rag/mcp:v2-20260311003507` | `/app/` |

### 3.2 方法一：Azure Portal Console（最簡單）

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

### 3.3 方法二：Azure CLI 遠端連線

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

### 3.4 方法三：從 ACR 拉取 Image 檢視

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

### 3.5 方法四：從 ACR 匯出檔案（不啟動容器）

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

---

## 4. 權限需求

| 查看方式 | 所需 Azure 權限 |
|----------|-----------------|
| Portal Console | Container App 的 Contributor 或以上角色 |
| Azure CLI exec | Container App 的 Contributor 或以上角色 |
| ACR pull image | ACR 的 AcrPull 角色 |

> **注意**: Azure Container Registry `cr2v3lfktkn4xamgprag` 和 Resource Group `GPRAG` 位於 **East US 2** 區域。
