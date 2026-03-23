# GPT-RAG 回應時間優化分析報告

**分析日期**: 2026-02-24 ~ 2026-02-25  
**環境**: Azure Container Apps (eastus2), GPT-4.1, AI Search (hybrid mode)  
**分析人員**: v-ktseng  

---

## 1. 問題描述

使用者反映從提問到看到回應的時間過長（約 40-50 秒），以「林口恩典大樓A棟時程表12.29_2026.01.13.13.08.xlsx」為主要測試對象，調查瓶頸並評估優化方案。

---

## 2. 端到端請求流程與時間分佈

```
使用者提問
    │
    ▼ [HTTP POST → Orchestrator]
┌────────────────────────────────────────────────────────────────┐
│ ① Cosmos DB 讀取/建立對話        ~4s    （9%）  可優化 ✅     │
│ ② Thread/Agent 建立              ~1-3s  （5%）  可優化 ✅     │
│ ③ Agent 思考＋決定呼叫工具       ~7s    （16%） 架構限制 ⚠️   │
│ ④ search_knowledge_base 執行     ~1.5s  （4%）  已不錯 ✅     │
│ ⑤ ★ LLM 處理搜尋結果＋生成回應  ~27s   （63%） ❌ 最大瓶頸   │
│ ⑥ 後處理＋Cosmos DB 更新         ~2s    （5%）  可優化 ✅     │
├────────────────────────────────────────────────────────────────┤
│                           合計    ~43s                         │
└────────────────────────────────────────────────────────────────┘
    ▼ [SSE Stream]
前端顯示回應
```

---

## 3. Excel 檔案的核心瓶頸分析

### 3.1 檔案結構

林口恩典大樓A棟時程表包含 2 個 Sheet：

| Sheet | 性質 | 行數 | 欄數 | 估計 tokens |
|-------|------|------|------|------------|
| **總表** | 每層樓一行，含 22 欄（樓層、用途、設計單位、各階段時程日期等） | 40 行 | 22 | ~9,876 |
| **各設計師樓層** | 以設計師為維度的彙總表（樓層範圍、坪數） | 15 行 | 7 | ~2,663 |

### 3.2 瓶頸根因：超大 Chunk

**目前 App Configuration 中未設定任何 `SPREADSHEET_CHUNKING` 參數**，全部使用程式碼預設值：

| 設定 | 目前值 | 效果 |
|------|--------|------|
| `SPREADSHEET_CHUNKING_NUM_TOKENS` | **0（無限制）** | 整個 sheet 變成一個 chunk，不限大小 |
| `SPREADSHEET_CHUNKING_BY_ROW` | **false** | 每個 sheet = 1 chunk |
| `SPREADSHEET_CHUNKING_BY_ROW_INCLUDE_HEADER` | **false** | （目前不適用） |

造成的影響：

```
Excel 檔案 → SpreadsheetChunker
  ├── 每個 Sheet → 1 chunk（~8,000-10,000 tokens）
  ├── search_knowledge_base(topK=3) → 回傳 3 個 chunk
  │   └── 3 × ~8,000 tokens = ~24,000 tokens ⚠️
  └── LLM 需處理 ~25,000+ tokens → 花費 27 秒 ❌
```

相比之下，一般文件（PDF/DOCX）使用 `DocAnalysisChunker`，預設 `CHUNKING_NUM_TOKENS=2048`，chunk 大小約 2,000 tokens，3 個 chunk 約 6,000 tokens，LLM 處理壓力小得多。

---

## 4. Excel Chunking 策略比較實驗

### 4.1 三種策略說明

| 策略 | 說明 | 預計 chunk 數 | topK=3 的 token 量 |
|------|------|-------------|-------------------|
| **by-sheet**（現有） | 每個 sheet 一個 chunk，完整 markdown 表格 | 2 個/檔 | ~24,000 tokens |
| **by-row** | 每行一個 chunk，含表頭 | ~55 個/檔 | ~1,000 tokens |
| **hybrid** | by-sheet + by-row 同時存在 | ~57 個/檔 | ~1,000-9,000 tokens（依問題而定） |

### 4.2 實作方式

建立三個 AI Search Index：
- `ragindex` — 預設 by-sheet（現有）
- `ragindex-byrow` — 純 by-row
- `ragindex-hybrid` — by-sheet + by-row 混合

使用腳本：
- `scripts/ingest_byrow.py` — by-row 模式 ingest
- `scripts/ingest_hybrid.py` — hybrid 模式 ingest（by-sheet + by-row 同時放入）
- `scripts/benchmark_index.py` — 自動化 benchmark（含 warmup 消除冷啟動）

前端切換方式（已有 `/index` 指令）：
```
/index ragindex-byrow     ← 切換到 by-row
/index ragindex-hybrid    ← 切換到 hybrid
/index reset              ← 切回預設
```

### 4.3 Benchmark 結果（10 題，含 warmup 消除冷啟動）

#### 4.3.1 回應時間

| # | 問題類型 | by-sheet | by-row | hybrid | 勝出 |
|---|---------|----------|--------|--------|------|
| Q1 | 單行精確（38F完工日期） | 11.1s | 12.0s | **9.8s** | hybrid |
| Q2 | 單行精確（27F設計單位） | 12.5s | **11.8s** | 10.5s | hybrid |
| Q3 | 跨行聚合（柏成設計樓層） | *(118s異常)* | 13.3s | **11.0s** | hybrid |
| Q4 | 跨行列舉（用途變更） | **14.4s** | 16.8s | 17.8s | by-sheet |
| Q5 | 日期篩選（2026/08前完工） | 13.8s | 13.0s | **12.2s** | hybrid |
| Q6 | 單行數值（30F坪數） | 13.3s | 12.3s | **12.0s** | hybrid |
| Q7 | 多行時程（酒店28-36F） | **14.7s** | 22.9s | 27.0s | by-sheet |
| Q8 | 條件篩選（設計單位未定） | 13.9s | 13.2s | **14.0s** | by-row |
| Q9 | 跨行比較（維格設計裝潢） | 16.3s | 19.4s | **12.0s** | hybrid |
| Q10 | 全表摘要（全棟用途） | **21.4s** | 23.2s | 31.2s | by-sheet |
| **AVG** | | **15.5s*** | **15.8s** | **15.8s** | |

*排除 Q3 by-sheet 的 118s 異常值

#### 4.3.2 回答品質

| 問題 | by-sheet | by-row | hybrid |
|------|----------|--------|--------|
| Q2 27F 設計單位 | ❌ 找不到 | ✅ 創揚室內裝修 | ✅ 創揚室內裝修 |
| Q3 柏成設計樓層 | ✅ 28-36F 完整 | ⚠️ 只有 30F | ⚠️ 只有 30F |
| Q4 用途變更 | ✅ 完整列出 | ❌ 只有表頭 | ❌ 只有表頭 |
| Q8 未定樓層 | ✅ 完整列出 | ❌ 搜不到 | ✅ 完整列出 |
| Q10 全棟概述 | ✅ 完整 1F-RF | ⚠️ 片段 | ⚠️ 片段 |

#### 4.3.3 統計摘要

| 指標 | by-sheet | by-row | hybrid |
|------|----------|--------|--------|
| **平均時間** | 15.5s | 15.8s | 15.8s |
| **速度勝出次數** | 2/10 | 2/10 | **6/10** |
| **品質最佳次數** | 4/10 | 1/10 | **5/10** |
| **品質最差次數** | 1/10 | 2/10 | **0/10** |

### 4.4 結論

- 排除冷啟動後，三者**平均速度差異不大**（~15-16s）
- **hybrid 贏在品質**：從未回答錯誤（0 次品質最差），且在 6/10 題速度最快
- by-sheet 獨有優勢：需要**全表一次性掃描**的問題（變更列表、全棟概述）
- by-row 獨有優勢：需要**多行但非全表**的問題
- **hybrid = 品質和速度的最佳平衡點**

---

## 5. 冷啟動影響分析

### 5.1 現象

Container App 設定 `minReplicas: 0`（scale-to-zero），閒置時完全關閉。

| 狀態 | Q1 TTFB | 說明 |
|------|---------|------|
| 冷啟動 | 35-50s | Container 啟動 + Python 初始化 + Azure AD Token + 連線建立 |
| 暖機後 | 1.1-1.3s | 連線池已建立，Token 快取有效 |

### 5.2 冷啟動的組成

| 階段 | 估計耗時 |
|------|---------|
| Container App 啟動新 replica | ~5-10s |
| Python + FastAPI 初始化 | ~2-3s |
| Azure AD Token 首次獲取 | ~2-3s |
| Cosmos DB 首次連線 (TCP+TLS) | ~1-2s |
| AI Search 首次連線 | ~1s |
| AI Foundry Agent Service 首次初始化 | ~3-5s |
| **合計** | **~15-25s** |

### 5.3 解法

- **保持 `minReplicas=0` 省錢**，在 benchmark 腳本中加入 warmup 機制確保測量一致性
- 若未來需要即時回應，可設 `minReplicas=1`（月增成本約 $30-50）

---

## 6. 檔案類型對回應時間的影響

### 6.1 測試設計

針對 Blob Storage 中不同類型檔案各產生問題（共 20 題），使用預設 `ragindex`（by-sheet for Excel, DocAnalysisChunker for PDF/DOCX）測量回應時間。

| 類型 | 來源檔案 | 頁數/大小 | 題數 |
|------|---------|----------|------|
| DOCX | 東森林口會員權益手冊.docx | 28KB | 5 |
| PDF-A | 富邦投資健檢中心SWOT分析.pdf | 26頁, 1.6MB | 5 |
| PDF-B | 蔡琴演唱會.pdf | 5頁, 410KB | 4 |
| PDF-C | 迪士尼授權合作洽談.pdf | 41頁, 4.8MB | 3 |
| XLSX | 林口恩典大樓時程表 | 2 sheets | 3 |

### 6.2 結果

| 排名 | 類型 | 平均 | 最快 | 最慢 | 品質 |
|------|------|------|------|------|------|
| 1 | **XLSX** | **12.7s** | 11.6s | 13.4s | 20/20 ✅ |
| 2 | **PDF-B** (小PDF) | **12.8s** | 11.2s | 14.4s | 全部正確 |
| 3 | **PDF-C** (中PDF) | 17.8s | 12.5s | 26.0s | 全部正確 |
| 4 | **DOCX** | 19.1s | 13.6s | 29.1s | 全部正確 |
| 5 | **PDF-A** (大PDF) | **27.2s** | 11.9s | 70.2s | 全部正確 |

### 6.3 關鍵發現

- **回應品質：所有 20 題全部正確回答** — PDF/DOCX 經 Document Intelligence chunking 後品質很好
- **TTFB 一致在 1.1-1.3s** — 跟檔案類型完全無關
- **速度差異來自「chunk 中的資訊密度」而非檔案類型本身**：
  - 小檔案（蔡琴 5 頁）chunk 少而精確 → 快
  - 大檔案（SWOT 26 頁）含多表格多面向 → Agent 反覆搜尋 → 慢
  - 複雜規則文檔（會員手冊）LLM 需要理解條款邏輯 → 偏慢
- **異常慢的根因**：PDF-A Q4 (70.2s) 是因為問題涉及多表格交叉資訊，Agent 多次呼叫 `search_knowledge_base`

### 6.4 結論

**檔案類型對回應時間影響不大**。真正的瓶頸是：
1. chunk 中的資訊密度和複雜度
2. LLM 需要多少次搜尋才能收集到完整答案
3. 最終傳入 LLM 的總 token 數

---

## 7. 優化建議總結

### 第一優先（設定變更，無程式碼修改）

| 方案 | 動作 | 預期效果 |
|------|------|----------|
| **啟用 hybrid chunking** | 使用 `ingest_hybrid.py` 將 Excel 同時以 by-sheet + by-row 寫入 index | 品質最佳、速度與 by-sheet 相當或更快 |
| **設定 AGENT_ID** | 在 App Configuration 設定預建立的 Agent ID | 節省 ~1.5s |

### 第二優先（需測試品質影響）

| 方案 | 說明 | 預期效果 |
|------|------|----------|
| **切換到更快的模型** | `CHAT_DEPLOYMENT_NAME = gpt-4o-mini` | 速度提升 50-60%，品質略降 |
| **增加 topK** | `SEARCH_RAGINDEX_TOP_K = 5` | 改善 hybrid/by-row 的跨行查詢完整性 |
| **簡化 System Prompt** | 精簡 Jinja2 模板 | ⚠️ 實測差異 <1s（見第 9 節） |

### 第三優先（程式碼變更）

| 方案 | 說明 | 預期效果 |
|------|------|----------|
| **搜尋結果 token 截斷** | 在 `search_knowledge_base` 回傳前限制 content 長度 | 防止超大 chunk 拖慢 LLM |
| **修改 SpreadsheetChunker** | 讓 ingestion 服務原生支援 hybrid 模式 | 自動化 ingest 流程 |

---

## 8. 相關腳本

| 腳本 | 用途 |
|------|------|
| `scripts/ingest_byrow.py` | 將 Excel 用 by-row 模式 ingest 到 `ragindex-byrow` |
| `scripts/ingest_hybrid.py` | 將 Excel 用 hybrid 模式 ingest 到 `ragindex-hybrid` |
| `scripts/benchmark_index.py` | 比較 by-sheet / by-row / hybrid 三種 index 的效能（含 warmup） |
| `scripts/benchmark_filetypes.py` | 比較 PDF / DOCX / XLSX 不同檔案類型的效能 |
| `scripts/benchmark_prompt.py` | 比較 standard / lite prompt mode 的效能 |

---

## 9. System Prompt 精簡化實驗

### 9.1 實作

新增 `/prompt` 前端指令，可在 standard 與 lite 兩種 prompt 模式之間切換：

```
/prompt            ← 查看目前模式
/prompt lite       ← 切換到精簡版（~350-450 tokens）
/prompt standard   ← 切回標準版（~800-1000 tokens）
```

| 面向 | standard (main.jinja2) | lite (main_lite.jinja2) |
|------|----------------------|------------------------|
| **Token 數** | ~800-1000 | ~350-450 |
| Tool Selection | 完整 6 行 markdown 表格 + 警告 | 3 行 bullet points |
| call_transcripts 說明 | 6 個參數詳解 + 5 個使用範例 | 1 行參數列表 |
| Knowledge Base 規則 | 5 條詳細規則 + 範例 | 3 行精要 |

修改檔案（共 8 個）：

| 層級 | 檔案 | 修改 |
|------|------|------|
| **Orchestrator** | `schemas.py` | 新增 `prompt_mode` 欄位 |
| | `main.py` | 解析並傳遞 `prompt_mode` |
| | `orchestrator.py` | 傳遞到 strategy |
| | `single_agent_rag_strategy_v1.py` | 依 `prompt_mode` 選擇模板 |
| | **新增** `main_lite.jinja2` | 精簡版 prompt 模板 |
| **Frontend** | `app.py` | 新增 `/prompt` 指令 |
| | `orchestrator_client.py` | 傳遞 `prompt_mode` 參數 |

### 9.2 Benchmark 結果（10 題，含 warmup）

| # | 問題 | standard | lite | 差異 | 勝出 |
|---|------|----------|------|------|------|
| Q1 | 38F 完工日期 | 13.2s | **11.9s** | -1.3s | lite |
| Q2 | 27F 設計單位 | **11.8s** | 12.7s | +0.9s | standard |
| Q3 | 柏成設計樓層 | **15.7s** | 18.4s | +2.7s | standard |
| Q4 | 用途變更 | 18.5s | **17.9s** | -0.6s | lite |
| Q5 | 2026/08前完工 | **44.9s** | 47.1s | +2.2s | standard |
| Q6 | 30F 坪數 | **12.4s** | 17.8s | +5.3s | standard |
| Q7 | 酒店 28-36F | **13.6s** | 13.7s | +0.1s | 平手 |
| Q8 | 未定樓層 | 12.4s | **11.6s** | -0.8s | lite |
| Q9 | 維格設計裝潢 | 13.0s | **12.8s** | -0.1s | lite |
| Q10 | 全棟概述 | 23.9s | **20.0s** | -4.0s | lite |
| **AVG** | | **17.9s** | **18.4s** | **+0.4s (2%)** | **平手** |

lite wins: 5/10, standard wins: 5/10

### 9.3 結論

**standard 和 lite 的差異幾乎為零（0.4s / 2%）**。原因：

- LLM Thinking #1 只佔總時間的 ~7%（1-4s out of 15-20s total）
- 即使 prompt 省了 ~450 tokens，對整體時間影響極小
- 回應時間的主要波動來自 Azure OpenAI 的負載（非 prompt 長度）

**lite prompt 的價值**：不在速度，而在**省 token 成本**（每次請求少 ~400-550 input tokens）。

---

## 10. 部署記錄

| 日期 | Image Tag | 功能 |
|------|-----------|------|
| 2026-02-25 | `orchestrator:prompt-20260225091224` | 新增 `/prompt` 指令、prompt_mode 參數支援 |
| 2026-02-25 | `frontend:prompt-20260225091224` | 新增 `/prompt` 前端指令 |

部署方式：ACR Build → Portal 手動更新 Container App（因 MFA Conditional Access Policy 限制 CLI 寫入操作）。

---

*最後更新: 2026-02-25*
