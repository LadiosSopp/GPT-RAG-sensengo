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

---

## Session: 2026-01-30 - TPM 配額調整與 Q&A 文件整理

### 📋 工作摘要

本次 session 解決了 **GPT-5.2 TPM 配額用盡**導致的 Internal Server Error，並將 Q&A 測試紀錄整理為標準 Markdown 格式。

---

### 🔧 1. TPM 配額問題修復

**問題描述：**
詢問「有櫻坂46相關的表演資訊嗎?」時，系統回傳：
```
event: error
data: An internal server error occurred.
```

**錯誤日誌：**
```
[Stream Debug] Event: thread.run.failed
[Stream] Run failed: Sorry, something went wrong.
Run completed - usage: {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
```

**根本原因：**
- GPT-5.2 Deployment 的 **TPM (Tokens Per Minute) 配額用完**
- 原設定：40K TPM（每分鐘 40,000 tokens）
- 當分鐘內使用量達到上限時，Azure AI Foundry 返回模糊的錯誤訊息

**解決方案：**
將 `chat` deployment 的 capacity 從 40 調高到 80：
```bash
az rest --method patch \
  --url "https://management.azure.com/subscriptions/{subscription-id}/resourceGroups/GPRAG/providers/Microsoft.CognitiveServices/accounts/aif-2v3lfktkn4xam-gprag/deployments/chat?api-version=2023-05-01" \
  --body '{"sku":{"name":"GlobalStandard","capacity":80}}'
```

**調整前後對比：**
| 設定 | 調整前 | 調整後 |
|------|--------|--------|
| Capacity | 40 | 80 |
| Token Rate Limit | 40,000/分鐘 | 80,000/分鐘 |
| Request Rate Limit | 400/分鐘 | 800/分鐘 |

**重要說明：**
- TPM 是**速率限制**，不是計費單位
- 調高 TPM 配額**不會增加費用**，費用仍按實際使用量計算
- 配額每分鐘重置一次

---

### 📝 2. Q&A 文件整理

將 [Q&A.md](../doc/Q&A.md) 文件套用標準 Markdown 格式：

- 使用 `##` 標示各題編號
- 使用 `**A1.**` 粗體標示答覆
- 使用 `-` 清單整理條列項目
- 使用 `>` 引用區塊標示資料來源
- 使用 `---` 分隔各題
- 使用 ``` 標示程式碼區塊

**Q&A 紀錄包含 11 題測試問答**，涵蓋：
- 市議員學歷查詢
- 老舊公寓會員數統計
- 佐登妮絲 AI 應用介紹
- 森JP塔資訊
- 收藏家等級分類
- 藝術品拍賣資訊
- 重劃區面積比較
- 親子公園列表
- 藏壽司 BT21 聯名活動
- TPM 配額問題記錄

---

*最後更新：2026-01-30*

---

## Session: 2026-02-05 - Chunk 長度分析

### 📋 工作摘要

本次 session 分析了 AI Search Index 中 **chunk 長度的分布**，並調查了 chunking 機制的設定。

---

### 📊 1. Chunk 長度統計

**查詢結果：**
| 指標 | 數值 |
|------|------|
| 總 Chunks 數 | 876 |
| 最大長度 | **31,772 字元** |
| 最小長度 | 93 字元 |
| 平均長度 | 1,464.85 字元 |

**Top 10 最長 Chunks：**
| 長度 | 標題 |
|------|------|
| 31,772 | 北北基桃 |
| 10,379 | 總表 |
| 10,263 | 總表 |
| 4,961 | 2025 Bk Pop Up Store Event |
| 4,883 | 標註 |
| 3,953 | Lic All Ip Combination |
| 3,393 | Lic All Ip Combination |
| 3,377 | Lic All Ip Combination |
| 3,274 | 工作表1 |
| 3,092 | Lic All Ip Combination |

---

### ⚙️ 2. Chunking 機制說明

**Chunker 選擇機制 (ChunkerFactory)：**

根據檔案副檔名自動選擇對應的 Chunker：

| 檔案類型 | Chunker |
|----------|---------|
| `.vtt` | TranscriptionChunker |
| `.json` | JSONChunker |
| `.xlsx`, `.xls` | SpreadsheetChunker |
| `.pdf`, `.png`, `.jpeg`, `.jpg`, `.bmp`, `.tiff` | DocAnalysisChunker / MultimodalChunker |
| `.docx`, `.pptx` | DocAnalysisChunker / MultimodalChunker |
| 其他 | LangChainChunker |

**預設 Chunking 參數：**

| 參數 | 環境變數 | 預設值 | 說明 |
|------|----------|--------|------|
| max_chunk_size | `CHUNKING_NUM_TOKENS` | 2048 tokens | 最大 chunk 大小 |
| token_overlap | `TOKEN_OVERLAP` | 100 tokens | 連續 chunk 間的重疊 |
| minimum_chunk_size | `CHUNKING_MIN_CHUNK_SIZE` | 100 tokens | 最小 chunk 大小 |

**SpreadsheetChunker 特殊設定：**

| 參數 | 環境變數 | 預設值 | 說明 |
|------|----------|--------|------|
| max_chunk_size | `SPREADSHEET_CHUNKING_NUM_TOKENS` | **0** (無限制) | Excel 最大 chunk 大小 |
| chunking_by_row | `SPREADSHEET_CHUNKING_BY_ROW` | false | 是否按列切分 |
| include_header | `SPREADSHEET_CHUNKING_BY_ROW_INCLUDE_HEADER` | false | 是否包含標題列 |

---

### 🔍 3. 分析結論

**為什麼會有 31,772 字元的超大 chunk？**

- **原因：** SpreadsheetChunker 的預設值 `SPREADSHEET_CHUNKING_NUM_TOKENS = 0`
- 當設為 0 時表示**不限制大小**
- 整個 Excel 工作表會被當作一個 chunk
- 「北北基桃」這個 Excel 檔案整頁匯入，產生 31,772 字元的 chunk

**App Configuration 現況：**
- 目前 App Configuration 中**沒有設定** chunking 相關參數
- 所有參數使用程式碼中的預設值

**建議調整（如需控制 chunk 大小）：**
```
SPREADSHEET_CHUNKING_NUM_TOKENS = 2048
CHUNKING_NUM_TOKENS = 2048
TOKEN_OVERLAP = 100
```

---

*最後更新：2026-02-05*

---

## Session: 2026-02-09~11 - 通話記錄查詢功能與 Knowledge Transfer 文件

### 📋 工作摘要

本次 session 實作了**通話記錄查詢功能 (Call Transcripts)**，透過 Function Calling 讓 Agent 能查詢 Cosmos DB 中的客戶通話資料。同時新增 Search Index 切換功能、修復 Dockerfile GPG 問題，並完成知識轉移文件。

---

### 📞 1. 通話記錄查詢功能 (Call Transcripts)

**功能概述：**
將會員卡推廣通話記錄 (xlsx, 1,100 筆) 匯入 Cosmos DB，透過 Azure AI Agent SDK 的 **FunctionTool** 機制，讓 LLM Agent 能查詢通話記錄。

**架構選擇：** 使用 FunctionTool（嵌入 Orchestrator），而非 MCP（獨立服務）

**新增檔案：**

| 檔案 | 說明 |
|------|------|
| `gpt-rag-orchestrator/src/connectors/call_transcripts.py` | Cosmos DB 查詢 Connector (`CallTranscriptClient`) |
| `scripts/import_call_transcripts.py` | 一次性 xlsx → Cosmos DB 匯入腳本 |
| `doc/call-transcripts-architecture.md` | 功能架構文件 (318 行) |

**`CallTranscriptClient.query_call_transcripts()` 參數：**

| 參數 | 類型 | 說明 |
|------|------|------|
| `customer_id` | str | 客代篩選 |
| `status` | str | 推銷狀態：「成功」/「失敗」|
| `call_date` | str | 日期篩選 (YYYY-MM-DD) |
| `keyword` | str | 逐字稿關鍵字搜尋 |
| `top` | int | 最大回傳筆數 (預設 10, 上限 50) |
| `include_full_transcript` | str | `"true"` 回傳完整逐字稿 |

**Cosmos DB 設定：**

| 設定 | 值 |
|------|------|
| 容器 | `call-transcripts` |
| Partition Key | `/customer_id` |
| 模式 | Serverless |
| 資料筆數 | 1,100 |
| 成功/失敗 | 676 / 424 |

**App Configuration 開關：**
```bash
# 啟用/停用（不需重新部署程式碼）
az appconfig kv set --endpoint https://appcs-2v3lfktkn4xam-gprag.azconfig.io \
  --key CALL_TRANSCRIPTS_ENABLED --value true --label gpt-rag --auth-mode login -y
```

---

### 🔧 2. Orchestrator 修改

**修改檔案：**

| 檔案 | 變更 |
|------|------|
| `gpt-rag-orchestrator/src/strategies/single_agent_rag_strategy_v1.py` | 引入 CallTranscriptClient、建立 FunctionTool、註冊 auto_functions |
| `gpt-rag-orchestrator/src/orchestration/orchestrator.py` | 新增 `search_index` 參數傳遞 |
| `gpt-rag-orchestrator/src/connectors/search.py` | 新增 `override_index()` 方法 |
| `gpt-rag-orchestrator/src/schemas.py` | 新增 `search_index` 欄位 |
| `gpt-rag-orchestrator/src/main.py` | 傳遞 `search_index` 到 Orchestrator |
| `gpt-rag-orchestrator/src/prompts/single_agent_rag/main.jinja2` | 新增 Tool Selection 決策表 |

**Prompt 模板重構 — Tool Selection 決策表：**

| 問題類型 | 使用工具 |
|---------|----------|
| 客戶通話記錄、推銷狀態分析 | `query_call_transcripts` |
| 文件、政策、知識文章 | `search_knowledge_base` |
| 混合問題 | 兩者皆用 |

---

### 🔍 3. Search Index 切換功能

**Frontend 新增 `/index` 指令：**
- `/index ragindex-second` — 切換到指定 Index
- `/index` — 查看目前 Index
- `/index reset` — 重設為預設 Index

**完整傳遞鏈：**
```
UI (/index 指令) → orchestrator_client.py (payload) → main.py → orchestrator.py → strategy.set_search_index() → search.py.override_index()
```

**修改檔案：**

| 檔案 | 變更 |
|------|------|
| `gpt-rag-ui/app.py` | 新增 `/index` 指令處理、傳遞 `search_index` 參數 |
| `gpt-rag-ui/orchestrator_client.py` | `call_orchestrator_stream` 新增 `search_index` 參數 |

---

### 🐳 4. Dockerfile GPG 修復

**問題：** Debian Trixie 的 `sqv` 自 2026-02-01 起拒絕 SHA1 簽名的 GPG key，導致 Microsoft Debian 12 repo 無法通過驗證。

**解決：**
```dockerfile
# 在 Orchestrator Dockerfile 中加入
RUN sed -i 's|^deb \[|deb [trusted=yes |' /etc/apt/sources.list.d/microsoft-prod.list
```

---

### ⏱️ 5. Debug Panel Timing 修正

移除 `response_streaming` stage，避免與 `llm_thinking_1 + tool_execution + llm_thinking_2` 重複計算。

---

### 📝 6. Knowledge Transfer 文件

新增並多次迭代 [knowledge-transfer.md](knowledge-transfer.md)：
- 完整專案架構與元件說明
- Function call chains
- Chunk size optimization 說明
- 準確性聲明、成本配額說明
- 移除附錄章節

---

### 🚀 7. 部署版本

| 元件 | Image Tag |
|------|-----------|
| Orchestrator | `orchestrator:20260209152559` |

---

### 📌 提交記錄

| Commit | 日期 | 說明 |
|--------|------|------|
| `808b640` | 2026-02-10 | feat: add call transcripts feature and knowledge transfer docs (16 files, +1327) |
| `42956f2` | 2026-02-10 | docs: update knowledge-transfer (+297/-225) |
| `918883b` | 2026-02-11 | docs: 新增準確性聲明、成本配額說明，移除附錄章節 (+30/-51) |

---

### ⚠️ 未追蹤檔案（尚未 commit）

- `doc/call-transcripts-architecture.md` — 通話記錄功能架構文件
- `doc/knowledge-transfer.html` — KT 文件 HTML 版
- `doc/knowledge-transfer_sensengo.pdf` / `_v1.pdf` — KT 文件 PDF exports
- `doc/responsetime_optimize.md` — 回應時間優化分析報告

---

## Phase 8: 回應時間優化與 Prompt 切換功能 (2026-02-24 ~ 2026-02-25)

### 📊 1. 回應時間瓶頸分析

以「林口恩典大樓A棟時程表」為主要測試對象，分析端到端回應時間：
- **冷啟動**：Container App scale-to-zero 導致首次請求額外等待 24-35s
- **Excel 超大 chunk**：`SPREADSHEET_CHUNKING_NUM_TOKENS=0`（無限制）導致單一 chunk ~8,000 tokens
- **LLM 處理時間**：占整體 ~63%（因搜尋結果 token 量大）

### 🔬 2. Chunking 策略比較

建立三個 AI Search Index 比較 Excel 的不同 chunking 策略：
- `ragindex` — by-sheet（現有，每 sheet 一個 chunk）
- `ragindex-byrow` — by-row（每行一個 chunk）
- `ragindex-hybrid` — by-sheet + by-row 混合

結論：三者速度差異不大（~15-16s），**hybrid 在回答品質上最佳**（從未回答錯誤）。

### 📁 3. 檔案類型比較

測試 PDF / DOCX / XLSX 共 20 題，結論：**檔案類型對回應時間影響不大**，瓶頸在 chunk 資訊密度和 LLM 搜尋次數。

### 📝 4. System Prompt 精簡化

新增 `/prompt` 前端指令，可切換 standard（~1000 tokens）與 lite（~400 tokens）兩種 prompt：
- 10 題 benchmark：**差異幾乎為零**（0.4s / 2%），各贏 5 題
- 結論：prompt 長度不是瓶頸，但 lite 可省 token 成本

### 🚀 5. 部署版本

| 元件 | Image Tag | 說明 |
|------|-----------|------|
| Orchestrator | `orchestrator:prompt-20260225091224` | 新增 prompt_mode 支援 |
| Frontend | `frontend:prompt-20260225091224` | 新增 /prompt 指令 |

部署方式：ACR Build + Azure Portal 手動更新（MFA Conditional Access 限制 CLI）。

### 📁 6. 新增/修改的檔案

| 檔案 | 變更 |
|------|------|
| `gpt-rag-orchestrator/src/schemas.py` | 新增 `prompt_mode` 欄位 |
| `gpt-rag-orchestrator/src/main.py` | 解析並傳遞 `prompt_mode` |
| `gpt-rag-orchestrator/src/orchestration/orchestrator.py` | 傳遞到 strategy |
| `gpt-rag-orchestrator/src/strategies/single_agent_rag_strategy_v1.py` | 依 prompt_mode 選擇模板 |
| `gpt-rag-orchestrator/src/prompts/single_agent_rag/main_lite.jinja2` | **新增** 精簡版 prompt |
| `gpt-rag-ui/app.py` | 新增 `/prompt` 指令 |
| `gpt-rag-ui/orchestrator_client.py` | 傳遞 `prompt_mode` 參數 |
| `scripts/ingest_byrow.py` | **新增** by-row ingest 腳本 |
| `scripts/ingest_hybrid.py` | **新增** hybrid ingest 腳本 |
| `scripts/benchmark_index.py` | **新增** index 策略 benchmark |
| `scripts/benchmark_filetypes.py` | **新增** 檔案類型 benchmark |
| `scripts/benchmark_prompt.py` | **新增** prompt mode benchmark |
| `scripts/deploy-prompt-feature.ps1` | **新增** 部署腳本 |
| `doc/responsetime_optimize.md` | **新增** 完整分析報告 |

### 📌 前端新指令

```
/prompt            ← 查看目前 prompt 模式
/prompt lite       ← 切換到精簡版
/prompt standard   ← 切回標準版
/index ragindex-hybrid  ← 切換到 hybrid index
/index reset       ← 切回預設 index
```

---

*最後更新：2026-02-25*

---

## Session: 2026-02-25~03-03 - 優化報告定版、KT 文件更新與提交

### 📋 工作摘要

本次 session 完成回應時間優化報告的定版、更新 Knowledge Transfer 文件、調查 Container App scale 設定，並將所有變更提交推送。

---

### 📄 1. 優化報告定版

建立 `doc/study/optimization_report_20260225.md`，經多次迭代最終以簡報導向架構定版：

| 章節 | 內容 |
|------|------|
| Current Performance Overview | 冷/暖啟動對照、效能基線 |
| Latency Breakdown Analysis | 各階段時間佔比、Excel chunk 根因、檔案類型/prompt 影響、XLSX chunking 策略比較 |
| Optimization Options | 三個優先級方案（含動態 LLM 切換） |
| Trade-offs Discussion | Latency vs Accuracy / Cost / Stability |
| 結論 | ~15s 是否可接受的決策 flowchart |

---

### 📝 2. Knowledge Transfer 文件更新

**新增 §4.2.1 擴展工具：MCP vs 本地 FunctionTool**
- MCP 方式：`@mcp.tool()` 定義、Semantic Kernel 自動發現、獨立 container 部署
- 本地 FunctionTool 方式（如 `call_transcripts`）：需自行實作並手動註冊
- 兩種策略使用不同 Agent 引擎（MCP = Semantic Kernel, RAG = Azure AI Foundry Agent）
- MCP 相關 App Configuration 參數

**更新 §5.1 問題 4: 回應延遲過長**
- 冷啟動分解（5 階段，35-50s）
- 暖機後瓶頸分佈（6 階段，~15-16s）
- 根因分析（Excel chunk 無限制）
- 5 個已驗證優化方案（含效果與風險）

---

### 🔍 3. Container App Scale-to-Zero 調查

| Container App | minReplicas | maxReplicas | cooldownPeriod | pollingInterval |
|---|---|---|---|---|
| Frontend | 0 | 3 | **300s (5 分鐘)** | 30s |
| Orchestrator | 0 | 1 | **300s (5 分鐘)** | 30s |
| DataIngest | 1 | 1 | — | — |

- Scaling rule：HTTP scaler，`concurrentRequests: 10`
- **閒置 5 分鐘後** Frontend 和 Orchestrator 會 scale down 到 0

---

### 📌 4. 提交記錄

```
193a61b feat: response time optimization, prompt mode, MCP docs, and benchmark scripts
```

**17 files changed**, +2,856/-21 lines, pushed to `master`

---

*最後更新：2026-03-03*

---

## Session: 2026-03-05~10 - KT 準備與技術深度整理

### 📋 工作摘要

本次 session 為客戶 KT（Knowledge Transfer）會議做準備，系統性地整理專案中所有需要向客戶說明的專有名詞與技術概念，並補充 KT 文件中遺漏的技術細節。

---

### 📚 1. 技術名詞深度解析

依客戶視角將 KT 文件中的專有名詞分類整理，並逐一深入追蹤原始碼確認：

**🔴 核心 AI 框架：**

| 名詞 | 說明 |
|------|------|
| Azure AI Foundry Agent Service | Agent 生命週期管理 (Thread/Run/Tool)，使用 `azure-ai-agents>=1.2.0b4` (beta) |
| Semantic Kernel (SK) | **僅用於 MCP 策略**作為 MCP 協議橋接，因 AI Foundry 原生不支援 MCP 協議 |
| MCP (Model Context Protocol) | Anthropic 開源協議，透過 SK `MCPSsePlugin` 連接 MCP Server |
| Agent Strategy 模式 | 6 種策略定義在 enum 中，但僅 3 種已實作：`single_agent_rag`/`single_agent_rag_v1`、`mcp`、`nl2sql` |

**關鍵架構決策釐清：**
- SK 存在的唯一原因：AI Foundry SDK 不支援 MCP 協議，需要 SK 作為 bridge
- `mcp` 策略完全繞過 AI Foundry Agent Service，使用 SK 自己的 `ChatCompletionAgent`
- `single_agent_rag` 和 `single_agent_rag_v1` 是同一策略的**別名**（向後相容）
- Foundry Tools（Build 2025 發表）理論上可取代 SK bridge，但目前 SDK 版本尚未支援

**🟠 資料處理：**

| 名詞 | 說明 |
|------|------|
| Document Intelligence | 文件解析服務，4.0 API 支援 DOCX/PPTX |
| Chunker 工廠模式 | `ChunkerFactory` 依副檔名選擇 7 種 Chunker |
| BaseChunker._create_chunk() | 所有 Chunker 的 embedding 統一在此生成 |
| `contentVector` vs `captionVector` | 前者＝文字內容向量（所有 chunk 都有）；後者＝圖片 caption 向量（僅 MultimodalChunker） |
| NL2SQL | 自然語言轉 SQL 查詢，目標資料庫為 Azure SQL / Fabric SQL（非 PostgreSQL） |

**🟡 架構元件：**

| 名詞 | 說明 |
|------|------|
| Dapr Sidecar | Container Apps 服務間通訊，處理 service discovery + token 認證 |
| FastAPI + Uvicorn | 後端 API 框架 + ASGI 伺服器 |
| Pydantic Model | FastAPI 自動 request 驗證（`OrchestratorRequest`） |
| Chainlit 2.6.0 | 前端 Chat UI 框架 |

**🟢 基礎設施：**

| 名詞 | 說明 |
|------|------|
| TPM (Tokens Per Minute) | 速率限制（含 input + output tokens），非計費單位 |
| VM Jumpbox | 網路隔離模式下的跳板機，用於存取私有網路資源 |
| `deployPostgres` | 預留擴展開關，目前 `false`；NL2SQL 實際用 SQL Server driver (ODBC 18) |

---

### 📝 2. KT 文件補充

在 [knowledge-transfer.md](knowledge-transfer.md) 中新增兩個段落：

**補充 1：Embedding 生成機制**（line ~411）
- 說明所有 Chunker 的 embedding 統一在 `BaseChunker._create_chunk()` 中生成
- 包含 `embedding_text` fallback 機制
- 說明 `MultimodalChunker` 的 `captionVector` 例外

**補充 2：Chunk + Vector 寫入 AI Search 的完整流程**（line ~432）
- 端到端流程圖：CRON → `BlobStorageDocumentIndexer.run()` → `_process_one()` → `DocumentChunker` → `_to_search_doc()` → `_replace_parent_docs()` → `upload_documents()`
- 說明 vector 生命週期：`_create_chunk()` 生成 → chunk dict 回傳 → `_to_search_doc()` 映射 → `upload_documents()` 寫入 AI Search
- 說明增量更新與原子替換機制

---

### 🔍 3. 技術調查結論

**PostgreSQL 在專案中的角色：**
- `main.parameters.json` 有 `deployPostgres=false` 參數
- 但 `main.bicep` 中**無任何 postgres 引用** — 模組尚未整合
- NL2SQL 的 `SQLDBClient`（`connectors/sqldbs.py`）使用的是 **ODBC Driver 18 for SQL Server**
- 結論：PostgreSQL 是 GPT-RAG accelerator 的**預留擴展**，目前 NL2SQL 走 Azure SQL / Fabric SQL

**`_to_search_doc()` 映射機制：**
- 本質是 merge 操作：Chunker 產出的內容欄位（content, contentVector, summary 等）+ Indexer 的 blob metadata（parent_id, security_ids, last_modified 等）
- 欄位名稱同名直傳，不需轉換

---

### 📁 修改的檔案

| 檔案 | 變更 |
|------|------|
| `doc/knowledge-transfer.md` | 新增「Embedding 生成機制」段落 + 「Chunk + Vector 寫入 AI Search 的完整流程」段落 |

---

### 📌 備註

- 本次 session 無程式碼修改或部署，純屬文件補充與技術分析
- KT 文件修改尚未 commit

---

*最後更新：2026-03-10*

---

## Session: 2026-02-26 - 東森多 Agent 架構分析與模型部署

### 📋 工作摘要

分析東森規劃的「AI 銷售中台」多 Agent 架構如何在 GPT-RAG 上實現，並嘗試部署 gpt-5.2-chat 模型。

---

### 🔍 1. 東森 AI 銷售中台 × GPT-RAG 可行性分析

東森規劃的銷售中台需要 Planner 分流 → 4 條路線：

| 路線 | 功能 | 觸發條件 |
|------|------|----------|
| A - 會員個人化推薦 | 四段式推薦話術 | 8 碼客代 + 推薦語意 |
| B - 通用資訊查詢 | RAG 文件檢索回答 | 文件/權益/業務相關查詢 |
| C - 拒絕處理模組 | 拒絕翻轉話術 | 8 碼客代 + 拒絕語意 |
| D - 一般 GPT 助理 | 通用對話 | 不屬於 A/B/C |

**識別 6 項困難：**
1. 缺乏動態任務分流（Planner）機制 — 策略在啟動時由 config 全域決定，非逐請求動態切換
2. 外部會員 API 整合不存在 — 需從零開發 Connector
3. `MULTIAGENT` 策略僅佔位未實作（`agent_strategy_factory.py` 中被註解）
4. 業務邏輯複雜度超越單純 RAG（四段式話術、拒絕翻轉、交通三鎖判定）
5. Prompt 管理不足以支撐多模組
6. 不同路線的對話脈絡與狀態模型不同

**比較三種方案：**

| 方案 | 做法 | 延遲 | 複雜度 |
|------|------|------|--------|
| A - 擴充策略模式 | 新增 PlannerStrategy + 子策略 | 低（2 次 LLM） | 中 |
| B - MCP Server | 四條路線包裝為 MCP tools | 中（SSE 往返） | 較低 |
| C - AgentGroupChat | 仿 NL2SQL 多 Agent 對話 | 高（4-6 次 LLM） | 高 |

**建議採用方案 A**（擴充策略模式），理由：分流條件明確不需協商、延遲可控、完全複用現有架構、`MULTIAGENT` 枚舉已預留。

---

### 🖥️ 2. 模型盤點

查詢 Azure AI Foundry 帳號 `aif-2v3lfktkn4xam-gprag` 中已部署的模型：

| 部署名稱 | 模型 | 版本 | SKU | TPM |
|----------|------|------|-----|-----|
| chat | gpt-5.2 | 2025-12-11 | GlobalStandard | 80 |
| text-embedding | text-embedding-3-large | 1 | Standard | 40 |

注意：chat 部署的 TPM 已從 IaC 設定的 40 手動上調至 80。

---

### ⚠️ 3. gpt-5.2-chat 部署（未完成）

- 已確認 eastus2 區域可用 `gpt-5.2-chat`（版本 2025-12-11 / 2026-02-10）
- 部署指令因 **MFA Conditional Access Policy** 被拒（`RequestDisallowedByAzure`）
- 多次嘗試 `az login`（含 `--use-device-code`、`--claims-challenge`）均未成功觸發 MFA step-up
- **待辦**：需透過 Azure Portal 手動部署，或在瀏覽器中清除 session 後重新 `az login` 完成 MFA

部署指令（待 MFA 通過後執行）：
```powershell
az cognitiveservices account deployment create `
  --name aif-2v3lfktkn4xam-gprag `
  --resource-group GPRAG `
  --deployment-name "chat-5.2" `
  --model-name "gpt-5.2-chat" `
  --model-version "2026-02-10" `
  --model-format OpenAI `
  --sku-name GlobalStandard `
  --sku-capacity 40
```

---

*最後更新：2026-03-10*
