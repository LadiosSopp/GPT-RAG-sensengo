# 東森通話錄音 STT 逐字稿生成報告

> 日期：2026-03-24  
> 專案：sensengo (東森)  
> 資源群組：GPRAG (ehs-ai-lab, eastus2)

---

## 1. STT 方案評估

### 1.1 兩種可用路徑

| 路徑 | 說明 | 部署方式 | 適合場景 |
|------|------|----------|----------|
| **Azure AI Speech Service** | 微軟託管服務，直接呼叫 API | API (Fast Transcription REST) | 生產批次轉錄、穩定度高 |
| **Foundry Model Catalog (Whisper)** | 開源模型部署到 GPU VM | Managed Compute | 需自訂模型/高精準度 |

### 1.2 Foundry Model Catalog — Whisper 系列（通用多語言）

| 模型 | 參數量 | 中文支援 | 速度 | 精準度 | 授權 |
|------|--------|----------|------|--------|------|
| `openai-whisper-large-v3` | 1.55B | 多語言（含中文） | 慢 | **最高** | MIT |
| `openai-whisper-large-v3-turbo` | ~809M | 多語言（含中文） | **快（~3x）** | 接近 large-v3 | MIT |
| `openai-whisper-large-v2` | 1.55B | 多語言（含中文） | 慢 | 高 | MIT |
| `openai-whisper-medium` | 769M | 多語言（含中文） | 中 | 中 | MIT |
| `openai-whisper-small` | 244M | 多語言（含中文） | 快 | 低 | MIT |
| `openai-whisper-tiny` | 39M | 多語言（含中文） | 最快 | 最低 | MIT |

### 1.3 Foundry Model Catalog — 中文特化模型

| 模型 | 基底 | 語言 | 特色 |
|------|------|------|------|
| `jacoblincool-whisper-large-v3-turbo-common-voice-19-0-zh-tw` | large-v3-turbo | **zh-TW 繁中** | Common Voice 19.0 zh-TW 微調，最適合台灣繁中 |
| `belle-2-belle-whisper-large-v2-zh` | large-v2 | zh 中文 | BELLE 開源中文微調版 |
| `belle-2-belle-distilwhisper-large-v2-zh` | distil large-v2 | zh 中文 | 蒸餾版，更快但精準度略降 |

> 以上 Foundry 模型均為 **Managed Compute (GPU VM)** 部署，需自行管理 VM。

### 1.4 方案比較

| 面向 | Azure AI Speech Service | Whisper (Foundry) | zh-TW 微調 (Foundry) |
|------|------------------------|-------------------|----------------------|
| 中文精準度 | 高（微軟引擎） | 高 | **最高（zh-TW 微調）** |
| 部署複雜度 | **低（API 即用）** | 高（需 GPU VM） | 高（需 GPU VM） |
| 成本 | 按音訊時數（~NT$32/hr） | 按 VM 時數 | 按 VM 時數 |
| 批次處理 | **內建 Batch API** | 需自行實作 | 需自行實作 |
| Speaker Diarization | **內建支援** | 不支援 | 不支援 |
| 自訂詞彙 (phrases) | **支援** | 不支援 | 不支援 |

### 1.5 選擇結果

採用 **Azure AI Speech Service — Fast Transcription REST API**：
- 直接使用既有的 AI Services endpoint (`aif-2v3lfktkn4xam-gprag.cognitiveservices.azure.com`)
- 語言設定 `zh-TW`，支援 WAV 格式
- 認證方式：`AzureCliCredential` (AAD Token + Bearer)
- API endpoint：`/speechtotext/transcriptions:transcribe?api-version=2024-11-15`

---

## 2. 批次轉檔執行

### 2.1 輸入資料

- 來源目錄：`SampleData/audio.sanitized/`
- 檔案格式：WAV（已分聲道）
- 命名規則：`{call_id}.agent.wav` / `{call_id}.customer.wav`
- 總數：**74 個 WAV 檔**（37 通對話 × agent/customer）
- 總大小：**0.65 GB**
- 音訊總時長：**13.60 小時**（815.8 分鐘）

### 2.2 執行結果

| 項目 | 結果 |
|------|------|
| 成功 | 74/74 (100%) |
| 失敗 | 0 |
| 輸出目錄 | `SampleData/transcripts/` |
| 輸出格式 | JSON（完整 API 回傳）+ TXT（可讀格式含時間戳） |
| 檔名格式 | `{call_id}.agent.json/.txt`, `{call_id}.customer.json/.txt` |
| 總輸出 | 148 個檔案（74 JSON + 74 TXT） |

### 2.3 轉錄品質觀察

- 正確辨識多數對話內容與專有名詞（東森、林口、A9 捷運站、精華酒店、蕭敬騰、中國信託、華南等）
- 部分辨識可改善處：
  - 「恩典大樓」名稱辨識偶有偏差
  - 「尊龍卡」有時轉為其他字
  - 可透過 phrases hint 加入東森專屬詞彙提升精準度

### 2.4 腳本

- 批次轉檔：[`scripts/batch_stt.py`](../scripts/batch_stt.py)
  - 支援斷點續跑（已完成的自動跳過）
  - 每 50 檔自動刷新 token
- 單檔測試：[`scripts/test_stt.py`](../scripts/test_stt.py)

---

## 3. 逐字稿合併（Merge）

將同一通電話的 agent 和 customer 逐字稿依時間戳合併為完整對話。

### 3.1 執行結果

| 項目 | 結果 |
|------|------|
| 合併數量 | 37 通對話 |
| 輸出目錄 | `SampleData/transcripts_merged/` |
| 輸出格式 | JSON + TXT |
| 檔名格式 | `{call_id}.json`, `{call_id}.txt` |
| 總輸出 | 74 個檔案（37 JSON + 37 TXT） |

### 3.2 合併格式範例

```
[0.1s - 4.5s] 客戶：欸，請問哪裡？
[1.7s - 12.0s] 客服：什麼是永仁大哥嗎？大哥，你好，我自己是那個東森全球總部這邊啊...
[48.0s - 49.0s] 客戶：我不知道，嘿。
[49.4s - 69.2s] 客服：好，那大哥，這一個的話是我們總裁投資原本是想說就100億就好了...
[74.0s - 83.9s] 客戶：我跟你講齁，現在這個不用啦哦...好謝謝你吼好拜拜。
```

### 3.3 腳本

- 合併腳本：[`scripts/merge_transcripts.py`](../scripts/merge_transcripts.py)

---

## 4. 成本分析

### 4.1 STT 費用

| 項目 | TWD | ~USD |
|------|-----|------|
| **Speech Fast Transcription (3/23)** | **NT$320.59** | **~US$9.86** |

- 計費服務：`Foundry Tools / Azure Speech / Fast Transcription Speech To Text`
- 音訊時長：13.60 小時（74 個 WAV）
- 等效單價：約 NT$23.6/小時 (~US$0.73/hr)

### 4.2 3/23 STT 執行日 vs 前一天

| 日期 | 日成本 (TWD) | ~USD | 變化 |
|------|-------------|------|------|
| 3/22 (無 STT) | NT$1,131.7 | ~US$34.82 | — |
| 3/23 (跑 STT) | NT$1,404.8 | ~US$43.22 | **+NT$273.1 (+24.1%)** |

增加的 NT$273.1 中，Speech STT 佔 NT$320.6，其他項目則略有減少。

### 4.3 GPRAG 7日成本結構 (3/17~3/24)

| 服務 | TWD | ~USD | 佔比 |
|------|-----|------|------|
| Foundry Tools (Doc Intelligence + Speech) | NT$4,608.0 | ~US$141.78 | 55.8% |
| Foundry Models (OpenAI GPT) | NT$1,116.3 | ~US$34.35 | 13.5% |
| Azure Cognitive Search | NT$1,104.0 | ~US$33.97 | 13.4% |
| Azure Container Apps | NT$829.0 | ~US$25.51 | 10.0% |
| App Configuration | NT$308.7 | ~US$9.50 | 3.7% |
| Azure Cosmos DB | NT$195.8 | ~US$6.02 | 2.4% |
| Container Registry | NT$57.7 | ~US$1.77 | 0.7% |
| SQL Database | NT$36.4 | ~US$1.12 | 0.4% |
| Storage | NT$2.2 | ~US$0.07 | 0.0% |
| **合計** | **NT$8,258.1** | **~US$254.09** | |

> 幣別確認：Cost Management API 回傳的是 **TWD（新台幣）**，Portal 顯示的 $577.72 為 USD（整月累積）。

### 4.4 成本查詢腳本

- [`scripts/query_stt_cost.py`](../scripts/query_stt_cost.py) — 透過 REST API 查詢
- [`scripts/analyze_cost_twd.py`](../scripts/analyze_cost_twd.py) — TWD 成本分析
- [`scripts/calc_stt_cost.py`](../scripts/calc_stt_cost.py) — 音訊時長計算

---

## 5. 檔案結構總覽

```
SampleData/
├── audio.sanitized/          # 原始 WAV（agent + customer 分聲道）
│   ├── 010a03a3caa92949.agent.wav
│   ├── 010a03a3caa92949.customer.wav
│   └── ... (74 files)
├── transcripts/              # 單聲道逐字稿 (JSON + TXT)
│   ├── 010a03a3caa92949.agent.json
│   ├── 010a03a3caa92949.agent.txt
│   ├── 010a03a3caa92949.customer.json
│   ├── 010a03a3caa92949.customer.txt
│   └── ... (148 files)
└── transcripts_merged/       # 合併對話 (JSON + TXT)
    ├── 010a03a3caa92949.json
    ├── 010a03a3caa92949.txt
    └── ... (74 files)
```

---

## 6. 後續建議

1. **phrases hint**：在 batch_stt.py 的 definition 加入東森專屬詞彙（尊龍卡、ETMall、精華酒店等）提升辨識精準度
2. **Speaker Diarization**：若改用 Batch Transcription API 可啟用說話者辨識，自動區分多人對話
3. **大規模作業**：客戶若有上千筆錄音，可改用 Azure Batch Transcription（非同步 API），支援 Blob Storage 直接讀取，避免逐檔上傳
4. **成本控制**：STT 為一次性費用（NT$320.59 / 74 檔），持續成本主要來自 Document Intelligence（NT$617/天）和 AI Search（NT$156/天）
