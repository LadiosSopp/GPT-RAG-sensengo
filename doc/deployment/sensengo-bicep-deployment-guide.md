# Sensengo 專案 Bicep 基礎設施說明與部署指南

> **版本**: v1.0 | **日期**: 2026-03-27 | **基礎**: GPT-RAG Solution Accelerator v2.3.0

---

## 目錄

1. [專案架構概述](#1-專案架構概述)
2. [Bicep 部署架構說明](#2-bicep-部署架構說明)
3. [原版 GPT-RAG 與 Sensengo 客製化差異比較](#3-原版-gpt-rag-與-sensengo-客製化差異比較)
   - 3.1 [main.parameters.json — Feature Flags 差異](#31-mainparametersjson--feature-flags-差異)
   - 3.2 [main.parameters.json — AI 模型部署差異](#32-mainparametersjson--ai-模型部署差異)
   - 3.3 [main.bicep — 資源命名慣例差異](#33-mainbicep--資源命名慣例差異)
   - 3.4 [main.parameters.json — 部署標籤差異](#34-mainparametersjson--部署標籤差異)
   - 3.5 [main.bicep — Container Apps 部署差異](#35-mainbicep--container-apps-部署差異)
   - 3.6 [完整參數逐項解說](#36-完整參數逐項解說)
4. [resourceToken（資源名稱中的 Token）機制說明](#4-resourcetoken資源名稱中的-token機制說明)
5. [將專案 Clone 到另一個 Resource Group 的完整部署步驟](#5-將專案-clone-到另一個-resource-group-的完整部署步驟)
6. [部署後驗證](#6-部署後驗證)
7. [常見問題](#7-常見問題)

---

## 1. 專案架構概述

Sensengo 專案基於 Microsoft 的 **GPT-RAG Solution Accelerator v2.3.0** 進行客製化開發，包含以下子專案：

| 子專案 | 用途 | 部署目標 |
|--------|------|---------|
| **GPT-RAG** | 基礎設施定義（Bicep IaC）+ 部署腳本 | Azure 資源佈建 |
| **gpt-rag-orchestrator** | RAG 核心引擎（FastAPI） | Container App |
| **gpt-rag-ui** | 對話介面（Chainlit） | Container App |
| **gpt-rag-ingestion** | 文件處理與索引服務 | Container App |
| **gpt-rag-mcp** | Model Context Protocol 工具擴充（選用） | Container App（未啟用） |

### 專案 Repository 結構

```
sensengo/
├── GPT-RAG/                      ← 基礎設施主體（Bicep + 部署腳本）
│   ├── azure.yaml                ← azd 主設定檔
│   ├── infra/
│   │   ├── main.bicep            ← ★ 主要 Bicep 範本（所有資源定義於此）
│   │   ├── main.parameters.json  ← ★ 參數檔（Feature Flags、模型設定等）
│   │   ├── manifest.json         ← 元件版本清單
│   │   ├── constants/
│   │   │   ├── constants.bicep   ← 型別定義與常數匯入
│   │   │   ├── abbreviations.json← Azure 資源縮寫對照表
│   │   │   └── roles.json        ← RBAC 角色 GUID 對照表
│   │   └── modules/              ← 各資源的子模組
│   │       ├── ai-foundry/       ← AI Foundry 相關模組
│   │       ├── app-configuration/← App Configuration 設定模組
│   │       ├── container-apps/   ← Container Apps 清單模組
│   │       ├── networking/       ← VNet、Private DNS、Private Endpoint
│   │       └── security/         ← RBAC 角色指派模組
│   └── scripts/
│       ├── preProvision.ps1      ← 佈建前檢查腳本
│       └── postProvision.ps1     ← 佈建後自動配置腳本
├── gpt-rag-orchestrator/         ← Orchestrator 應用程式碼
├── gpt-rag-ui/                   ← Frontend 應用程式碼
├── gpt-rag-ingestion/            ← Ingestion 應用程式碼
└── gpt-rag-mcp/                  ← MCP Server 應用程式碼
```

> **重點理解**：**所有 Azure 基礎設施資源**（AI Foundry、Cosmos DB、AI Search、Storage、Container Apps 等）都是由 `GPT-RAG/infra/main.bicep` 這支主設定檔統一部署的。各子專案（orchestrator、ingestion、ui）裡的 `infra/main.bicep` 只有一行 `targetScope = 'resourceGroup'`，是 azd 框架的佔位符，不負責建立任何資源。這些子專案主要負責**應用程式的部署**（透過 `azd deploy` 將 Docker image 推送到 Container Apps）。

---

## 2. Bicep 部署架構說明

### 2.1 部署流程圖

```
                    GPT-RAG/azure.yaml
                           │
                    azd provision
                           │
              ┌────────────┼────────────┐
              │                         │
    scripts/preProvision.ps1    infra/main.bicep
    (網路隔離警告檢查)          (建立所有 Azure 資源)
                                        │
                               main.parameters.json
                               (參數值 + Feature Flags)
                                        │
                         ┌──────────────┼──────────────┐
                         │              │              │
                    modules/       constants/     manifest.json
                 (子模組 Bicep)   (縮寫/角色定義)  (版本清單)
                                        │
                              scripts/postProvision.ps1
                              (AI Foundry 設定、Container Apps 配置)
```

### 2.2 部署工具

本專案使用 **Azure Developer CLI (azd)** 作為部署引擎：

- `azd provision` — 執行 `GPT-RAG/infra/main.bicep`，建立所有基礎設施
- `azd deploy` — 將應用程式 Docker image 推送到 Container Apps
- 參數透過 `${ENV_VARIABLE_NAME}` 機制從 azd 環境變數注入到 `main.parameters.json`

### 2.3 main.bicep 主要組成區塊

| 區塊 | 行數範圍（約略） | 說明 |
|------|-----------------|------|
| **Parameters** | 55–330 行 | 所有可配置參數（位置、Feature Flags、資源名稱等） |
| **Variables** | 330–440 行 | 衍生變數（tags、網路計算、Feature Flag 轉換等） |
| **Networking** | 440–600 行 | VNet、Subnet、Bastion、NAT Gateway |
| **VM & Role Assignments** | 600–1000 行 | Jumpbox VM 及其 RBAC 權限 |
| **Private DNS Zones** | 1000–1170 行 | 各服務的 Private DNS 區域 |
| **Private Endpoints** | 1170–1450 行 | 各服務的 Private Endpoint |
| **AI Foundry** | 1450–1700 行 | AI Foundry Account、Project、模型部署、連接 |
| **Application Insights** | 1700–1900 行 | 監控相關資源 |
| **Container Resources** | 1900–2100 行 | Container Registry、Container Apps Environment、Container Apps |
| **Cosmos DB** | 2100–2200 行 | Cosmos DB Account 和 Database |
| **Key Vault** | 2200–2250 行 | 密鑰保管庫 |
| **Log Analytics** | 2250–2280 行 | 日誌分析工作區 |
| **AI Search** | 2280–2360 行 | 搜尋服務 |
| **Storage Account** | 2360–2420 行 | 儲存帳戶 |
| **Role Assignments** | 2420–2850 行 | 所有 RBAC 角色指派（Executor + Container Apps + Search） |
| **App Configuration** | 2850–3100 行 | App Config Store 建立 + 所有設定值寫入 |
| **Outputs** | 3100+ 行 | 輸出供後續腳本使用 |

---

## 3. 原版 GPT-RAG 與 Sensengo 客製化差異比較

### 3.1 main.parameters.json — Feature Flags 差異

以下表格列出所有 Feature Flag 以及原版預設值與 Sensengo 客製化值的對比：

| Feature Flag | 原版 GPT-RAG 預設 | Sensengo 客製值 | 差異原因 |
|-------------|-------------------|----------------|---------|
| `deployAiFoundry` | `true` | `true` | 相同，AI Foundry 為核心元件 |
| `deployAiFoundrySubnet` | `true` | `true` | 相同 |
| `deployAppConfig` | `true` | `true` | 相同，用於集中管理設定 |
| `deployAppInsights` | `true` | `true` | 相同，用於應用監控 |
| `deployCosmosDb` | `true` | `true` | 相同，用於對話歷史儲存 |
| `deployContainerApps` | `true` | `true` | 相同，微服務運行環境 |
| `deployContainerRegistry` | `true` | `true` | 相同，Docker 映像儲存 |
| `deployContainerEnv` | `true` | `true` | 相同 |
| `deployNsgs` | `true` | `true` | 相同 |
| `deployKeyVault` | `true` | `true` | 相同 |
| `deployLogAnalytics` | `true` | `true` | 相同 |
| `deploySearchService` | `true` | `true` | 相同，RAG 向量搜尋核心 |
| `deployStorageAccount` | `true` | `true` | 相同，文件儲存 |
| `greenFieldDeployment` | `true` | `true` | 相同，全新部署模式 |
| `deployGroundingWithBing` | **`true`** | **`false`** | ★ **關閉** — Sensengo 不使用 Bing 搜尋作為 grounding 來源，所有知識來自內部 RAG 知識庫 |
| `deployMcp` | `false` | `false` | 相同，MCP 為選用功能（但 Sensengo 後續手動部署了 MCP Container App） |
| `deployVM` | **`true`** | **`false`** | ★ **關閉** — Sensengo 不使用 Jumpbox VM，因為未啟用完整的 Zero Trust 網路隔離 |
| `deploySoftware` | **`true`** | **`false`** | ★ **關閉** — 與 deployVM 連動 |
| `deployPostgres` | `false` | `false` | 相同，Sensengo 使用 Cosmos DB + Azure SQL（外部），不需要 PostgreSQL |
| `useZoneRedundancy` | `false` | `false` | 相同，PoC/開發階段不需要異地備援 |
| `networkIsolation` | 環境變數控制 | 環境變數控制 | 相同，支援按需啟用 |
| `deployVmKeyVault` | 環境變數控制 | 環境變數控制 | 相同 |

### 3.2 main.parameters.json — AI 模型部署差異

這是最關鍵的客製化項目之一，定義在 `main.parameters.json` 的 `modelDeploymentList` 中：

| 項目 | 原版 GPT-RAG 預設 | Sensengo 客製值 | 差異原因 |
|------|-------------------|----------------|---------|
| **Chat 模型名稱** | `gpt-4.1` | **`gpt-5.2`** | 升級至更新模型以獲得更好的中文推理與話術生成能力 |
| **Chat 模型版本** | `2025-04-14` | **`2025-12-11`** | 對應 gpt-5.2 的版本 |
| **Chat 部署 SKU** | `GlobalStandard` / **10** TPM | `GlobalStandard` / **40** TPM | ★ 大幅提升配額至 40K TPM，因為推薦話術生成需要大量 tokens（gpt-5 系列的 reasoning token 消耗量大） |
| **Chat 部署名稱** | `gpt-4.1` | **`chat`** | 使用語義化部署名稱，與 App Config 中的 `CHAT_DEPLOYMENT_NAME` 對應 |
| **Embedding 模型** | `text-embedding-3-large` | `text-embedding-3-large` | 相同 |
| **Embedding 版本** | `1` | `1` | 相同 |
| **Embedding SKU** | `Standard` / **1** TPM | `Standard` / **40** TPM | ★ 大幅提升配額至 40K TPM，因為文件索引 (ingestion) 需要大量嵌入運算 |
| **Embedding 部署名稱** | `text-embedding-3-large` | **`text-embedding`** | 使用語義化名稱 |

> **原版 main.bicep 中的 fallback 預設**（當 `main.parameters.json` 未指定模型清單時）也定義了 `gpt-4.1` 10 TPM + `text-embedding-3-large` 1 TPM，可在 main.bicep 約 1500 行看到。Sensengo 透過 `main.parameters.json` 覆蓋了這些預設值。

### 3.3 main.bicep — 資源命名慣例差異

這是第二個核心客製化，直接修改了 `main.bicep` 中的資源命名預設值：

| 資源類型 | 原版 GPT-RAG 命名模式 | Sensengo 客製命名模式 | 差異說明 |
|---------|---------------------|---------------------|---------|
| AI Foundry Account | `aif-{token}` | `aif-{token}`**`-gprag`** | 加上 `-gprag` 後綴以區分專案 |
| AI Foundry Project | `aifp-{token}` | `aifp-{token}`**`-gprag`** | 同上 |
| AI Search | `srch-{token}` | `srch-{token}`**`-gprag`** | 同上 |
| App Configuration | `appcs-{token}` | `appcs-{token}`**`-gprag`** | 同上 |
| App Insights | `appi-{token}` | `appi-{token}`**`-gprag`** | 同上 |
| Container Apps Env | `cae-{token}` | `cae-{token}`**`-gprag`** | 同上 |
| Container Registry | `cr{token}` | `cr{token}`**`gprag`** | 無連字號（Registry 名稱不允許 `-`） |
| Cosmos DB Account | `cosmos-{token}` | `cosmos-{token}`**`-gprag`** | 同上 |
| Cosmos DB Database | `cosmos-db{token}` | `cosmos-db{token}`**`-gprag`** | 同上 |
| Key Vault | `kv-{token}` | `kv-{token}`**`-gprag`** | 同上 |
| Log Analytics | `log-{token}` | `log-{token}`**`-gprag`** | 同上 |
| Search Service | `srch-{token}` | `srch-{token}`**`-gprag`** | 同上 |
| Storage Account | `st{token}` | `st{token}` | **未加後綴**（Storage Account 名稱有嚴格長度限制） |
| VNet | `vnet-{token}` | `vnet-{token}` | **未加後綴** |
| Container Apps | `ca-{token}-{service}` | `ca-{token}-{service}`**`-gprag`** | 同上 |

**設定位置**：`GPT-RAG/infra/main.bicep` 第 248–299 行，各 `param` 的預設值。

**客製化目的**：在同一個 Azure 訂閱內可能有多個 GPT-RAG 部署，加上 `-gprag` 後綴可以：
1. 在 Azure Portal 中快速辨識哪些資源屬於此專案
2. 避免與其他 GPT-RAG 部署的資源名稱衝突
3. 搭配 `deploymentTags` 中的 `Project: GPRAG` 標籤做資源歸類

### 3.4 main.parameters.json — 部署標籤差異

| 項目 | 原版 GPT-RAG | Sensengo 客製 |
|------|-------------|--------------|
| `deploymentTags` | `{}` (空) | `{ "Project": "GPRAG" }` |

**目的**：所有資源加上 `Project: GPRAG` 標籤，方便在 Azure Portal 的 Resource Group 中依標籤篩選、成本分析歸類。

### 3.5 main.bicep — Container Apps 部署差異

| 項目 | 原版 GPT-RAG | Sensengo 客製 |
|------|-------------|--------------|
| Container Apps 清單 | orchestrator, frontend, dataingest | 相同三個服務 |
| external ingress | orchestrator: internal | **orchestrator: external** ★ |
| dataingest ingress | dataingest: internal | **dataingest: external** ★ |
| 資源配置 | 每個 0.5 vCPU / 1.0 Gi | 相同 |
| min_replicas | 0 | 0 |
| max_replicas | 1 | 1 |

> ★ **External Ingress 差異原因**：Sensengo 的 Orchestrator 和 DataIngest 設為 external，是因為開發/PoC 階段需要從外部直接呼叫 API 進行測試（例如推薦話術 API `/sales/recommendation`）。正式環境建議改回 internal。

### 3.6 完整參數逐項解說

以下是 `main.bicep` 中所有主要參數的完整說明：

#### 3.6.1 通用參數

| 參數名 | 類型 | 預設值 | 說明 |
|--------|------|--------|------|
| `environmentName` | string | 無（必填） | Azure Developer CLI 的環境名稱。用於生成 `resourceToken`，並作為 `azd-env-name` tag 附加到所有資源。 |
| `location` | string | `resourceGroup().location` | 所有資源的 Azure 區域。建議使用 `eastus2` 或 `japaneast`（需確認模型可用性）。 |
| `cosmosLocation` | string | `resourceGroup().location` | Cosmos DB 的部署區域。某些區域不支援 Serverless Cosmos DB，可單獨指定。 |
| `principalId` | string | 無（必填） | 執行部署的使用者或 Service Principal 的 Object ID。用於 RBAC 角色指派。azd 會透過 `${AZURE_PRINCIPAL_ID}` 自動注入。 |
| `principalType` | string | `'User'` | Principal 類型。一般使用者填 `User`；CI/CD pipeline 填 `ServicePrincipal`。 |
| `deploymentTags` | object | `{}` | 附加到所有資源的自訂標籤。Sensengo 設為 `{ Project: "GPRAG" }`。 |
| `networkIsolation` | bool | `false` | 啟用 Zero Trust 網路隔離。設為 `true` 會建立 VNet + Private Endpoints + NSGs，所有資源僅限私有網路存取。 |

#### 3.6.2 resourceToken 相關

| 參數名 | 類型 | 預設值 | 說明 |
|--------|------|--------|------|
| `resourceToken` | string | `toLower(uniqueString(subscription().id, environmentName, location))` | 根據訂閱 ID + 環境名稱 + 區域自動算出的 13 字元確定性雜湊。用於所有資源命名，確保全域唯一且可重複產生。 |

#### 3.6.3 Feature Flag 參數

| 參數名 | 類型 | 原版預設 | Sensengo 值 | 說明 |
|--------|------|---------|------------|------|
| `deployAiFoundry` | bool | `true` | `true` | 部署 Azure AI Foundry（AI 模型管理平台），含 Account + Project + 模型部署。 |
| `deployAiFoundrySubnet` | bool | `true` | `true` | 部署 AI Foundry Agent 專用 Subnet（網路隔離模式下使用）。 |
| `deployAfProject` | bool | `true` | `true` | 部署 AI Foundry Project。 |
| `deployAAfAgentSvc` | bool | `true` | `true` | 部署 AI Foundry Agent Service（Capability Host）。 |
| `deployAppConfig` | bool | `true` | `true` | 部署 Azure App Configuration，集中管理所有應用設定（endpoints、feature flags、model deployment names 等）。 |
| `deployKeyVault` | bool | `true` | `true` | 部署 Azure Key Vault，儲存 secrets、API keys。Container App API Key 會存放於此。 |
| `deployVmKeyVault` | bool | `true` | 環境變數控制 | 部署 VM 專用的 Key Vault（僅在 `deployVM=true` 時有意義）。 |
| `deployLogAnalytics` | bool | `true` | `true` | 部署 Log Analytics Workspace，收集所有資源的日誌。 |
| `deployAppInsights` | bool | `true` | `true` | 部署 Application Insights，連結 Log Analytics，提供應用效能監控（APM）。 |
| `deploySearchService` | bool | `true` | `true` | 部署 Azure AI Search（Basic SKU），用於 RAG 向量索引與混合搜尋。 |
| `deployStorageAccount` | bool | `true` | `true` | 部署 Azure Storage Account（Standard LRS），存放待索引文件（documents、documents-images、nl2sql 容器）。 |
| `deployCosmosDb` | bool | `true` | `true` | 部署 Azure Cosmos DB（Serverless 模式），存放對話歷史（conversations）、資料來源（datasources）、prompts、mcp。 |
| `deployContainerApps` | bool | `true` | `true` | 部署 Container Apps（orchestrator、frontend、dataingest 三個微服務）。 |
| `deployContainerRegistry` | bool | `true` | `true` | 部署 Azure Container Registry（Basic SKU），儲存 Docker 映像。 |
| `deployContainerEnv` | bool | `true` | `true` | 部署 Container Apps Environment（共用的運行環境，含 VNet 整合和日誌設定）。 |
| `deployGroundingWithBing` | bool | **`true`** | **`false`** | 是否部署 Bing Search 作為 grounding 來源。Sensengo 關閉此功能，所有知識來自自建 RAG 知識庫。 |
| `deployVM` | bool | **`true`** | **`false`** | 是否部署 Jumpbox VM。用於 Zero Trust 模式下從私有網路存取資源。Sensengo 不使用。 |
| `deploySoftware` | bool | **`true`** | **`false`** | 是否在 VM 上安裝軟體（az CLI、azd 等）。隨 `deployVM` 關閉。 |
| `deploySubnets` | bool | `true` | 環境變數控制 | 是否建立 VNet Subnets。 |
| `deployNsgs` | bool | `true` | `true` | 是否建立 Network Security Groups。 |
| `sideBySideDeploy` | bool | `true` | 環境變數控制 | 是否將網路資源與應用資源部署在相同 Resource Group。 |
| `deployApim` | bool | `false` | `false` | 是否部署 API Management（尚未實作，保留給未來）。 |
| `enableAgenticRetrieval` | bool | `false` | 環境變數控制 | 是否啟用 AI Search 的 Agentic Retrieval 功能。需要 semantic search 配置。 |

#### 3.6.4 認證與安全參數

| 參數名 | 類型 | 預設值 | 說明 |
|--------|------|--------|------|
| `useUAI` | bool | `false` | 使用 User Assigned Identity 而非 System Managed Identity。一般情況使用 System MI 即可。 |
| `useCAppAPIKey` | bool | `false` | 為 Container Apps 產生 API Key 並存入 Key Vault。啟用後各服務間通訊需帶 `X-API-KEY` header。 |
| `useZoneRedundancy` | bool | `false` | 對 Cosmos DB、Search、Registry 等啟用可用性區域冗餘備份。生產環境建議啟用。 |

#### 3.6.5 網路參數

| 參數名 | 預設值 | 說明 |
|--------|--------|------|
| `vnetAddressPrefixes` | `['192.168.0.0/21']` | VNet 位址空間，共 2048 個 IP。 |
| `agentSubnetPrefix` | `192.168.0.0/24` | AI Foundry Agent 專用子網（256 IPs）。 |
| `acaEnvironmentSubnetPrefix` | `192.168.1.0/24` | Container Apps Environment 子網（256 IPs）。 |
| `peSubnetPrefix` | `192.168.2.0/26` | Private Endpoint 子網（64 IPs），加大以避免並行建立 PE 時的 race condition。 |
| `useExistingVNet` | `false` | 是否使用既有 VNet。 |
| `existingVnetResourceId` | `''` | 既有 VNet 的 ARM Resource ID。 |

#### 3.6.6 資源命名參數

所有資源名稱都透過 `{abbreviation}{resourceToken}{suffix}` 模式產生。縮寫對照來自 `constants/abbreviations.json`：

| 參數名 | 縮寫 | 預設值範例 | 說明 |
|--------|------|-----------|------|
| `aiFoundryAccountName` | `aif-` | `aif-2v3lfktkn4xam-gprag` | AI Foundry 帳戶名稱 |
| `aiFoundryProjectName` | `aifp-` | `aifp-2v3lfktkn4xam-gprag` | AI Foundry 專案名稱 |
| `appConfigName` | `appcs-` | `appcs-2v3lfktkn4xam-gprag` | App Configuration 名稱 |
| `appInsightsName` | `appi-` | `appi-2v3lfktkn4xam-gprag` | Application Insights 名稱 |
| `containerEnvName` | `cae-` | `cae-2v3lfktkn4xam-gprag` | Container Apps Env 名稱 |
| `containerRegistryName` | `cr` | `cr2v3lfktkn4xamgprag` | Container Registry（不允許連字號） |
| `dbAccountName` | `cosmos-` | `cosmos-2v3lfktkn4xam-gprag` | Cosmos DB Account |
| `dbDatabaseName` | `cosmos-db` | `cosmos-db2v3lfktkn4xam-gprag` | Cosmos DB Database |
| `keyVaultName` | `kv-` | `kv-2v3lfktkn4xam-gprag` | Key Vault |
| `logAnalyticsWorkspaceName` | `log-` | `log-2v3lfktkn4xam-gprag` | Log Analytics Workspace |
| `searchServiceName` | `srch-` | `srch-2v3lfktkn4xam-gprag` | AI Search |
| `storageAccountName` | `st` | `st2v3lfktkn4xam` | Storage Account（無後綴） |
| `vnetName` | `vnet-` | `vnet-2v3lfktkn4xam` | Virtual Network（無後綴） |

> **如需修改後綴**：直接在 `GPT-RAG/infra/main.bicep` 第 251–299 行修改各 `param` 的預設值即可。

#### 3.6.7 AI 模型部署參數

定義在 `main.parameters.json` 的 `modelDeploymentList` 陣列中：

```json
{
  "name": "chat",                          // 部署名稱（對應 App Config 的 CHAT_DEPLOYMENT_NAME）
  "model": {
    "format": "OpenAI",                    // 模型格式
    "name": "gpt-5.2",                     // 模型 ID
    "version": "2025-12-11"                // 模型版本
  },
  "sku": {
    "name": "GlobalStandard",              // 部署類型（GlobalStandard = 全球路由）
    "capacity": 40                         // TPM（每分鐘千 token 數）
  },
  "canonical_name": "CHAT_DEPLOYMENT_NAME", // App Config 中的 Key 名稱
  "apiVersion": "2025-01-01-preview"        // Azure OpenAI API 版本
}
```

#### 3.6.8 Container Apps 參數

定義在 `main.parameters.json` 的 `containerAppsList` 陣列中。每個 Container App 的結構：

| 欄位 | 說明 |
|------|------|
| `name` | 設為 `null` 時使用自動命名：`ca-{token}-{service_name}-gprag` |
| `external` | `true` = 可從外部存取；`false` = 僅限 Container Apps Env 內部存取 |
| `service_name` | 服務識別名（orchestrator / frontend / dataingest） |
| `profile_name` | Workload Profile（`Consumption` = Serverless） |
| `min_replicas` / `max_replicas` | 0–1（scale-to-zero，閒置時不佔資源） |
| `canonical_name` | App Config 中對應的 Key（如 `ORCHESTRATOR_APP`） |
| `roles` | 需指派的 RBAC 角色清單 |

#### 3.6.9 Storage & Cosmos DB 容器

**Storage Account 容器** (`storageAccountContainersList`)：

| 容器名稱 | 用途 |
|----------|------|
| `documents` | 存放待索引的原始文件（PDF、XLSX、MD 等） |
| `documents-images` | 存放從文件中擷取的圖片 |
| `nl2sql` | Natural Language to SQL 相關資料 |

**Cosmos DB 容器** (`databaseContainersList`)：

| 容器名稱 | 用途 |
|----------|------|
| `conversations` | 使用者對話歷史 |
| `datasources` | 資料來源管理 |
| `prompts` | System Prompt 版本管理 |
| `mcp` | MCP 工具設定 |

---

## 4. resourceToken（資源名稱中的 Token）機制說明

### 4.1 什麼是 resourceToken？

當您看到資源名稱如 `srch-2v3lfktkn4xam-gprag`，其中的 `2v3lfktkn4xam` 就是 **resourceToken**。

### 4.2 如何產生？

```bicep
param resourceToken string = toLower(uniqueString(subscription().id, environmentName, location))
```

Bicep 的 `uniqueString()` 函式接受一組字串輸入，透過確定性的雜湊演算法產生一個 **13 字元的唯一字串**。三個輸入值：

| 輸入 | 來源 | 說明 |
|------|------|------|
| `subscription().id` | 自動 | Azure 訂閱的完整 ID |
| `environmentName` | `azd env` | 您設定的 azd 環境名稱 |
| `location` | `azd env` | Azure 部署區域 |

### 4.3 特性

- **確定性**：相同的 (subscription + environmentName + location) 組合，每次都會算出完全相同的 token
- **唯一性**：不同組合幾乎不可能產生相同的 token（SHA256 前 13 chars）
- **不可逆**：無法從 token 反推出輸入值
- **自動產生**：不需要手動設定，`azd provision` 時自動計算

### 4.4 在部署中的作用

在 `main.parameters.json` 中，所有資源名稱參數都設為 `null`：

```json
"appConfigName":     { "value": null },
"searchServiceName": { "value": null },
```

當 `null` 時，Bicep 會使用 `main.bicep` 中定義的預設值（含 `resourceToken`）。如需覆寫特定資源名稱，可以在 `main.parameters.json` 中填入自訂值。

### 4.5 林口大樓現有環境的 token

現有的 `2v3lfktkn4xam` 是由以下輸入產生的：
- Subscription ID：當時部署所用的訂閱
- Environment Name：當時設定的 `azd` 環境名稱
- Location：當時選擇的區域

> 部署到新環境時，只要 (subscription + environmentName + location) 有任何一個不同，就會產生不同的 token，從而產生一組全新的資源名稱。

---

## 5. 將專案 Clone 到另一個 Resource Group 的完整部署步驟

### 5.1 先決條件

#### 5.1.1 工具安裝

| 工具 | 最低版本 | 安裝指令 |
|------|---------|---------|
| **Azure CLI** | 2.80+ | `winget install Microsoft.AzureCLI` |
| **Azure Developer CLI (azd)** | 1.22+ | `winget install Microsoft.Azd` |
| **Docker Desktop** | 29+ | [官網下載](https://www.docker.com/products/docker-desktop/) |
| **Python** | 3.12 | `winget install Python.Python.3.12` |
| **Git** | 最新 | `winget install Git.Git` |

#### 5.1.2 Azure 權限

- 訂閱層級 **Owner** 或 **Contributor + User Access Administrator**
- 需註冊以下 Resource Provider（若尚未註冊）：

```powershell
az provider register --namespace Microsoft.AppConfiguration
az provider register --namespace Microsoft.DocumentDB
az provider register --namespace Microsoft.ContainerService
az provider register --namespace Microsoft.CognitiveServices
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.Search
```

#### 5.1.3 Azure OpenAI 模型配額

確保目標區域有足夠的模型配額：
- `gpt-5.2` — GlobalStandard 至少 40K TPM
- `text-embedding-3-large` — Standard 至少 40K TPM

```powershell
# 檢查可用區域的配額
az cognitiveservices usage list --location eastus2 --query "[?name.value=='OpenAI.Standard.gpt-5.2']"
```

### 5.2 Step-by-Step 部署流程

#### Step 1: 取得原始碼

```powershell
# Clone 專案（或從現有 repo 取得）
git clone <your-repo-url> sensengo
cd sensengo
```

#### Step 2: 登入 Azure

```powershell
# 登入指定租戶
az login --tenant <your-tenant-id>

# 設定目標訂閱
az account set --subscription "<subscription-name-or-id>"

# 確認目前身份
az ad signed-in-user show --query "{name:displayName, id:id}" -o table

# 驗證權限
az role assignment list --assignee $(az ad signed-in-user show --query id -o tsv) `
  --query "[].roleDefinitionName" -o table
```

#### Step 3: 初始化 azd 環境

```powershell
cd GPT-RAG

# 建立新的 azd 環境（名稱自訂，會影響 resourceToken 的計算）
azd init -e <your-environment-name>

# 設定部署區域（須確認模型可用性）
azd env set AZURE_LOCATION eastus2

# 設定 Principal ID（您的 Azure AD Object ID）
# azd 通常會自動偵測，如需手動設定：
azd env set AZURE_PRINCIPAL_ID $(az ad signed-in-user show --query id -o tsv)
```

> **重要**：`<your-environment-name>` + 訂閱 ID + 區域會決定新的 `resourceToken`，從而產生一組全新的資源名稱。

#### Step 4: 設定可選環境變數

```powershell
# 以下為可選，依需求設定：

# 啟用網路隔離（Zero Trust）— 預設關閉
# azd env set NETWORK_ISOLATION true

# 使用 User Assigned Identity — 預設關閉
# azd env set USE_UAI true

# 使用 Container App API Key — 預設關閉
# azd env set USE_CAPP_API_KEY true

# 啟用 Agentic Retrieval — 預設關閉
# azd env set ENABLE_AGENTIC_RETRIEVAL true
```

#### Step 5: 確認客製化設定

部署前檢查以下檔案中的設定是否符合需求：

**5.5.1 模型與計費（`main.parameters.json`）**

```powershell
# 檢查 modelDeploymentList 中的模型名稱、版本和 TPM
notepad infra/main.parameters.json
```

確認事項：
- `gpt-5.2` 在目標區域是否可用？
- 40K TPM 配額是否足夠？
- 是否需要調整模型版本？

**5.5.2 資源命名與後綴（`main.bicep`）**

若需更改 `-gprag` 後綴，編輯 `infra/main.bicep` 第 251–299 行：

```bicep
// 例如改為 -myproject
param appConfigName string = '${const.abbrs.configuration.appConfiguration}${resourceToken}-myproject'
```

**5.5.3 Feature Flags（`main.parameters.json`）**

確認以下設定是否符合需求：
- `deployGroundingWithBing`: `false`（不使用 Bing Grounding）
- `deployVM`: `false`（不部署 Jumpbox）
- `deployMcp`: `false`（不部署 MCP Container App）

#### Step 6: 建立 Resource Group

```powershell
# 建立新的 Resource Group
az group create --name <resource-group-name> --location eastus2 --tags Project=GPRAG

# 設定 azd 使用此 Resource Group
azd env set AZURE_RESOURCE_GROUP <resource-group-name>
```

#### Step 7: 佈建基礎設施

```powershell
# 在 GPT-RAG 目錄下執行
azd provision
```

**預期過程**：
1. `preProvision.ps1` — 執行前檢查（網路隔離警告等）
2. Bicep 部署 — 建立約 20-25 個 Azure 資源（約 15-30 分鐘）
3. `postProvision.ps1` — 自動配置 AI Foundry、Container Apps 設定

**預期輸出**（成功時）：
```
Provisioning Azure resources (azd provision)
...
SUCCESS: Your application was provisioned in Azure.
```

#### Step 8: 部署應用程式

**方式 A：使用 azd deploy（推薦）**

分別到各子專案目錄執行部署：

```powershell
# 部署 Orchestrator
cd ..\gpt-rag-orchestrator
azd deploy

# 部署 Frontend
cd ..\gpt-rag-ui
azd deploy

# 部署 Ingestion
cd ..\gpt-rag-ingestion
azd deploy
```

**方式 B：手動 Docker Build + Push（azd deploy 失敗時）**

```powershell
# 取得新的 resourceToken 和 Container Registry 名稱
# 從 azd 環境變數取得
azd env get-values | Select-String "CONTAINER_REGISTRY"

# 登入 Container Registry
az acr login --name <cr-name>

# 以 Orchestrator 為例
cd ..\gpt-rag-orchestrator
$ts = Get-Date -Format "yyyyMMddHHmmss"
docker build -t <cr-name>.azurecr.io/azure-gpt-rag/orchestrator:$ts .
docker push <cr-name>.azurecr.io/azure-gpt-rag/orchestrator:$ts

# 更新 Container App 映像
az containerapp update --name <ca-orchestrator-name> --resource-group <rg-name> `
  --image <cr-name>.azurecr.io/azure-gpt-rag/orchestrator:$ts
```

#### Step 9: 設定 App Configuration（客製化設定）

如果有 Sensengo 專屬的設定需要寫入：

```powershell
# 取得 App Config endpoint
$appConfigEndpoint = az appconfig show --name <appcs-name> --query endpoint -o tsv

# 設定額外的 App Configuration 值（範例）
az appconfig kv set --endpoint $appConfigEndpoint `
  --key "RECOMMENDATION_DEPLOYMENT" --value "gpt-5.4" --label "gpt-rag" --auth-mode login -y

az appconfig kv set --endpoint $appConfigEndpoint `
  --key "MCP_APP_ENDPOINT" --value "http://<mcp-container-app-fqdn>" --label "gpt-rag" --auth-mode login -y
```

#### Step 10: 上傳知識庫文件

```powershell
# 取得 Storage Account 名稱
$storageName = az storage account list --resource-group <rg-name> --query "[0].name" -o tsv

# 上傳文件到 documents 容器
az storage blob upload-batch --account-name $storageName `
  --destination documents --source ./path-to-your-documents/ `
  --auth-mode login
```

上傳後，Ingestion 服務會依 CRON 排程（`10 * * * *`，每小時第 10 分鐘）自動處理文件索引。

---

## 6. 部署後驗證

### 6.1 驗證清單

- [ ] Container Apps 狀態為 Running
- [ ] Frontend URL 可正常存取（瀏覽器開啟）
- [ ] AI Search 索引已建立
- [ ] App Configuration 參數正確
- [ ] 嘗試發送一個對話訊息確認端到端運作

### 6.2 驗證指令

```powershell
# 1. 檢查 Container Apps 狀態
az containerapp list --resource-group <rg-name> `
  --query "[].{name:name, state:properties.runningStatus}" -o table

# 2. 取得 Frontend URL
az containerapp show --name <ca-frontend-name> --resource-group <rg-name> `
  --query "properties.configuration.ingress.fqdn" -o tsv

# 3. 檢查 AI Search 索引
$searchEndpoint = "https://<srch-name>.search.windows.net"
$token = az account get-access-token --resource "https://search.azure.com" --query accessToken -o tsv
Invoke-RestMethod -Uri "$searchEndpoint/indexes?api-version=2023-11-01" `
  -Headers @{ Authorization = "Bearer $token" }

# 4. 檢查 App Configuration
az appconfig kv list --endpoint "https://<appcs-name>.azconfig.io" `
  --label "gpt-rag" --auth-mode login --query "[].{key:key, value:value}" -o table

# 5. 檢查 Container App 日誌
az containerapp logs show --name <ca-orch-name> --resource-group <rg-name> --tail 50
```

---

## 7. 常見問題

### Q1: 我可以直接複製現有的 resourceToken 嗎？

**不建議**。`resourceToken` 是確定性雜湊，如果您在不同的訂閱或區域部署，應該讓系統自動產生新的 token。如果堅持使用舊 token，可以在 `main.parameters.json` 中為每個資源名稱參數填入完整的舊名稱（覆寫預設值），但這可能造成名稱衝突。

### Q2: 部署到另一個 Resource Group 但在同一個訂閱，需要注意什麼？

- 如果 `environmentName` 和 `location` 與舊環境相同，`resourceToken` 也會相同，可能造成**全域名稱衝突**（如 Container Registry、Storage Account 名稱是全域唯一的）
- **建議**：使用不同的 `environmentName`（例如 `sensengo-dev` vs `sensengo-prod`）

### Q3: main.parameters.json 中 `null` 值代表什麼？

```json
"appConfigName": { "value": null }
```

`null` 代表使用 `main.bicep` 中定義的**預設值**（含 `resourceToken` 和 `-gprag` 後綴）。如果要覆寫特定資源名稱，可以在此填入自訂值。

### Q4: 如何查看現有環境的所有 azd 環境變數？

```powershell
cd GPT-RAG
azd env get-values
```

### Q5: 佈建失敗怎麼辦？

1. 先檢查錯誤訊息（通常是配額不足或區域不支援特定服務）
2. 修正問題後直接重跑 `azd provision`（Bicep 是冪等的，會只建立缺少的資源）
3. 如果需要完全重來，先刪除 Resource Group：`az group delete --name <rg-name>`

### Q6: 子專案的 infra/main.bicep 為何幾乎是空的？

各子專案（orchestrator、ingestion、ui）的 `infra/main.bicep` 只有 `targetScope = 'resourceGroup'`，因為：
- 所有基礎設施都由 `GPT-RAG/infra/main.bicep` 統一管理
- 子專案的 `azure.yaml` 只負責應用程式部署（`azd deploy`），不負責基礎設施
- 子專案的 `infra/main.bicep` 是 azd 框架要求的佔位檔

---

*本文件由 Sensengo 專案團隊提供，如有疑問請聯繫專案技術負責人。*
