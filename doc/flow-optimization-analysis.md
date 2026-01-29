# GPT-RAG 呼叫流程優化分析

**分析日期**: 2026-01-26  
**基於**: 現有架構文檔 + 程式碼分析

---

## 1. 當前呼叫流程分析

### 1.1 完整請求流程時間線

```
使用者提問 (Frontend)
    │
    ▼ [HTTP POST /orchestrator]
┌─────────────────────────────────────────────────────────────┐
│ Orchestrator 處理流程                                        │
├─────────────────────────────────────────────────────────────┤
│ 1. Cosmos DB 讀取/建立對話 (~2-4s)                          │
│ 2. 建立/取得 Thread (~0.5-1s)                               │
│ 3. 建立/取得 Agent (~0.5-1.5s)                              │
│    └── 讀取 System Prompt                                    │
│ 4. 發送使用者訊息到 Thread (~0.3s)                          │
│ 5. 啟動 Agent Run Stream                                     │
│    ├── Agent 思考 + 決定呼叫工具 (~5-10s) ⚠️                │
│    ├── 執行 search_knowledge_base (~1-3s)                   │
│    │   ├── 生成 Embeddings (~0.3-0.5s)                      │
│    │   └── AI Search 查詢 (~0.5-1s)                         │
│    ├── LLM 處理搜尋結果 (~5-15s) ⚠️                        │
│    └── 生成回應串流 (~3-5s)                                  │
│ 6. 更新對話歷史到 Cosmos DB (~1-2s)                         │
│ 7. 清理臨時 Agent (~0.5s)                                   │
└─────────────────────────────────────────────────────────────┘
    │
    ▼ [SSE Stream]
Frontend 顯示回應
```

### 1.2 時間分佈 (基於實測數據)

| 階段 | 時間 | 佔比 | 狀態 |
|------|------|------|------|
| Cosmos DB 操作 | ~4s | 9% | 可優化 ✅ |
| Thread/Agent 建立 | ~1-3s | 5% | 可優化 ✅ |
| Agent 思考決策 | ~7s | 16% | 架構限制 ⚠️ |
| RAG 檢索 | ~1.5s | 4% | 已優化 ✅ |
| **LLM 生成回應** | **~27s** | **63%** | **主要瓶頸** ❌ |
| 後處理 | ~2s | 5% | 可優化 ✅ |
| **總計** | **~43s** | 100% | |

---

## 2. 可優化項目分析

### 2.1 ✅ 可立即優化 (不影響 RAG 品質)

#### A. Agent 重用優化
**現狀**: 每次請求都建立新 Agent，然後刪除  
**問題**: 浪費 ~1.5s + API 呼叫費用  
**建議**: 
- 設定 `AGENT_ID` 使用預建立的 Agent
- 或實作 Agent 池 (Agent Pool)

```python
# 在 App Configuration 設定
AGENT_ID = "asst_xxxx"  # 預建立的 Agent ID
```

**預期節省**: 1-1.5 秒

#### B. Cosmos DB 連線池優化
**現狀**: 可能每次都建立新連線  
**建議**: 確保使用連線池和 session consistency

**預期節省**: 0.5-1 秒

#### C. Thread 重用
**現狀**: 同一對話已重用 Thread ✅  
**確認**: 目前實作正確，無需更改

### 2.2 ⚠️ 需評估影響的優化

#### D. 減少 RAG 結果數量
**現狀**: `SEARCH_RAGINDEX_TOP_K = 3` (預設)  
**分析**: 
- 減少到 2 可節省 ~0.3s
- 可能影響回答品質

```python
# 評估方案
SEARCH_RAGINDEX_TOP_K = 2  # 測試回答品質
```

**預期節省**: 0.2-0.5 秒 (需測試品質影響)

#### E. 簡化 System Prompt
**現狀**: 完整的 Jinja2 模板 (~800-1000 tokens)  
**分析**: 
- 每個 token 都增加 LLM 處理時間
- 但過度簡化可能影響回答品質

**建議**: 
1. 移除重複的說明
2. 精簡指令格式
3. 保留核心 RAG 指令

**預期節省**: 1-3 秒 (取決於簡化程度)

### 2.3 ❌ 架構限制 (無法直接優化)

#### F. Agent 思考時間
**原因**: Azure AI Foundry Agent Service 的 ReAct 模式需要完整思考
**狀態**: 這是 Agent 架構的固有特性，非技術缺陷

#### G. LLM 生成時間
**原因**: GPT-4 級模型本身需要時間處理和生成
**替代方案**: 使用更快的模型 (見下節)

---

## 3. 高影響優化建議

### 3.1 🚀 使用更快的模型

| 模型 | 思考時間 | 生成速度 | 品質 | 建議 |
|------|----------|----------|------|------|
| gpt-4.1 | 較慢 | 較慢 | 最高 | 複雜問題 |
| gpt-4o-mini | 快 50%+ | 快 2-3x | 良好 | **預設推薦** |
| gpt-5-nano | 最快 | 最快 | 中等 | 簡單問答 |

**建議**:
```python
# App Configuration
CHAT_DEPLOYMENT_NAME = "gpt-4o-mini"  # 預設使用快速模型
```

**預期節省**: 15-25 秒 (思考+生成時間減少 50%)

### 3.2 🔧 移除 Agent 建立/刪除開銷

修改 `single_agent_rag_strategy_v1.py`:

```python
# 建議: 預先建立 Agent 並在 App Configuration 設定 AGENT_ID
# 這樣可以跳過每次請求的 Agent 建立和刪除

# 在 initiate_agent_flow() 中:
# 移除 Step 6: Cleanup temporary agent
# if create_agent:
#     await self._cleanup_agent(project_client, agent.id)  # 刪除此行
```

### 3.3 📊 非 Agent 模式 (最大優化)

如果不需要 Agent 的複雜推理能力，可考慮直接使用 Chat Completion:

```
現有 Agent 模式流程:
Request → Agent 思考 → 決定工具 → 執行 RAG → 處理結果 → 生成回應
   └── 這個循環至少需要 2 次 LLM 呼叫 (思考 + 生成)

直接 RAG 模式:
Request → RAG 檢索 → Chat Completion (1 次呼叫)
   └── 省去 Agent 的思考循環
```

**預期節省**: 10-20 秒 (移除 Agent 決策循環)

**缺點**: 失去 Agent 的動態工具選擇能力

---

## 4. 不建議的優化 (會影響 RAG 品質)

| 優化項目 | 原因 |
|----------|------|
| 跳過 RAG 檢索 | 直接影響回答準確性 |
| 大幅減少檢索結果 | 可能遺漏重要資訊 |
| 過度截斷上下文 | 影響 LLM 理解能力 |
| 關閉向量搜尋 | 降低檢索精度 |

---

## 5. 實施優先順序

### 第一階段 (立即可做，無風險)

| 優化 | 預期節省 | 難度 |
|------|----------|------|
| 設定 AGENT_ID 重用 Agent | 1-1.5s | 低 |
| 移除 Agent 刪除步驟 | 0.5s | 低 |
| 啟用 DEBUG_MODE_ENABLED 監控 | 0s (但可追蹤瓶頸) | 低 |

### 第二階段 (需測試品質影響)

| 優化 | 預期節省 | 難度 |
|------|----------|------|
| 切換到 gpt-4o-mini | 15-25s | 中 |
| 簡化 System Prompt | 1-3s | 中 |

### 第三階段 (架構變更)

| 優化 | 預期節省 | 難度 |
|------|----------|------|
| 實作非 Agent 直接 RAG 模式 | 10-20s | 高 |
| Agent 池化 | 1-2s | 高 |

---

## 6. 監控建議

啟用 DEBUG_MODE_ENABLED 後，前端會顯示:

1. **執行摘要**: 總時間、各步驟耗時
2. **System Prompt**: 完整提示詞和 token 估計
3. **RAG 結果**: 搜尋查詢、結果數量、分數
4. **Tool 呼叫**: 每個工具的執行時間
5. **LLM 呼叫**: 模型、token 使用量

這些資訊可幫助:
- 識別真正的瓶頸
- 評估優化效果
- 比較不同模型的效能

---

## 7. 配置範例

### 7.1 效能優先配置

```env
# App Configuration (gpt-rag label)
AGENT_ID = "asst_xxxxx"           # 預建立的 Agent
CHAT_DEPLOYMENT_NAME = "gpt-4o-mini"  # 快速模型
SEARCH_RAGINDEX_TOP_K = 2         # 減少檢索數量
DEBUG_MODE_ENABLED = true         # 啟用監控
```

### 7.2 品質優先配置

```env
# App Configuration (gpt-rag label)  
CHAT_DEPLOYMENT_NAME = "gpt-4.1"  # 最強模型
SEARCH_RAGINDEX_TOP_K = 5         # 更多上下文
DEBUG_MODE_ENABLED = true         # 啟用監控
```

---

## 8. 結論

**最有效的優化方式** (按效果排序):

1. **換用 gpt-4o-mini** (節省 15-25s，品質影響小)
2. **預建立 Agent** (節省 1-2s，無品質影響)
3. **實作直接 RAG 模式** (節省 10-20s，但失去 Agent 功能)

**建議先實施**:
1. 啟用 DEBUG_MODE_ENABLED 收集基線數據
2. 設定 AGENT_ID 重用 Agent
3. 評估切換到 gpt-4o-mini 的品質影響
