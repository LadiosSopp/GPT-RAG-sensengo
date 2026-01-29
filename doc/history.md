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

## Session: 2026-01-25~26 - Indexing Bug 修復與成本分析

### 📋 工作摘要

本次 session 主要解決 **文件 indexing 缺失問題**，修復了 `_upload_in_batches` 未檢查上傳結果的 bug，並因成本過高而中斷 indexing 作業。

---

### 🐛 1. Bug 修復：upload_documents 結果檢查

**問題發現：** `捷運展演廳參訪.pptx` 顯示處理成功但未出現在 index 中

**根本原因：** [blob_storage_indexer.py](../gpt-rag-ingestion/jobs/blob_storage_indexer.py) 中的 `_upload_in_batches` 函數未檢查 Azure Search SDK 的 `upload_documents` 返回值

**修復內容：**
```python
# 修復前：只調用 upload_documents，不檢查結果
client.upload_documents(documents=batch)

# 修復後：檢查每個文件的上傳狀態
result: IndexDocumentsResult = client.upload_documents(documents=batch)
for r in result.results:
    if r.succeeded:
        succeeded += 1
    else:
        failed += 1
        logger.error(f"Failed to upload document {r.key}: {r.error_message}")
if failed > 0:
    raise RuntimeError(f"Failed to upload {failed} documents")
```

**部署：**
- Image: `dataingest:20260125155500`
- Container App: `ca-ingest-gprag`

---

### 📊 2. Indexing 狀態報告

**最終結果：**
| 項目 | 數量 |
|------|------|
| Blob 總數 (排除 _skip) | 79 |
| 已 Indexed | 78 |
| 未 Indexed | 1 |

**未 Indexed 檔案：**
- `/documents/商場相關/台中百貨商場營收統計.pptx`

**成功 Indexed (包含修復)：**
- `捷運展演廳參訪.pptx` ✅ 現已成功 indexed

---

### 💰 3. 成本分析 (2026/01/22-25)

**總花費：NT$3,830.90 (~$117 USD)**

| 服務 | 費用 (TWD) | 佔比 |
|------|----------:|-----:|
| Foundry Tools (Document Intelligence) | 1,946.67 | 50.8% |
| Azure Cognitive Search | 1,540.07 | 40.2% |
| App Configuration | 154.34 | 4.0% |
| Foundry Models (OpenAI) | 91.63 | 2.4% |
| Azure Cosmos DB | 82.19 | 2.1% |
| Container Registry | 15.80 | 0.4% |
| Storage | 0.20 | <0.1% |

**2026/01/25 詳細成本：**
| 細項 | 費用 (TWD) |
|------|----------:|
| Document Intelligence - S0 Pre-built Pages | 1,667.51 |
| Document Intelligence - S0 Add-on for Pages | 279.16 |
| GPT 5.2 output tokens | 67.64 |
| AI Search Basic Unit | 84.42 |
| App Configuration Standard | 38.59 |

**結論：**
- 主要花費來自 **Document Intelligence (89.6%)**
- 其他服務為正常固定費用
- 每日固定成本約 **NT$140/天** (不含 ingestion)

---

### ⏹️ 4. 成本節約措施

**已執行：**
| 項目 | 操作 | 狀態 |
|------|------|------|
| Container App | `az containerapp revision deactivate` | ✅ 已停用 |
| CRON 排程 | 刪除 `CRON_RUN_BLOB_INDEX` | ✅ 已刪除 |
| AI Search | 維持 Basic tier | ✅ 保留 |

**資源狀態確認：**
```
AI Search: Basic tier, 1 replica, 1 partition
Container App: Revision deactivated, 0 replicas running
```

---

### 📝 5. 提交記錄

```
fix: check upload_documents result in _upload_in_batches for proper error handling

- Added result validation for Azure Search SDK upload_documents return values
- Log individual document failures with error messages
- Raise RuntimeError if any documents fail to upload
- Cleaned up temporary files and scripts
```

**45 files changed**, pushed to `master` branch

---

### 📌 待辦事項

- [ ] 手動處理剩餘 1 個未 indexed 檔案：`台中百貨商場營收統計.pptx`
- [ ] 監控後續固定成本是否如預期 (~NT$140/天)
- [ ] 考慮 App Configuration 是否可降為 Free tier

---

### ⚠️ 重要提醒

1. **DI 按量計費：** Document Intelligence 是按使用量計費，Container App 停止後不會再產生費用
2. **AI Search 固定費用：** Basic tier 每天約 NT$84-350，視使用時段而定
3. **下次 indexing：** 需手動啟動 Container App revision

---

*最後更新：2026-01-29*

---

## Session: 2026-01-29 - Debug Panel UI 優化與佈局改進

### 📋 工作摘要

本次 session 優化了 Debug Panel 的 UI 體驗，改為**左右分割佈局**，讓 Debug 資訊不再遮擋問答區。

---

### 🎨 1. UI 佈局改進

**原本問題：**
- Debug Panel 以浮動面板形式顯示在右側
- 展開時會遮擋問答區域的內容

**解決方案：** 改為左右分割佈局
- **Debug ON**: 頁面左側 55% 為問答區，右側 45% 為 Debug Panel
- **Debug OFF**: 問答區恢復全寬置中

**技術實作：**
```javascript
// 調整主要內容區寬度
function adjustMainContent(enable) {
    const root = document.getElementById('root');
    if (enable) {
        root.style.width = '55%';
        root.style.marginRight = '45%';
    } else {
        root.style.width = '';
        root.style.marginRight = '';
    }
}
```

---

### 🔧 2. 功能調整

**移除的功能：**
- ❌ 移除 on_chat_start 的 debug 模式提示訊息
- ❌ 移除 Python 端的 `display_debug_panel` 函數（改由 JavaScript 處理）

**保留的功能：**
- ✅ `/debug` 或 `/debug on` - 啟用 Debug 模式
- ✅ `/debug off` - 關閉 Debug 模式
- ✅ `/debug status` - 查看目前狀態

**預設行為改變：**
- Debug 模式預設為 **啟用** (True)
- 使用者進入聊天即可看到 Debug Panel

---

### 🚀 3. 部署版本

| 版本 | Image Tag | 說明 |
|------|-----------|------|
| v25 | ui:v25-clean | 移除重複的 Python debug 訊息 |
| v26 | ui:v26-debug-default | 移除提示訊息，預設 debug ON |
| v27 | ui:v27-split-layout | 左右分割佈局 |

**目前部署版本：** `ui:v27-split-layout`

---

### 📁 修改的檔案

| 檔案 | 變更 |
|------|------|
| `gpt-rag-ui/app.py` | 移除 `display_debug_panel` 函數、移除提示訊息、預設 debug=True |
| `gpt-rag-ui/public/debug-panels.js` | 新增 `adjustMainContent()` 函數、改為側邊欄佈局、新增關閉按鈕 |

---

### 📌 使用方式

1. 進入聊天頁面，Debug Panel 預設顯示在右側
2. 發送問題後，可在右側看到：
   - **Timing** - 各階段執行時間
   - **Prompting Details** - 完整的 prompting 資訊
3. 點擊「關閉 ✕」或輸入 `/debug off` 可關閉 Debug Panel

---

*最後更新：2026-01-29*

---

## Session: 2026-01-27 - Debug 面板功能強化

### 📋 工作摘要

本次 session 實作了 **Debug 面板**功能強化，包含完整的 Timing 追蹤和 Prompting Details 顯示。

---

### ⏱️ 1. Timing 面板強化

**新增功能：**
- 顯示所有 Orchestrator 內部階段的執行時間
- 新增 Orchestrator Total 和 End-to-End Total
- 顯示 Components Sum vs Overhead（網路延遲分析）

**Timing 階段：**
| 圖示 | 階段 | 說明 |
|------|------|------|
| 🧵 | Thread Management | Thread 建立/取得 |
| 🤖 | Agent Management | Agent 建立/取得 |
| 📨 | Send Message | 發送訊息到 Agent |
| 🤔 | LLM Thinking #1 | 第一次 LLM 推理 |
| 🔧 | Tool Execution | 工具執行（RAG 搜尋） |
| 💭 | LLM Thinking #2 | 第二次 LLM 推理 |
| 📤 | Agent Response | Agent 回應處理 |
| 📚 | Consolidate History | 整合對話歷史 |
| 🧹 | Cleanup Agent | 清理 Agent |
| ⏱️ | Orchestrator Total | Orchestrator 內部總時間 |
| 🏁 | End-to-End Total | 完整請求時間（含網路） |

**修改檔案：**
- [gpt-rag-ui/public/debug-panels.js](../gpt-rag-ui/public/debug-panels.js) - 前端 timing 顯示邏輯

---

### 📝 2. Prompting Details 面板強化

**新增功能：**
- 📝 **User Message** - 完整用戶訊息
- ⚙️ **System Prompt** - 系統提示（可滾動）
- 🔧 **Tool Calls** - 工具調用詳情
- 🔍 **Search Results** - 完整搜索結果，包含：
  - 文檔標題
  - 連結
  - 內容預覽
  - 相關性分數
- 🤖 **LLM Calls** - LLM 調用詳情（model、tokens、duration）

**修改檔案：**
- [gpt-rag-ui/app.py](../gpt-rag-ui/app.py) - 後端 prompting_data 提取
- [gpt-rag-ui/public/debug-panels.js](../gpt-rag-ui/public/debug-panels.js) - 前端顯示邏輯

---

### 🔧 3. 技術修復

**問題 1: JSON 控制字元解析錯誤**
- **錯誤：** `Failed to parse debug event JSON: Invalid control character`
- **解決：** 在 `debug_store.py` 中清理控制字元（\n, \r, \t）

**問題 2: Timing Key 名稱不匹配**
- **問題：** 後端使用 `thread_management`，前端預期 `thread_creation`
- **解決：** 在 JS 中添加 key 映射 fallback

**問題 3: Prompting 面板高度不足**
- **問題：** `max-height: 400px` 無法顯示完整內容
- **解決：** 增加到 `max-height: 70vh`

---

### 🚀 4. 部署版本

| 版本 | Image Tag | 說明 |
|------|-----------|------|
| v15 | ui:v15-json-fix | JSON 控制字元修復 |
| v16 | ui:v16-timing-map | Timing key 映射修復 |
| v17 | ui:v17-full-search | 完整搜索結果顯示 |
| v18 | ui:v18-timing | 完整 timing 階段顯示 |

**目前部署版本：** `ui:v18-timing`

---

### 📁 修改的檔案

| 檔案 | 變更 |
|------|------|
| `gpt-rag-ui/app.py` | 提取 prompting_data（system_prompt, search_results, tool_calls, llm_calls） |
| `gpt-rag-ui/debug_store.py` | JSON 控制字元清理 |
| `gpt-rag-ui/public/debug-panels.js` | 完整 timing 階段、搜索結果顯示、面板高度調整 |

---

### 📌 使用方式

1. 在 UI 輸入 `/debug` 啟用 Debug 模式
2. 發送問題
3. 右側面板顯示：
   - **Timing** - 各階段執行時間
   - **Prompting Details** - 完整的 prompting 資訊

---

*最後更新：2026-01-27*
