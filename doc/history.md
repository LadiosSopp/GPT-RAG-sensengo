# GPT-RAG Sensengo 部署歷史記錄

## Session: 2026-01-22 - 客戶環境部署準備

### 📋 工作摘要

本次 session 主要目標是準備在 **sensengo (東森集團企業)** 客戶環境部署 GPT-RAG 專案。

---

### 🔍 1. Bicep 部署檔案審查

**審查檔案：**
- [infra/main.bicep](../GPT-RAG/infra/main.bicep) - 3092 行主要 IaC 模板
- [infra/main.parameters.json](../GPT-RAG/infra/main.parameters.json) - 部署參數設定

**主要部署選項：**
| 功能 | 參數 | 目前設定 |
|------|------|----------|
| AI Foundry | `deployAiFoundry` | true |
| Cosmos DB | `deployCosmosDb` | true |
| Container Apps | `deployContainerApps` | true |
| AI Search | `deploySearchService` | true |
| 網路隔離 | `networkIsolation` | false |
| 虛擬機器 | `deployVM` | false |
| Bing Grounding | `deployGroundingWithBing` | false |

**Container Apps 服務 (4個)：**
- orchestrator
- frontend  
- dataingest
- mcp

---

### 📝 2. 文件敏感資訊清理

**處理的檔案：** `/doc` 目錄下 13 個 markdown 檔案

**置換規則：**
| 原始資料 | 置換為 |
|---------|--------|
| `v-ktseng@microsoft.com` | `{deployer}@{domain}.com` |
| `rg-ethan-test` | `{resource-group}` |
| `d5teispadppru` | `{token}` |
| `ethan-test` | `{environment-name}` |
| Microsoft 內部訂閱資訊 | 通用佔位符 |

**統計：** 191+ 處敏感字串已匿名化

---

### 🔐 3. Azure 環境切換與權限驗證

**目標租戶：**
- 名稱：東森集團企業 / sensengo.com.tw
- Tenant ID：`45f5172d-7608-4bd1-a52a-c3a7de0423d3`

**目標訂閱：**
- 名稱：`ehs-ai-lab`
- Subscription ID：`2c9b3248-f263-4104-bd24-6446d4db84b9`

**執行命令：**
```powershell
az login --tenant 45f5172d-7608-4bd1-a52a-c3a7de0423d3
az account set --subscription "ehs-ai-lab"
```

**權限確認：**
- ✅ 使用者角色：**Owner** (訂閱層級)

---

### ⚙️ 4. Resource Provider 註冊

**發現問題：** 兩個必要的 resource provider 未註冊

| Provider | 用途 | 狀態 |
|----------|------|------|
| Microsoft.AppConfiguration | 集中化設定管理 | ✅ 已註冊 |
| Microsoft.DocumentDB | Cosmos DB (對話歷史) | ⏳ 註冊中 |

**執行命令：**
```powershell
az provider register -n Microsoft.DocumentDB
az provider register -n Microsoft.AppConfiguration
```

---

### 📌 待辦事項

- [ ] 確認 Microsoft.DocumentDB 註冊完成
- [ ] 選擇部署區域 (eastus / eastus2 / 其他)
- [ ] 驗證 Azure OpenAI 模型配額
- [ ] 建立或選擇 resource group
- [ ] 設定 azd 環境變數
- [ ] 執行 `azd provision` 和 `azd deploy`

---

### ⚠️ 重要提醒

1. **客戶環境注意事項：** 這是客戶的正式環境，任何變更前需確認
2. **Azure MCP 使用：** 後續 Azure 相關查詢使用 Azure MCP 工具
3. **舊文件備份：** 原始 history.md 已備份為 `history_old.md`

---

### 📁 相關檔案

- 舊部署記錄：[history_old.md](history_old.md)
- Bicep 主檔案：[main.bicep](../GPT-RAG/infra/main.bicep)
- 參數檔案：[main.parameters.json](../GPT-RAG/infra/main.parameters.json)
- AZD 設定：[azure.yaml](../GPT-RAG/azure.yaml)

---

## Session: 2026-01-23 - 客戶環境手動部署與疑難排解

### 📋 工作摘要

本次 session 完成了 **sensengo (東森集團企業)** 客戶環境的 Container Apps 手動部署，並解決了多個認證與設定問題。

---

### 🚀 1. 基礎建設佈建 (azd provision)

**執行結果：** ✅ 成功

**已建立資源：**
| 資源類型 | 名稱 | 狀態 |
|---------|------|------|
| Resource Group | GPRAG | ✅ |
| Container Registry | cr2v3lfktkn4xamgprag | ✅ |
| App Configuration | appcs-2v3lfktkn4xam-gprag | ✅ |
| Container Apps Environment | cae-2v3lfktkn4xam-GPRAG | ✅ |
| Storage Account | st2v3lfktkn4xamgprag | ✅ |
| Cosmos DB | cosmos-2v3lfktkn4xam-gprag | ✅ |
| AI Search | srch-2v3lfktkn4xam-gprag | ✅ |
| Key Vault | kv-2v3lfktkn4xam-gprag | ✅ |
| Application Insights | appi-2v3lfktkn4xam-gprag | ✅ |

---

### 🐳 2. Container Apps 手動建立

由於 `azd deploy` 失敗（AI Foundry 未部署），改為手動建立 Container Apps。

**手動建立的 Container Apps：**
| 名稱 | Image | Port | 狀態 |
|------|-------|------|------|
| ca-2v3lfktkn4xam-frontend-gprag | frontend:20260123104501 | 80 | ✅ Running |
| ca-2v3lfktkn4xam-orch-gprag | orchestrator:20260123112916 | 80 | ✅ Running |
| ca-ingest-gprag | dataingest:dac2e4a | 80 | ✅ Running |

**Container Apps URLs：**
- Frontend: https://ca-2v3lfktkn4xam-frontend-gprag.nicepond-9d5552be.eastus2.azurecontainerapps.io
- Orchestrator: https://ca-2v3lfktkn4xam-orch-gprag.nicepond-9d5552be.eastus2.azurecontainerapps.io
- DataIngest: https://ca-ingest-gprag.nicepond-9d5552be.eastus2.azurecontainerapps.io

---

### 🐛 3. 疑難排解

#### 問題 1: Frontend 顯示 Azure 預設頁面
**原因：** 舊的 helloworld revision 仍在接收流量  
**解決：** 停用舊 revision，設定 `min-replicas=1`

#### 問題 2: APP_CONFIG_ENDPOINT must be set
**原因：** Container App 未設定環境變數  
**解決：** 為三個 Container Apps 都設定 `APP_CONFIG_ENDPOINT=https://appcs-2v3lfktkn4xam-gprag.azconfig.io`

#### 問題 3: ManagedIdentityCredential 認證失敗
**錯誤訊息：** `App Service managed identity configuration not found in environment. invalid_scope`

**根本原因：** [gpt-rag-ui/connectors/appconfig.py](../gpt-rag-ui/connectors/appconfig.py#L33) 中的代碼問題：
```python
# 錯誤的代碼
self.client_id = os.environ.get('AZURE_CLIENT_ID', "*")  # 預設值 "*"
```
當 `AZURE_CLIENT_ID` 未設定時，預設值 `"*"` 傳給 `ManagedIdentityCredential(client_id="*")`，導致 SDK 嘗試查找不存在的 User Assigned Managed Identity。

**解決：** 修改代碼預設值為 `None`：
```python
self.client_id = os.environ.get('AZURE_CLIENT_ID') or None
```

#### 問題 4: httpx.ConnectError - Frontend 無法連接 Orchestrator
**原因：** App Configuration 缺少 `ORCHESTRATOR_URI` 設定  
**解決：** 
```powershell
az appconfig kv set --endpoint "https://appcs-2v3lfktkn4xam-gprag.azconfig.io" \
  --key "ORCHESTRATOR_URI" \
  --value "https://ca-2v3lfktkn4xam-orch-gprag.nicepond-9d5552be.eastus2.azurecontainerapps.io" \
  --label "gpt-rag" --auth-mode login -y
```

---

### 🔐 4. RBAC 權限設定

為三個 Container Apps 的 System Assigned Managed Identity 授予 App Configuration 存取權限：

| Container App | Principal ID | 角色 |
|--------------|--------------|------|
| Frontend | 9dc7b228-99b5-4d3f-9320-bba01cce1762 | App Configuration Data Reader |
| Orchestrator | ef79083f-72e4-4dec-b386-cd6b12ac10ac | App Configuration Data Reader |
| DataIngest | e1ca0054-6b41-43e7-ae82-b373cf86586c | App Configuration Data Reader |

---

### 📝 5. 代碼修改

**修改檔案：** [gpt-rag-ui/connectors/appconfig.py](../gpt-rag-ui/connectors/appconfig.py)

**變更內容：**
- 將 `AZURE_TENANT_ID` 和 `AZURE_CLIENT_ID` 的預設值從 `"*"` 改為 `None`
- 確保 System Assigned Managed Identity 能正確運作

---

### 📌 待辦事項

- [ ] 測試 Frontend 提問功能是否正常
- [ ] 設定 AI Foundry 相關設定 (如需要)
- [ ] 設定 DataIngest CRON 排程
- [ ] 上傳測試文件進行索引測試
- [ ] 將代碼修改提交到版本控制

---

### ⚠️ 重要提醒

1. **代碼修改需同步到上游：** `gpt-rag-ui/connectors/appconfig.py` 的修改需要提交
2. **Image 標籤記錄：** 
   - Frontend: `frontend:20260123104501`
   - Orchestrator: `orchestrator:20260123112916`
   - DataIngest: `dataingest:dac2e4a` (使用舊 image)
3. **DataIngest 可能需要重新 build：** 目前使用的是舊 image，如果有 Managed Identity 問題需重新 build

---

*最後更新：2026-01-23*
