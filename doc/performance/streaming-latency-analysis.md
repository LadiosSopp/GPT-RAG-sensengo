# GPT-RAG 串流延遲分析報告

**分析日期**: 2026-01-09  
**環境**: Azure Container Apps (eastus2)  
**版本**: Orchestrator ch6-20260109142010, Frontend ch5-20260109140046

---

## 1. 問題描述

使用者反映從提問到看到回應的時間過長（約 43 秒），希望了解延遲原因並評估優化可能性。

---

## 2. 測量方法

### 2.1 Frontend SSE 時間分析

在 `orchestrator_client.py` 中加入 SSE 時間戳記錄：
- 連線建立時間
- TTFB (Time To First Byte)
- 每個 chunk 的時間間隔
- 串流持續時間

### 2.2 Orchestrator 串流事件日誌

在 `single_agent_rag_strategy_v1.py` 的 `_stream_agent_response()` 方法中記錄所有 Azure OpenAI Agent Service 事件：
- 事件編號
- 累計時間
- 事件間隔
- 事件類型

---

## 3. 測量結果

### 3.1 整體時間分佈

| 階段 | 時間 | 佔比 | 說明 |
|------|------|------|------|
| CosmosDB 操作 | ~4s | 9% | 建立/讀取對話記錄 |
| Thread/Agent 建立 | ~1.3s | 3% | Azure Agent Service 初始化 |
| Agent 思考決策 | ~7s | 16% | 分析問題，決定呼叫工具 |
| 檢索執行 | ~1.7s | 4% | Embeddings + AI Search |
| **LLM 生成回應** | **~27s** | **63%** | **主要瓶頸** |
| 後處理 | ~2.4s | 5% | 歷史記錄 + 清理 |
| **總計** | **~43s** | 100% | |

### 3.2 串流事件詳細分析

根據 Orchestrator 日誌，單次請求共產生 **398 個串流事件**，總串流時間 **33.35 秒**：

```
事件時間線:
+0s        ────────────────────────────────────────────── 串流開始
           │
+0s~+7s    │  Agent 分析問題，決定呼叫 retrieval 工具
           │  (thread.run.created, thread.run.in_progress,
           │   thread.run.step.created [tool_calls])
           │
+7s~+9s    │  執行 Azure AI Search 檢索
           │  (thread.run.step.in_progress, thread.run.step.completed)
           │
+9s~+30s   │  LLM 處理檢索結果，準備生成回應
           │  ⚠️ 這段時間無法串流 - LLM 必須理解所有資料
           │
+30.074s   │  第一個 thread.message.delta 事件 ← 文字串流開始
           │
+30s~+33s  │  快速串流輸出 (288 個 delta 事件，~2.9 秒)
           │
+32.976s   │  thread.message.completed
+33.203s   │  thread.run.step.completed
+33.347s   │  thread.run.completed, done
           │
+33.35s    ────────────────────────────────────────────── 串流結束
```

### 3.3 關鍵發現

1. **Azure OpenAI Agent Service 內部確實使用串流**
   - 從 +30.074s 到 +32.976s，產生了 288 個 `thread.message.delta` 事件
   - 平均每個 delta 間隔約 0.01 秒，串流效率很高

2. **~30 秒的「思考時間」無法串流**
   - 這是 LLM 在分析問題、決定工具、處理檢索結果的時間
   - 這是 Agent 架構的固有限制，非技術問題

3. **一旦開始生成，串流非常快速**
   - 最後 ~3 秒產生了實際文字輸出
   - 串流傳輸到前端的延遲可忽略

---

## 4. 技術架構分析

### 4.1 Azure OpenAI Agent Service 處理流程

```
[使用者問題]
      ↓
[Agent 分析] ← 無法串流，必須完整處理
      ↓
[決定呼叫工具] ← 必須等待決策完成
      ↓
[執行檢索] ← 必須等待結果返回
      ↓
[處理檢索結果] ← 無法串流，LLM 必須理解所有資料
      ↓
[開始生成回應] ← 從這裡開始才能串流！
      ↓
[串流輸出] ✓ 這部分確實是串流的
```

### 4.2 為什麼前 30 秒無法串流？

| 階段 | 原因 |
|------|------|
| Agent 分析 | LLM 需要完整理解問題才能決定下一步 |
| 工具決策 | 必須產生完整的工具呼叫參數 |
| 檢索執行 | 必須等待 AI Search 返回結果 |
| 結果處理 | LLM 需要閱讀所有檢索文件才能開始生成 |

這是 **ReAct (Reasoning + Acting) 模式**的固有特性，不是技術缺陷。

---

## 5. 優化建議

### 5.1 可行的優化方案

| 優化方向 | 預期改善 | 實作難度 | 說明 |
|----------|----------|----------|------|
| **換用 gpt-4o-mini** | 思考時間減少 50%+ | 低 | 較小模型推理更快 |
| **簡化系統提示詞** | 減少 3-5 秒 | 中 | 減少 token 數量 |
| **減少檢索結果數量** | 減少處理時間 2-5 秒 | 中 | 從 top_k=5 降到 3 |
| **預熱 Agent** | 減少冷啟動 1-2 秒 | 高 | 保持 Agent 實例存活 |
| **取消 Agent 模式** | 可能減少 10-15 秒 | 高 | 改用直接 Chat Completion |

### 5.2 不可行的優化

| 方向 | 原因 |
|------|------|
| 讓 LLM 思考過程也串流 | Agent 必須完成推理才能行動 |
| 並行執行工具呼叫和生成 | 生成依賴工具結果 |
| 跳過檢索直接回答 | 會降低回答品質 |

### 5.3 建議的下一步

1. **短期**: 部署 gpt-4o-mini 並提供 UI 切換選項，讓使用者可以選擇速度優先或品質優先
2. **中期**: 評估簡化系統提示詞和減少檢索數量的影響
3. **長期**: 考慮是否需要 Agent 模式，或可以用更簡單的 RAG 流程

---

## 6. 結論

**目前系統已經是端到端串流**，使用者感受到的 ~30-40 秒延遲是 Azure OpenAI Agent Service 的「思考時間」，這是 Agent 架構的固有特性。

最有效的優化方式是**換用更快的模型 (gpt-4o-mini)**，可以在保持功能的同時顯著減少等待時間。

---

## 附錄：相關程式碼位置

| 檔案 | 功能 |
|------|------|
| `gpt-rag-ui/orchestrator_client.py` | SSE 串流客戶端 + 時間分析 |
| `gpt-rag-orchestrator/src/strategies/single_agent_rag_strategy_v1.py` | Agent 串流事件處理 |
| `gpt-rag-orchestrator/src/strategies/single_agent_rag_strategy_v1.py:_stream_agent_response()` | 串流事件日誌 |
