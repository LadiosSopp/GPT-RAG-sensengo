# Document Intelligence 成本異常分析報告

> **調查日期**: 2026-01-20  
> **問題描述**: Azure Document Intelligence 服務產生超過 $2,000 USD 的非預期費用

---

## 📋 執行摘要

經過深入調查，發現 Document Intelligence 高額費用的根本原因是 **CRON 排程設定錯誤** 和 **Container App 記憶體不足導致的重複執行**。原本預估處理 89 個檔案（約 5,455 頁）的成本應為 ~$55，但由於多重問題疊加，導致同一批文件被重複處理了 30-40 次以上。

---

## 🔍 問題根本原因

### 1. CRON 排程設定錯誤（主因）

| 設定項目 | 錯誤值 | 正確值 |
|---------|-------|-------|
| `CRON_RUN_BLOB_INDEX` | `*/5 * * * *` | `0 */6 * * *` |
| **執行頻率** | 每 5 分鐘 | 每 6 小時 |
| **每日執行次數** | 288 次 | 4 次 |

在 App Configuration 中存在兩個不同 label 的設定：
- `gpt-rag` label: `13 * * * *` (每小時)
- `gpt-rag-ingestion` label: `*/5 * * * *` (每 5 分鐘) ← **問題來源**

### 2. Container App 記憶體不足（OOM）

```
原始配置: 0.5 CPU, 1Gi RAM
錯誤訊息: Container 'dataingest' was terminated with exit code '137' (OOMKilled)
```

處理大型 PPTX 檔案（部分超過 100MB，base64 編碼後達 132MB+）時，1Gi 記憶體不足導致：
- Container 被 OOM Kill
- Kubernetes 自動重啟 Container
- 每次重啟觸發新的索引作業
- 形成無限循環

### 3. 啟動時立即執行邏輯

在 `main.py` 中的設計會在每次 Container 啟動時立即執行一次完整的 blob 索引：

```python
if s_blob_index:
    logging.info("[startup] Running blob-storage-indexer immediately")
    await run_blob_index()
```

當 Container 因 OOM 頻繁重啟時，這個設計加劇了重複執行的問題。

---

## 📊 影響分析

### API 呼叫統計 (2026/1/8 - 2026/1/18)

| 日期 | API 呼叫次數 |
|------|-------------|
| 1/8 | 851 |
| 1/11 | 662 |
| 1/12 | 1,583 |
| 1/13 | 2,703 |
| 1/14 | 1,479 |
| 1/15 | 1,152 |
| 1/17 | 813 |
| 1/18 | 7,809 |
| **總計** | **~17,215 次** |

### Job 執行記錄

- 總 Job 數量: **1,673 次**
- 1/19 單日執行: **532 次**
- Job 狀態異常: 大量 jobs 卡在 `status: running`，`indexedItems: 0`

### 成本計算

| 項目 | 數值 |
|------|------|
| Layout 模型定價 | $10 / 1,000 頁 |
| 單次處理估計頁數 | ~5,455 頁 |
| 單次處理成本 | ~$55 |
| 估計重複處理次數 | 30-40 次 |
| **預估總成本** | **$1,650 - $2,200** |

---

## ✅ 已執行的修復措施

### 1. 停用問題 CRON 排程

```powershell
# 備份原設定
az appconfig kv set --endpoint "https://appcs-d5teispadppru.azconfig.io" \
  --key "CRON_RUN_BLOB_INDEX_BACKUP" --value "13 * * * *" --auth-mode login

# 刪除問題設定
az appconfig kv delete --endpoint "https://appcs-d5teispadppru.azconfig.io" \
  --key "CRON_RUN_BLOB_INDEX" --label "gpt-rag-ingestion" --auth-mode login
```

### 2. 增加 Container 資源配置

```powershell
az containerapp update --name ca-d5teispadppru-dataingest \
  --resource-group rg-ethan-test --cpu 1.0 --memory 2Gi
```

| 配置項目 | 修改前 | 修改後 |
|---------|-------|-------|
| CPU | 0.5 | 1.0 |
| Memory | 1Gi | 2Gi |
| Ephemeral Storage | 2Gi | 4Gi |

### 3. 新增啟動控制環境變數

修改 `gpt-rag-ingestion/main.py`，加入 `RUN_JOBS_ON_STARTUP` 環境變數：

```python
run_on_startup = os.getenv("RUN_JOBS_ON_STARTUP", "true").lower() in ("true", "1", "yes")
if not run_on_startup:
    logging.info("[startup] RUN_JOBS_ON_STARTUP=false, skipping immediate job execution")
else:
    # 執行啟動時的 jobs...
```

設定環境變數：
```powershell
az appconfig kv set --endpoint "https://appcs-d5teispadppru.azconfig.io" \
  --key "RUN_JOBS_ON_STARTUP" --value "false" --auth-mode login
```

---

## 📋 修復後驗證結果

| 檢查項目 | 狀態 |
|---------|------|
| Container App Health | ✅ Healthy |
| Container Running State | ✅ RunningAtMaxScale |
| CRON 問題設定 | ✅ 已刪除 |
| RUN_JOBS_ON_STARTUP | ✅ 設為 false |
| 資源配置 | ✅ 1 CPU, 2Gi RAM |

---

## ⚠️ 後續建議事項

### 短期 (立即執行)

1. **部署 main.py 修改**
   - 目前修改只在本地，需要重新 build 並部署 Container App
   
2. **恢復 CRON 排程（使用合理頻率）**
   ```powershell
   az appconfig kv set --endpoint "https://appcs-d5teispadppru.azconfig.io" \
     --key "CRON_RUN_BLOB_INDEX" --label "gpt-rag-ingestion" \
     --value "0 */6 * * *" --auth-mode login
   ```
   建議改為每 6 小時執行一次

### 中期 (本週內)

3. **設定 Azure 預算警報**
   - 建議設定 $100 和 $500 兩個閾值
   - 需要具有 Cost Management 權限的管理員協助設定

4. **清理歷史 Job 記錄**
   ```powershell
   # 清理 jobs container 中的舊記錄
   az storage blob delete-batch --account-name std5teispadppru \
     --source jobs --pattern "blob-storage-indexer/runs/*" --auth-mode login
   ```

### 長期 (本月內)

5. **實作分散式鎖定機制**
   - 防止多個 indexer instance 同時執行
   - 可使用 Azure Blob Lease 或 Redis Lock

6. **加入處理進度 checkpoint**
   - 在處理大檔案時定期保存進度
   - OOM 重啟後可從 checkpoint 繼續

7. **優化大檔案處理**
   - 考慮使用 streaming 方式處理大型 PPTX
   - 或在處理前檢查檔案大小，過大的檔案分批處理

---

## 📁 相關檔案

| 檔案 | 說明 |
|-----|------|
| `gpt-rag-ingestion/main.py` | 主程式，包含 CRON 排程和啟動邏輯 |
| `gpt-rag-ingestion/jobs/blob_storage_indexer.py` | Blob 索引器，包含 skip 邏輯 |
| `gpt-rag-ingestion/tools/doc_intelligence.py` | Document Intelligence API 客戶端 |
| `gpt-rag-ingestion/check_cron_settings.py` | CRON 設定檢查工具 |

---

## 📞 相關資源

| 資源 | 識別碼/URL |
|-----|-----------|
| Resource Group | `rg-ethan-test` |
| Container App | `ca-d5teispadppru-dataingest` |
| App Configuration | `appcs-d5teispadppru.azconfig.io` |
| AI Foundry Account | `aif-d5teispadppru.cognitiveservices.azure.com` |
| Storage Account | `std5teispadppru` |

---

## 📝 教訓總結

1. **CRON 表達式要仔細確認** - `*/5 * * * *` 和 `0 */6 * * *` 差別巨大
2. **App Configuration 的 label 機制要注意** - 相同 key 不同 label 可能導致混淆
3. **Container 資源配置要考慮峰值需求** - 處理大檔案時記憶體需求可能超出預期
4. **設定成本警報是必要的** - 可以及早發現異常消費
5. **啟動時自動執行的設計要謹慎** - 應該要有開關控制

---

*報告產生時間: 2026-01-20*
