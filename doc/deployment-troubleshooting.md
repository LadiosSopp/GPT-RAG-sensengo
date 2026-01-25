# GPT-RAG 部署問題排解指南

> 本文件記錄了在 Azure 上部署 GPT-RAG 解決方案時遇到的問題及其解決方法。
> 
> **部署日期**: 2026-01-08 ~ 2026-01-09  
> **環境**: {resource-group} / {environment-name}  
> **區域**: eastus2  
> **模式**: 無網路隔離 (Minimal Configuration)

---

## 目錄

1. [部署概述](#部署概述)
2. [問題 1: Deploy 階段失敗 - App Configuration 解析錯誤](#問題-1-deploy-階段失敗---app-configuration-解析錯誤)
3. [問題 2: Ingestion 失敗 - Storage Account AuthorizationFailure](#問題-2-ingestion-失敗---storage-account-authorizationfailure)
4. [問題 3: 前端查詢失敗 - Cosmos DB 防火牆阻擋](#問題-3-前端查詢失敗---cosmos-db-防火牆阻擋)
5. [問題 4: AZURE_CLIENT_ID 設定錯誤 (已撤銷)](#問題-4-azure_client_id-設定錯誤-已撤銷)
6. [完整修復步驟](#完整修復步驟)
7. [部署後驗證清單](#部署後驗證清單)

---

## 部署概述

### 使用的工具版本

| 工具 | 版本 |
|------|------|
| Azure CLI | 2.80.0 |
| Azure Developer CLI (azd) | 1.22.5 |
| Docker | 29.1.3 |
| Python | 3.12 (容器內) |

### 部署架構

```
Resource Group: {resource-group}
├── Container Apps Environment (cae-{token})
│   ├── ca-{token}-frontend (前端 UI)
│   ├── ca-{token}-orchestrator (RAG 編排器)
│   ├── ca-{token}-dataingest (資料攝取)
│   └── ca-{token}-function (Azure Functions)
├── Storage Account (st{token})
├── Cosmos DB (cosmos-{token}) - 對話歷史
├── Cosmos DB (cosmos-aif-{token}) - AI Foundry
├── AI Search (srch-{token})
├── AI Services (aif-{token})
├── App Configuration (appcs-{token})
├── Container Registry (cr{token})
└── Key Vault (kv-{token})
```

---

## 問題 1: Deploy 階段失敗 - App Configuration 解析錯誤

### 症狀

執行 `azd up` 時，Provision 階段成功完成（22 個資源已建立），但 Deploy 階段失敗。

### 錯誤訊息

```
ERROR: error executing step command 'deploy --all': failed deploying service 'orchestrator': 
failing because of error getting app config client: 
failed to parse Azure App Configuration URI '': 
invalid Azure App Configuration URI ''
```

### 根本原因

`deploy.ps1` 腳本無法從 `azd env get-values` 正確解析 `AZURE_APP_CONFIG_URI` 環境變數。

### 解決方法

**手動部署 Container Apps**：繞過 `azd deploy`，直接使用 Docker 建置映像並推送到 ACR。

#### 步驟 1: Clone 所有元件 Repo

```powershell
cd "C:\SynologyDrive\LTIMindtree\Source Code\GPT-RAG-2.0"

# Clone 四個元件 repos
git clone https://github.com/Azure/gpt-rag-frontend.git
git clone https://github.com/Azure/gpt-rag-orchestrator.git
git clone https://github.com/Azure/gpt-rag-ingestion.git
git clone https://github.com/Azure/gpt-rag-agentic.git
```

#### 步驟 2: 登入 ACR

```powershell
$ACR_NAME = "cr{token}"
az acr login --name $ACR_NAME
```

#### 步驟 3: 建置並推送映像

```powershell
# Frontend
cd gpt-rag-frontend
docker build -t "$ACR_NAME.azurecr.io/azure-gpt-rag/frontend:latest" .
docker push "$ACR_NAME.azurecr.io/azure-gpt-rag/frontend:latest"

# Orchestrator
cd ../gpt-rag-orchestrator
docker build -t "$ACR_NAME.azurecr.io/azure-gpt-rag/orchestrator:latest" .
docker push "$ACR_NAME.azurecr.io/azure-gpt-rag/orchestrator:latest"

# Dataingest
cd ../gpt-rag-ingestion
docker build -t "$ACR_NAME.azurecr.io/azure-gpt-rag/dataingest:latest" .
docker push "$ACR_NAME.azurecr.io/azure-gpt-rag/dataingest:latest"

# Function
cd ../gpt-rag-agentic
docker build -t "$ACR_NAME.azurecr.io/azure-gpt-rag/function:latest" .
docker push "$ACR_NAME.azurecr.io/azure-gpt-rag/function:latest"
```

#### 步驟 4: 更新 Container Apps

```powershell
$RG = "{resource-group}"
$ACR = "cr{token}.azurecr.io"

# 更新四個 Container Apps
az containerapp update --name ca-{token}-frontend --resource-group $RG --image "$ACR/azure-gpt-rag/frontend:latest"
az containerapp update --name ca-{token}-orchestrator --resource-group $RG --image "$ACR/azure-gpt-rag/orchestrator:latest"
az containerapp update --name ca-{token}-dataingest --resource-group $RG --image "$ACR/azure-gpt-rag/dataingest:latest"
az containerapp update --name ca-{token}-function --resource-group $RG --image "$ACR/azure-gpt-rag/function:latest"
```

---

## 問題 2: Ingestion 失敗 - Storage Account AuthorizationFailure

### 症狀

上傳文件到 Storage Account 的 `documents` 容器後，Ingestion 作業無法執行，日誌顯示 `AuthorizationFailure`。

### 錯誤訊息

```json
{
  "Log": "[ERROR] root: [blob-storage-indexer-purger] Unexpected error",
  "Log": "azure.core.exceptions.HttpResponseError: This request is not authorized to perform this operation.",
  "Log": "ErrorCode:AuthorizationFailure"
}
```

### 根本原因

**Storage Account 的 `publicNetworkAccess` 設定為 `Disabled`**

在「無網路隔離」模式下，Container Apps 沒有 VNet 整合，因此需要透過公開網路存取 Storage Account。但 Bicep 模板預設禁用了公開網路存取。

### 診斷命令

```powershell
# 檢查 Storage Account 網路設定
az storage account show --name st{token} --resource-group {resource-group} `
  --query "{publicNetworkAccess: publicNetworkAccess, defaultAction: networkRuleSet.defaultAction}"
```

輸出（問題狀態）：
```json
{
  "defaultAction": "Allow",
  "publicNetworkAccess": "Disabled"  // <-- 這是問題！
}
```

> ⚠️ **重要**: `defaultAction: Allow` 不代表可以存取！當 `publicNetworkAccess: Disabled` 時，所有公開網路請求都會被拒絕。

### 解決方法

```powershell
# 啟用 Storage Account 公開網路存取
az storage account update `
  --name st{token} `
  --resource-group {resource-group} `
  --public-network-access Enabled

# 驗證設定
az storage account show --name st{token} --resource-group {resource-group} `
  --query "{publicNetworkAccess: publicNetworkAccess}"
```

---

## 問題 3: 前端查詢失敗 - Cosmos DB 防火牆阻擋

### 症狀

Ingestion 修復後，前端查詢時顯示 `An internal server error occurred.`

### 錯誤訊息

Orchestrator 日誌：
```
(Forbidden) Request originated from IP 20.10.114.230 through public internet. 
This is blocked by your Cosmos DB account firewall settings.
```

### 根本原因

**兩個 Cosmos DB 帳戶的 `publicNetworkAccess` 設定為 `Disabled`**

### 診斷命令

```powershell
# 檢查 Cosmos DB 網路設定
az cosmosdb list --resource-group {resource-group} `
  --query "[].{name: name, publicNetworkAccess: publicNetworkAccess}" -o table
```

輸出（問題狀態）：
```
Name                      PublicNetworkAccess
------------------------  ---------------------
cosmos-aif-{token}  Disabled
cosmos-{token}      Disabled
```

### 解決方法

```powershell
# 啟用兩個 Cosmos DB 帳戶的公開網路存取
az cosmosdb update --name cosmos-{token} `
  --resource-group {resource-group} `
  --public-network-access Enabled

az cosmosdb update --name cosmos-aif-{token} `
  --resource-group {resource-group} `
  --public-network-access Enabled

# 驗證設定
az cosmosdb list --resource-group {resource-group} `
  --query "[].{name: name, publicNetworkAccess: publicNetworkAccess}" -o table
```

---

## 問題 4: AZURE_CLIENT_ID 設定錯誤 (已撤銷)

### 症狀

嘗試設定 `AZURE_CLIENT_ID` 環境變數後，應用程式啟動失敗。

### 錯誤訊息

```
azure.identity.aio._credentials.chained.ChainedTokenCredential failed to retrieve a token 
from the included credentials.
```

### 根本原因

**Container Apps 使用 System Assigned Managed Identity 時，不應設定 `AZURE_CLIENT_ID`**

設定 `AZURE_CLIENT_ID` 會導致 Azure Identity SDK 嘗試使用 User Assigned Managed Identity 的驗證流程，但實際上沒有配置該身分。

### 解決方法

**不要設定 `AZURE_CLIENT_ID`**，讓 SDK 自動使用 System Assigned Managed Identity。

```powershell
# 如果已經設定，需要移除（設為空字串）
az containerapp update --name ca-{token}-dataingest `
  --resource-group {resource-group} `
  --set-env-vars "AZURE_CLIENT_ID="
```

> ⚠️ **教訓**: 對於 System Assigned Managed Identity，`AZURE_CLIENT_ID` 應保持為空。

---

## 完整修復步驟

如果您遇到類似問題，以下是完整的修復步驟：

### 1. 修復網路存取設定

```powershell
$RG = "{resource-group}"
$STORAGE = "st{token}"

# 1. 啟用 Storage Account 公開網路存取
az storage account update --name $STORAGE --resource-group $RG --public-network-access Enabled

# 2. 啟用 Cosmos DB 公開網路存取
az cosmosdb update --name cosmos-{token} --resource-group $RG --public-network-access Enabled
az cosmosdb update --name cosmos-aif-{token} --resource-group $RG --public-network-access Enabled
```

### 2. 重啟 Container Apps（觸發新的 Revision）

```powershell
$timestamp = Get-Date -Format "yyyyMMddHHmmss"

# 更新環境變數以觸發新的 Revision
az containerapp update --name ca-{token}-dataingest --resource-group $RG `
  --set-env-vars "RESTART_TIMESTAMP=$timestamp"
  
az containerapp update --name ca-{token}-orchestrator --resource-group $RG `
  --set-env-vars "RESTART_TIMESTAMP=$timestamp"
```

### 3. 驗證設定

```powershell
# 檢查 Storage Account
az storage account show --name $STORAGE --resource-group $RG `
  --query "{publicNetworkAccess: publicNetworkAccess}" -o json

# 檢查 Cosmos DB
az cosmosdb list --resource-group $RG `
  --query "[].{name: name, publicNetworkAccess: publicNetworkAccess}" -o table

# 檢查 Container App 日誌
az containerapp logs show --name ca-{token}-dataingest `
  --resource-group $RG --tail 50 --follow false
```

---

## 部署後驗證清單

### ✅ 基礎設施驗證

- [ ] 所有 22 個 Azure 資源已建立
- [ ] Container Apps 正常運行 (Healthy)
- [ ] Storage Account `publicNetworkAccess: Enabled`
- [ ] Cosmos DB `publicNetworkAccess: Enabled`

### ✅ Ingestion 驗證

```powershell
# 檢查 AI Search 索引
$searchEndpoint = "https://srch-{token}.search.windows.net"
$token = az account get-access-token --resource "https://search.azure.com" --query accessToken -o tsv
$indexName = "ragindex-{token}"

# 獲取索引統計
Invoke-RestMethod -Uri "$searchEndpoint/indexes/$indexName/stats?api-version=2023-11-01" `
  -Headers @{ "Authorization" = "Bearer $token" }
```

預期輸出：
```json
{
  "documentCount": 1,
  "storageSize": 91751
}
```

### ✅ 前端驗證

1. 開啟前端 URL: `https://ca-{token}-frontend.calmcoast-6a1d388b.eastus2.azurecontainerapps.io`
2. 輸入測試問題: "What are the benefit options available?"
3. 驗證收到來自文件的回答（非錯誤訊息）

---

## 預防措施

### 在 Bicep 模板中修改預設值

如果使用「無網路隔離」模式，建議在部署前修改 Bicep 模板：

**infra/core/storage/storage-account.bicep**:
```bicep
param publicNetworkAccess string = 'Enabled'  // 預設改為 Enabled
```

**infra/core/database/cosmos/cosmos-account.bicep**:
```bicep
param publicNetworkAccess string = 'Enabled'  // 預設改為 Enabled
```

### 或者使用參數覆蓋

在 `main.parameters.json` 中添加：
```json
{
  "publicNetworkAccessEnabled": {
    "value": true
  }
}
```

---

## 相關資源

- [GPT-RAG GitHub Repository](https://github.com/Azure/GPT-RAG)
- [Azure Container Apps 文件](https://learn.microsoft.com/azure/container-apps/)
- [Azure Storage 網路安全](https://learn.microsoft.com/azure/storage/common/storage-network-security)
- [Cosmos DB 防火牆設定](https://learn.microsoft.com/azure/cosmos-db/how-to-configure-firewall)

---

## 問題 5: Document Intelligence 成本異常 (2026-01-20)

### 症狀
Azure Document Intelligence 服務產生超過 **$2,000 USD** 的非預期費用。

### 根本原因

| 問題 | 說明 |
|------|------|
| **CRON 設定錯誤** | `*/5 * * * *` (每5分鐘) 導致每天執行 288 次 |
| **Container OOM** | 1Gi 記憶體處理大型 PPTX 時被 OOM Kill，觸發重啟循環 |
| **啟動時自動執行** | `main.py` 在 Container 啟動時立即執行完整索引 |

### 解決方法

#### 1. 刪除問題 CRON 設定
```powershell
# 備份
az appconfig kv set --endpoint "https://appcs-xxx.azconfig.io" \
  --key "CRON_RUN_BLOB_INDEX_BACKUP" --value "13 * * * *" --auth-mode login

# 刪除
az appconfig kv delete --endpoint "https://appcs-xxx.azconfig.io" \
  --key "CRON_RUN_BLOB_INDEX" --label "gpt-rag-ingestion" --auth-mode login -y
```

#### 2. 增加 Container 記憶體
```powershell
az containerapp update --name ca-xxx-dataingest \
  --resource-group rg-xxx --cpu 1.0 --memory 2Gi
```

#### 3. 新增啟動控制環境變數
在 `gpt-rag-ingestion/main.py` 中加入：
```python
run_on_startup = os.getenv("RUN_JOBS_ON_STARTUP", "true").lower() in ("true", "1", "yes")
if not run_on_startup:
    logging.info("[startup] RUN_JOBS_ON_STARTUP=false, skipping immediate job execution")
```

設定環境變數：
```powershell
az appconfig kv set --endpoint "https://appcs-xxx.azconfig.io" \
  --key "RUN_JOBS_ON_STARTUP" --value "false" --auth-mode login
```

### 預防措施

1. **CRON 設定檢查**: 使用 `check_cron_settings.py` 驗證排程
2. **Container 資源**: 處理大型檔案需至少 2Gi 記憶體
3. **成本警報**: 在 Azure Portal 設定預算警報
4. **監控**: 定期檢查 `az monitor metrics list --metric "TotalCalls"`

> 📄 詳細分析: [document-intelligence-cost-analysis.md](document-intelligence-cost-analysis.md)

---

## 問題 6: Container App 更新後前端沒有變化

### 症狀

執行 `az containerapp update` 後，網頁重新整理仍顯示舊版本。

### 根本原因

1. **Docker cache**: 使用 `:latest` tag 時，若 image digest 相同，Azure 不會重新拉取
2. **Browser cache**: 靜態資源（JS/CSS）被瀏覽器快取

### 解決方法

#### 方法 1: 使用時間戳標籤強制更新

```powershell
# 登入 ACR
az acr login --name cr{token}

# 建置並使用時間戳標籤
$ts = Get-Date -Format "yyyyMMddHHmmss"
docker build --no-cache -t cr{token}.azurecr.io/azure-gpt-rag/frontend:$ts .
docker push cr{token}.azurecr.io/azure-gpt-rag/frontend:$ts

# 更新 Container App 使用新標籤
az containerapp update --name ca-{token}-frontend `
  --resource-group {resource-group} `
  --image cr{token}.azurecr.io/azure-gpt-rag/frontend:$ts
```

#### 方法 2: 驗證新 revision 已啟用

```powershell
# 確認新 revision 狀態
az containerapp revision list --name ca-{token}-frontend `
  --resource-group {resource-group} -o table

# 預期輸出: 新 revision 應該 Active=True, TrafficWeight=100
```

#### 方法 3: 清除瀏覽器快取

- **Windows**: `Ctrl+Shift+R` 強制重新整理
- **Mac**: `Cmd+Shift+R`
- 或開啟 DevTools (F12) → Network → 勾選 "Disable cache"

### 驗證 Docker Image 內容

```powershell
# 檢查 image 內的檔案是否包含最新變更
docker run --rm cr{token}.azurecr.io/azure-gpt-rag/frontend:latest `
  cat /app/public/debug-panels.js | Select-String "特定關鍵字"
```

---

## UI 更新記錄

### 2026-01-16: Debug Panel 優化

**變更內容**:
1. 移除「User Message」區塊（冗餘資訊）
2. 移除「最終回應」區塊（與主畫面重複）
3. 加寬 Prompting 詳情面板 (320px → 450px)

**修改檔案**:
- `gpt-rag-ui/public/debug-panels.js`: 移除兩個 collapsible section
- `gpt-rag-ui/public/custom.css`: 修改 `.debug-panel.right-panel` 寬度

**部署指令**:
```powershell
az acr login --name cr{token}
cd "c:\SynologyDrive\LTIMindtree\Source Code\GPT-RAG-2.0\gpt-rag-ui"

$ts = Get-Date -Format "yyyyMMddHHmmss"
docker build --no-cache -t cr{token}.azurecr.io/azure-gpt-rag/frontend:$ts .
docker push cr{token}.azurecr.io/azure-gpt-rag/frontend:$ts

az containerapp update --name ca-{token}-frontend `
  --resource-group {resource-group} `
  --image cr{token}.azurecr.io/azure-gpt-rag/frontend:$ts
```

---

*最後更新: 2026-01-21*
