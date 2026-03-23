# 即時銷售輔助 Agent — 架構設計文件

> **建立日期**：2026-03-10  
> **最後更新**：2026-03-10  
> **狀態**：Draft  
> **相關元件**：LangGraph, Azure Container Apps, Azure SQL DB, Azure AI Search, Azure OpenAI, Azure Blob Storage

---

## 1. 目標概述

建立一個 **即時銷售輔助系統**，在電話銷售（OB, Outbound）進行中，根據客戶的 Persona 與歷史通話記錄，即時生成個人化的銷售策略建議，提升推銷成功率。

### 核心價值

| 面向 | 現狀 | 目標 |
|------|------|------|
| 銷售策略 | 專員依經驗判斷 | 系統根據客戶特徵 + 歷史數據提供即時建議 |
| 客戶理解 | 需手動查閱資料 | 自動彙整 Persona + 過去對話摘要 |
| 成功率預測 | 無 | 模型預估成功機率並給出關鍵影響因子 |
| 即時反應 | 無 | 對話中即時偵測關鍵時刻，動態調整建議 |

---

## 2. 整體架構

系統分為兩大階段：**離線訓練** 與 **即時推論**。
即時推論階段採用 **Multi-Agent Supervisor Pattern**，以 LangGraph 編排三個專職 Agent，部署於 Azure Container Apps。

### 2.1 系統全景圖

```
╔══════════════════════════════════════════════════════════════════════════╗
║                         Phase 1: 離線訓練 (Offline Training)            ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐  ║
║  │ Persona 資料     │    │ 歷史通話文本     │    │ 推銷結果         │  ║
║  │ (53 欄位)        │    │ (1,100 通)       │    │ (成功/失敗)      │  ║
║  └────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘  ║
║           │                       │                       │            ║
║           ▼                       ▼                       │            ║
║  ┌──────────────────┐    ┌──────────────────┐             │            ║
║  │ 結構化特徵       │    │ LLM 特徵萃取    │             │            ║
║  │ → Azure SQL DB   │    │ → Vectorize      │             │            ║
║  │                  │    │ → AI Search      │             │            ║
║  └────────┬─────────┘    └────────┬─────────┘             │            ║
║           │                       │                       │            ║
║           └───────────┬───────────┘                       │            ║
║                       ▼                                   │            ║
║              ┌──────────────────┐                         │            ║
║              │ 特徵矩陣合併    │◄────────────────────────┘            ║
║              └────────┬─────────┘                                      ║
║                       ▼                                                ║
║              ┌──────────────────┐    ┌──────────────────────────────┐  ║
║              │ 模型訓練         │───►│ 輸出                         │  ║
║              │ (XGBoost/LGB)   │    │ • 成功機率預測模型           │  ║
║              │                  │    │ • 特徵重要度排名 (SHAP)     │  ║
║              │                  │    │ • 銷售策略知識庫 (RAG)      │  ║
║              └──────────────────┘    └──────────────────────────────┘  ║
║                                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### 2.2 Phase 2 — Multi-Agent 即時推論架構

```
╔══════════════════════════════════════════════════════════════════════════╗
║                     Phase 2: 即時推論 (Real-Time Inference)             ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  ┌─────────────────────────────────────────────────────────────────┐   ║
║  │                   Front-end / Copilot                            │   ║
║  │              （銷售專員即時建議介面）                             │   ║
║  └──────────────────────────┬──────────────────────────────────────┘   ║
║                             │ HTTP / SSE                               ║
║                             ▼                                          ║
║  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  ║
║  │  Orchestration Layer (LangGraph in Azure Container Apps)        │  ║
║  │                                                                 │  ║
║  │  ┌──────────────────┐                                           │  ║
║  │  │  Azure OpenAI    │    ┌────────────────────────────────┐     │  ║
║  │  │  (LLM Engine)    │◄──►│   Reasoning Agent (Supervisor) │     │  ║
║  │  │  GPT-4.1 / GPT-5 │    │                                │     │  ║
║  │  └──────────────────┘    │   • 接收兩個子 Agent 的結果    │     │  ║
║  │           ▲               │   • 綜合研判 + 策略生成        │     │  ║
║  │           │               │   • 輸出個人化銷售建議        │     │  ║
║  │           │               └──────────┬─────────────────────┘     │  ║
║  │           │                    ┌─────┴──────┐                    │  ║
║  │           │                    │            │                    │  ║
║  │           │               dispatch      dispatch                │  ║
║  │           │                    │            │                    │  ║
║  │           ▼                    ▼            ▼                    │  ║
║  │  ┌──────────────────┐  ┌──────────────────────────────────┐     │  ║
║  │  │  Data Agent      │  │  Context RAG Agent               │     │  ║
║  │  │  (Structured     │  │  (Unstructured Data)             │     │  ║
║  │  │   Data)          │  │                                  │     │  ║
║  │  │                  │  │  • Hybrid Search (向量+關鍵字)   │     │  ║
║  │  │  • SQL Query     │  │  • 檢索歷史通話中的：           │     │  ║
║  │  │  • 結構化 Persona│  │    - 客戶痛點                   │     │  ║
║  │  │  • 消費數據      │  │    - 禁忌/地雷                  │     │  ║
║  │  │  • 預測模型      │  │    - 過去成功/失敗因素         │     │  ║
║  │  │    Scoring       │  │    - 偏好與習慣                 │     │  ║
║  │  └────────┬─────────┘  └──────────────┬───────────────────┘     │  ║
║  │           │ SQL Query                  │ Hybrid Search           │  ║
║  └ ─ ─ ─ ─ ─┼─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┼─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  ║
║             │                            │                            ║
║             ▼                            ▼                            ║
║  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  ║
║  │  Data Layer                                                     │  ║
║  │                                                                 │  ║
║  │  ┌──────────────────┐    ┌──────────────────────────────────┐   │  ║
║  │  │  Azure SQL DB    │    │  Azure AI Search (Vector DB)     │   │  ║
║  │  │  (Persona Data)  │    │                                  │   │  ║
║  │  │                  │    │  • 歷史通話逐字稿 (vectorized)  │   │  ║
║  │  │  • 人口統計      │    │  • Persona 文字摘要             │   │  ║
║  │  │  • 消費行為      │    │  • 會員卡權益知識               │   │  ║
║  │  │  • 生活型態標籤  │    │  • 銷售話術 & 異議處理         │   │  ║
║  │  │  • 高價值指標    │    │                                  │   │  ║
║  │  │  • 預測特徵      │    ├──────────────────────────────────┤   │  ║
║  │  │                  │    │  Azure Blob Storage              │   │  ║
║  │  │                  │    │  (Call Logs - 原始通話文本)      │   │  ║
║  │  └──────────────────┘    └──────────────────────────────────┘   │  ║
║  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  ║
║                                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### 2.3 為什麼用 Multi-Agent 而非 Single Agent？

| 面向 | Single Agent + Tools | Multi-Agent (Supervisor) |
|------|---------------------|-------------------------|
| **關注點分離** | 一個 Agent 身兼數職，Prompt 臃腫 | 每個 Agent 專注單一職責，Prompt 精簡有效 |
| **資料存取模式** | 全部走 Function Calling | Data Agent 走 SQL（精確查詢），Context Agent 走 Hybrid Search（語意檢索），各取所長 |
| **推理品質** | LLM 需同時理解 SQL 結果 + 語意檢索 + 策略生成 | Reasoning Agent 只負責「綜合研判」，輸入已是結構化的子 Agent 報告 |
| **可擴展性** | 加 Tool 就越來越複雜 | 加新 Agent（如即時語音分析 Agent）不影響現有流程 |
| **錯誤隔離** | 一個 Tool 失敗可能影響整體 | 子 Agent 失敗可降級處理，不影響其他分支 |
| **平行執行** | 需 LLM 主動平行呼叫 | LangGraph 原生支援 Data Agent + Context Agent 平行 dispatch |

---

## 3. Phase 1 — 離線訓練：特徵工程與模型建構

### 3.1 資料來源盤點

| 資料集 | 來源 | 筆數 | 說明 |
|--------|------|------|------|
| Persona 結構化欄位 | `persona_random_pick.1K.csv` | 1,185 | 53 欄位，含人口統計、消費行為、生活風格標籤 |
| Persona 文字描述 | `persona` 欄位 / `persona_對應通話文本.csv` | 728+ | LLM 從歷史對話中萃取的客戶特徵摘要 |
| 通話逐字稿 | `會員卡推廣名單通話文本_成功失敗各500人_去敏.xlsx` / Cosmos DB `call-transcripts` | 1,100 | 含推銷結果（成功 676 / 失敗 424） |
| 會員卡權益 | `會員卡權益_服務與優惠內容/` | — | 產品知識，供 RAG 檢索 |

### 3.2 特徵分類

#### A. 結構化 Persona 特徵（直接可用）

| 類別 | 欄位 | 處理方式 |
|------|------|----------|
| **人口統計** | 性別、年齡、縣市、星座 | One-hot / Label Encoding |
| **會員屬性** | OB等級(A/B/C/Z)、會員年資_天數 | Label Encoding / 數值 |
| **生活型態** | 是否獨居、寵愛自己名單、高健康/美麗意識、健檢/美容/保健標籤、有無養寵物 | Binary |
| **消費行為 — 全通路** | 歷史/近三年/近一年 累積消費金額 & 件數（總計、保健、美容） | 數值，考慮做 log transform |
| **消費行為 — OB** | 同上但限 OB 通路 | 數值 |
| **高價值指標** | 高單一次付清、黃金鑽石、十年地址不變、商務菁英、房產投資客、高爾夫、富等信用卡、高價保單、科學園區、大額禮券、收藏品、退休保健族、珠寶客、理財、高價地段、高社經地位 | Binary（共 16 個） |

#### B. 對話萃取特徵（需 LLM 抽取）

從 Persona 文字描述 + 通話逐字稿中，利用 LLM 萃取以下結構化特徵：

| 特徵 | 萃取方式 | 說明 |
|------|----------|------|
| **家庭結構** | LLM extraction | 獨居/有配偶/有子女/有孫輩 → 數值化 |
| **健康關注領域** | LLM extraction | 保健品類別偏好（眼睛、骨骼、美容、綜合保健...） |
| **品牌偏好** | LLM extraction | 偏好東森自有 / 外部品牌 / 無特別偏好 |
| **價格敏感度** | LLM extraction | 對價格的反應（詢問折扣次數、比價行為...） |
| **過去購買滿意度** | LLM extraction | 正面/中性/負面 |
| **拒絕原因分類** | LLM extraction（失敗通話）| 不需要/太貴/已有替代/沒時間/不信任 |
| **通話語氣分析** | LLM extraction | 友善/冷淡/急躁/猶豫 |
| **對話長度特徵** | 規則計算 | 逐字稿長度、輪次數、客戶說話比例 |
| **時間特徵** | 規則計算 | 通話時段（上午/下午/晚上）、星期幾 |

#### C. 衍生特徵（Feature Engineering）

| 特徵 | 計算公式 | 說明 |
|------|----------|------|
| OB消費佔比 | `ob歷史消費金額 / 全通路歷史消費金額` | 對 OB 通路的依賴程度 |
| 近一年消費趨勢 | `近一年消費金額 / 近三年平均年消費金額` | 消費活躍度變化 |
| 保健美容比 | `保健消費金額 / (保健+美容)` | 品類偏好 |
| 消費頻率 | `消費件數 / 會員年資天數 * 365` | 年均消費頻率 |
| 客單價 | `消費金額 / 消費件數` | 平均客單價 |
| 高價值標籤數 | 16 個 binary 標籤的加總 | 高價值客戶綜合指數 |

### 3.3 模型訓練方案

#### 目標變數

- `y = 推銷狀態`（成功=1, 失敗=0）— Binary Classification

#### 模型選擇

| 模型 | 優勢 | 適用場景 |
|------|------|----------|
| **XGBoost** | 速度快、可解釋、特徵重要性好 | 主力模型，用於即時 scoring |
| **LightGBM** | 大量類別特徵處理好 | 備選 |
| **Logistic Regression** | 最可解釋、係數直接有意義 | Baseline 模型 + 解釋用 |

#### 訓練流程

```
1. 資料合併
   persona_random_pick.1K.csv (by unikey3)
     ⟕ JOIN ⟕
   通話文本.xlsx (by 客代)
     → 合併表（含 Persona 欄位 + 逐字稿 + 推銷結果）

2. 特徵工程
   → 結構化特徵 (A) + LLM 萃取特徵 (B) + 衍生特徵 (C)
   → 特徵矩陣 X, 標籤 y

3. 模型訓練
   → Train/Test Split (80/20, stratified)
   → XGBoost + 5-fold CV
   → Hyperparameter Tuning (Bayesian Optimization)

4. 模型評估
   → AUC-ROC, Precision, Recall, F1
   → Confusion Matrix
   → SHAP Value 分析（全局 + 局部可解釋性）

5. 產出物
   → 訓練好的模型檔 (model.pkl / model.onnx)
   → 特徵重要度排名
   → SHAP summary plot
   → 特徵轉換 pipeline (sklearn Pipeline)
```

### 3.4 SHAP 解釋性分析 — 驅動銷售策略

SHAP 分析不只是模型驗證，更是銷售策略的核心驅動：

```
SHAP Output 範例:
─────────────────────────────────────────────
特徵                      | SHAP 重要度 | 方向
─────────────────────────────────────────────
近一年保健消費金額        | 0.23        | 正相關（越高越易成功）
通話客戶說話比例          | 0.18        | 正相關（客戶參與度高）
OB等級                    | 0.15        | A > B > C > Z
年齡                      | 0.12        | 50-65 歲區間成功率最高
價格敏感度               | 0.11        | 負相關（越敏感越難）
過去購買滿意度           | 0.09        | 正相關
拒絕原因(歷史)           | 0.08        | 「已有替代」最難轉化
─────────────────────────────────────────────

→ 這些發現直接轉化為 Sales Agent 的決策規則
```

---

## 4. Phase 2 — 即時推論：Multi-Agent 設計

採用 **LangGraph Supervisor Pattern**，將複雜的銷售輔助任務分解為三個專責 Agent，由 Reasoning Agent 統籌協調。

### 4.1 Multi-Agent vs Single-Agent 比較

| 面向 | Single-Agent | Multi-Agent (Supervisor) |
|------|-------------|--------------------------|
| 架構 | 單一 Agent + 多 Tools | 多個專責 Agent + Supervisor |
| 上下文管理 | 所有資訊混在同一 context | 各 Agent 獨立 context，互不干擾 |
| Prompt 品質 | Token 膨脹，指令模糊 | 各 Agent 精準 Prompt，品質高 |
| 錯誤隔離 | 一個 Tool 失敗影響全局 | Agent 失敗可獨立重試 |
| 擴展性 | 加 Tool 會讓 Prompt 越來越長 | 加 Agent 不影響既有 Agent |
| 適用場景 | 簡單 QA | 多資料源 + 推理的複雜場景 |

### 4.2 整體 Agent 架構圖

```
+------------------------------------------------------------------+
|                    Reasoning Agent (Supervisor)                    |
|                                                                   |
|  "綜合客戶結構化資料 + 歷史對話脈絡，                               |
|   動態生成個人化銷售策略"                                           |
|                                                                   |
|  +---------------------+     +-----------------------------+      |
|  |     Data Agent       |     |    Context RAG Agent        |      |
|  |                      |     |                             |      |
|  |  +---------------+   |     |  +-----------------------+  |      |
|  |  | sql_query      |   |     |  | hybrid_search         |  |      |
|  |  | (Azure SQL)    |   |     |  | _transcripts          |  |      |
|  |  +---------------+   |     |  | (Azure AI Search)     |  |      |
|  |  +---------------+   |     |  +-----------------------+  |      |
|  |  | predict_score  |   |     |  +-----------------------+  |      |
|  |  | (ML Model)     |   |     |  | search_sales          |  |      |
|  |  +---------------+   |     |  | _knowledge            |  |      |
|  |                      |     |  | (Azure AI Search)     |  |      |
|  +---------------------+     |  +-----------------------+  |      |
|          |                    |                             |      |
|          |                    +-----------------------------+      |
|          |                              |                         |
|          v                              v                         |
|  +--------------+              +------------------+               |
|  | Azure SQL DB |              | Azure AI Search  |               |
|  | (Persona     |              | (Vector DB)      |               |
|  |  結構化資料)  |              | + Azure Blob     |               |
|  +--------------+              |   Storage        |               |
|                                +------------------+               |
+------------------------------------------------------------------+
```

### 4.3 各 Agent 詳細設計

#### 4.3.1 Data Agent — 結構化資料查詢

**職責**：查詢 Azure SQL DB 中的客戶 Persona 結構化資料，並呼叫 ML 模型預測成功機率。

**Tools**：

| Tool | 資料源 | 說明 |
|------|--------|------|
| `sql_query` | Azure SQL DB | 查詢客戶 Persona 欄位（年齡、消費力、偏好標籤等） |
| `predict_score` | ML Model API | 根據 Persona 特徵預測推銷成功機率 + SHAP 重要特徵 |

**Prompt 設計**：

```
你是東森購物的客戶資料分析專家。

任務：根據客代查詢 Azure SQL DB，取得客戶完整 Persona 資料，
並呼叫預測模型取得推銷成功機率。

輸出格式：
- 客戶基本屬性：性別、年齡、縣市、會員年資、OB等級
- 消費力指標：全通路歷史金額、近一年金額、客單價
- 偏好標籤：高價值指標（食品控、保健控、美容控等）
- 預測成功機率：XX% (SHAP Top-3 影響因子)

注意：只回傳事實資料，不做推薦判斷。
```

#### 4.3.2 Context RAG Agent — 非結構化資料檢索

**職責**：從 Azure AI Search 中檢索歷史通話記錄與銷售知識庫，提取客戶痛點、禁忌、偏好等上下文。

**Tools**：

| Tool | 資料源 | 說明 |
|------|--------|------|
| `hybrid_search_transcripts` | Azure AI Search (call-transcripts index) | 向量+關鍵字混合搜尋歷史通話文本 |
| `search_sales_knowledge` | Azure AI Search (sales-knowledge index) | 搜尋產品知識、話術範本、促銷活動等 |

**Prompt 設計**：

```
你是東森購物的通話歷史分析專家。

任務：根據客代搜尋歷史通話記錄，萃取以下資訊：
1. 客戶曾表達的痛點與需求
2. 客戶的禁忌與拒絕原因（例如：過敏成分、價格敏感）
3. 過去成功/失敗的推銷經驗
4. 客戶偏好的溝通風格

同時搜尋銷售知識庫，找出：
- 適合此客戶 profile 的產品資訊
- 相關的促銷活動與優惠方案
- 推薦話術範本

輸出格式：結構化摘要，區分「客戶洞察」與「銷售素材」兩大區塊。
```

#### 4.3.3 Reasoning Agent (Supervisor) — 推理與策略生成

**職責**：接收來自 Data Agent 和 Context RAG Agent 的資訊，綜合推理後生成個人化銷售建議。

**Prompt 設計**：

```
你是東森購物的資深銷售策略顧問。

你有兩個專屬助手：
1. Data Agent：提供客戶結構化 Persona 資料與成功預測
2. Context RAG Agent：提供歷史通話洞察與銷售知識

工作流程：
1. 先請 Data Agent 查詢客戶 Persona 與預測分數
2. 再請 Context RAG Agent 檢索歷史通話與銷售素材
3. 綜合兩方資訊，生成銷售策略

輸出必須包含：
- 客戶畫像摘要（一句話描述此客戶）
- 成功機率與關鍵影響因子
- 推薦產品（Top 3，附推薦理由）
- 開場話術建議
- 應避免的地雷區
- 促銷方案搭配建議

原則：
- 所有建議必須基於資料，不可憑空臆測
- 標注每個建議的資料來源（Persona / 通話紀錄 / 知識庫）
- 如果預測成功率低於 30%，需特別提醒並建議替代策略
```

### 4.4 LangGraph 流程實作

```python
from langgraph.graph import StateGraph, MessagesState
from langgraph.prebuilt import create_react_agent
from langgraph_supervisor import create_supervisor

# --- Data Agent ---
data_agent = create_react_agent(
    model=azure_openai_model,
    tools=[sql_query, predict_score],
    name="data_agent",
    prompt="你是客戶資料分析專家，負責查詢 Azure SQL DB 的 Persona 資料與預測模型。"
)

# --- Context RAG Agent ---
context_rag_agent = create_react_agent(
    model=azure_openai_model,
    tools=[hybrid_search_transcripts, search_sales_knowledge],
    name="context_rag_agent",
    prompt="你是通話歷史與銷售知識檢索專家，負責從 Azure AI Search 檢索相關資訊。"
)

# --- Reasoning Agent (Supervisor) ---
supervisor = create_supervisor(
    model=azure_openai_model,
    agents=[data_agent, context_rag_agent],
    prompt=(
        "你是東森購物的資深銷售策略顧問。"
        "先請 data_agent 查詢客戶資料，"
        "再請 context_rag_agent 檢索歷史通話與銷售知識，"
        "最後綜合產出個人化銷售建議。"
    ),
    output_mode="full_history"
)

# --- 編譯圖 ---
app = supervisor.compile()
```

### 4.5 完整協作範例

**場景**：電銷人員準備撥打客代 `10056675` 推銷會員卡

```
步驟 1: Reasoning Agent 接收請求
  「請準備客代 10056675 的銷售策略」

步驟 2: 委派 Data Agent
  -> sql_query("SELECT * FROM customer_persona WHERE customer_id='10056675'")
  -> predict_score(features={年齡:45, OB等級:1, 近一年金額:23800...})
  <- 回傳：女性/45歲/台北/高消費力/保健控/預測成功率 72%
  <- SHAP: 近一年金額(+0.15), 保健控(+0.12), 會員年資(+0.08)

步驟 3: 委派 Context RAG Agent
  -> hybrid_search_transcripts("10056675")
  -> search_sales_knowledge("保健 高消費 會員卡")
  <- 通話洞察：腸胃敏感、偏好天然成分、曾拒絕含人工色素產品
  <- 銷售素材：天然保健品系列、會員卡 9 折優惠、滿額贈品活動

步驟 4: Reasoning Agent 綜合推理
  <- 產出：
    客戶畫像：高消費力保健導向熟齡女性，腸胃敏感注重天然成分
    成功機率：72% (關鍵因子：近期高消費 + 保健偏好)
    推薦產品：(1)天然益生菌 (2)有機膠原蛋白 (3)草本舒壓茶
    開場建議：從健康保養切入，提及天然成分優勢
    地雷區：避免推薦含人工色素/添加物產品
    促銷搭配：會員卡 + 保健品滿 3000 送養生禮盒
```

### 4.6 Multi-Agent 交匯價值

當 Data Agent 的結構化 Persona 資料（消費力、偏好標籤）與 Context RAG Agent 的非結構化洞察（痛點、禁忌、溝通風格）交匯於 Reasoning Agent 時，系統可以動態生成：

> 「客戶為高消費力商務人士，但目前工作壓力大且腸胃敏感，請推薦溫和型的高階舒壓產品，並避開含有 X 成分的品項。」

這種**高度個人化且安全的應答策略**，是單一 Agent 難以達成的。

---

## 5. 資料儲存設計

### 5.1 Azure SQL DB — 結構化 Persona 資料

Data Agent 透過 `sql_query` Tool 直接以 SQL 查詢 Azure SQL DB，適合結構化 Persona 欄位的精確查詢與彙總統計。

#### 資料表設計

| Table | 說明 |
|-------|------|
| `customer_persona` | 客戶 Persona 主表（人口統計、消費、標籤） |
| `sales_predictions` | 預測結果快取 & 銷售建議歷史 |

#### `customer_persona` Table Schema

```sql
CREATE TABLE customer_persona (
    customer_id        NVARCHAR(20) PRIMARY KEY,
    -- 人口統計
    gender             NVARCHAR(5),
    age                INT,
    city               NVARCHAR(30),
    zodiac             NVARCHAR(10),
    ob_level           NVARCHAR(5),
    membership_days    INT,
    lives_alone        BIT,
    -- 全通路消費
    total_hist_amount  DECIMAL(12,2),
    total_hist_items   INT,
    recent_3y_amount   DECIMAL(12,2),
    recent_3y_items    INT,
    recent_1y_amount   DECIMAL(12,2),
    recent_1y_items    INT,
    recent_1y_health_amount  DECIMAL(12,2),
    recent_1y_health_items   INT,
    recent_1y_beauty_amount  DECIMAL(12,2),
    recent_1y_beauty_items   INT,
    -- OB 消費
    ob_hist_amount     DECIMAL(12,2),
    ob_hist_items      INT,
    ob_recent_1y_amount DECIMAL(12,2),
    ob_recent_1y_items INT,
    -- 生活型態標籤
    self_care_list     BIT,
    health_conscious   BIT,
    beauty_conscious   BIT,
    health_check       BIT,
    beauty_tag         BIT,
    supplement_tag     BIT,
    has_pets           BIT,
    -- 高價值指標 (16 欄位)
    high_single_payment BIT,
    gold_diamond       BIT,
    stable_address_10y BIT,
    business_elite     BIT,
    real_estate_investor BIT,
    golf               BIT,
    premium_credit_card BIT,
    high_insurance     BIT,
    science_park_3km   BIT,
    large_voucher      BIT,
    collectibles       BIT,
    retired_health     BIT,
    jewelry_client     BIT,
    finance_interest   BIT,
    premium_location   BIT,
    high_ses_occupation BIT,
    -- Persona 文本 & 衍生特徵
    persona_text       NVARCHAR(MAX),
    ob_ratio           DECIMAL(5,3),
    consumption_trend  DECIMAL(5,2),
    health_beauty_ratio DECIMAL(5,3),
    annual_frequency   DECIMAL(6,2),
    avg_order_value    DECIMAL(10,2),
    high_value_score   INT,
    -- 時間戳
    updated_at         DATETIME2 DEFAULT GETUTCDATE()
);

-- 常用查詢索引
CREATE INDEX IX_persona_city ON customer_persona(city);
CREATE INDEX IX_persona_ob_level ON customer_persona(ob_level);
CREATE INDEX IX_persona_age ON customer_persona(age);
```

#### Data Agent SQL 查詢範例

```sql
-- 查詢單一客戶完整 Persona
SELECT * FROM customer_persona WHERE customer_id = '10056675';

-- 查詢同類客群的平均消費力（供比較）
SELECT AVG(recent_1y_amount) as avg_amount, AVG(ob_ratio) as avg_ob_ratio
FROM customer_persona
WHERE ob_level = 'C' AND age BETWEEN 50 AND 60;
```

### 5.1.1 Cosmos DB（維持既有）

| Container | Partition Key | 用途 |
|-----------|--------------|------|
| `call-transcripts` | `/customer_id` | **已存在** — 通話逐字稿（原始儲存） |

### 5.2 Azure AI Search — 新增 Index

| Index | 用途 | 資料來源 |
|-------|------|----------|
| `ragindex` | **已存在** — 通用 RAG 知識庫 | 文件上傳 |
| `sales-knowledge` | **新增** — 銷售專用知識庫 | 下方內容 |

#### `sales-knowledge` Index 內容規劃

| 文件類型 | 內容 | 來源 |
|----------|------|------|
| 會員卡權益 | 各級會員卡收費、權益、服務 | `會員卡權益_服務與優惠內容/` |
| 競品比較 | 競業會員卡優劣比較 | `競業會員卡比較_改.md` |
| 成功話術 | 從成功通話中萃取的有效銷售話術 | LLM 萃取 from 676 成功通話 |
| 異議處理 | 常見客戶拒絕理由 + 應對話術 | LLM 萃取 from 424 失敗通話 |
| 客戶分群策略 | 不同 Persona 類型的最佳銷售策略 | Phase 1 SHAP 分析 + LLM 整理 |

---

## 6. ML 模型部署方案

### 6.1 選項比較

| 方案 | 優勢 | 劣勢 | 適用 |
|------|------|------|------|
| **A. Azure ML Managed Endpoint** | 全託管、自動擴縮、MLflow 整合 | 成本較高（最低 $0.12/hr） | 生產環境 |
| **B. 嵌入 sales-agent Container App** | 與 LangGraph Agent 同容器、無網路延遲 | 模型更新需重新部署 | MVP / POC |
| **C. 獨立 ML API Container App** | 模型獨立部署、可個別擴縮 | 多一個服務需維護 | 規模化 |

#### 建議：Phase 1 用方案 B（嵌入 LangGraph Agent），驗證後升級至方案 A 或 C

### 6.2 方案 B — 嵌入 LangGraph Agent 部署

```python
# sales-agent/src/tools/predict_score.py

class SalesPredictor:
    """嵌入式銷售成功率預測器"""
    
    def __init__(self, model_path: str = "models/sales_model.pkl"):
        self.model = joblib.load(model_path)
        self.feature_pipeline = joblib.load("models/feature_pipeline.pkl")
        self.explainer = shap.TreeExplainer(self.model)
    
    async def predict(self, customer_features: dict) -> dict:
        """
        輸入：客戶特徵 dict
        輸出：成功機率 + SHAP 解釋
        """
        X = self.feature_pipeline.transform([customer_features])
        prob = self.model.predict_proba(X)[0][1]
        shap_values = self.explainer.shap_values(X)
        
        # 取 top-5 影響因子
        top_factors = self._get_top_factors(shap_values, customer_features)
        
        return {
            "success_probability": round(prob, 3),
            "confidence": self._get_confidence_level(prob),
            "top_factors": top_factors,
            "risk_factors": self._identify_risks(shap_values, customer_features)
        }
```

---

## 7. 與現有系統的整合方式

### 7.1 部署架構 — LangGraph as Container App

Multi-Agent 系統以獨立 Container App 部署，透過 API 與現有 gpt-rag-ui 串接：

```
gpt-rag-ui (前端)
    │
    ├── /chat  →  gpt-rag-orchestrator (既有 RAG 問答)
    │
    └── /sales →  sales-agent-app (🆕 LangGraph Multi-Agent)
                     ├── Reasoning Agent (Supervisor)
                     ├── Data Agent → Azure SQL DB
                     └── Context RAG Agent → Azure AI Search
```

### 7.2 專案結構

```
sales-agent/                              # 🆕 新專案
├── Dockerfile
├── pyproject.toml
├── azure.yaml
├── src/
│   ├── main.py                           # FastAPI 入口
│   ├── graph.py                          # LangGraph Supervisor 定義
│   ├── agents/
│   │   ├── data_agent.py                 # Data Agent (sql_query + predict_score)
│   │   ├── context_rag_agent.py          # Context RAG Agent (hybrid_search + knowledge)
│   │   └── reasoning_agent.py            # Reasoning Agent (Supervisor)
│   ├── tools/
│   │   ├── sql_query.py                  # Azure SQL DB 查詢
│   │   ├── predict_score.py              # ML 模型預測
│   │   ├── hybrid_search_transcripts.py  # AI Search 通話搜尋
│   │   └── search_sales_knowledge.py     # AI Search 銷售知識搜尋
│   └── config.py                         # 環境設定
├── models/
│   ├── sales_model.pkl                   # 訓練好的 XGBoost 模型
│   └── feature_pipeline.pkl              # 特徵前處理 pipeline
└── tests/
    └── ...
```

### 7.3 與 gpt-rag-ui 串接

gpt-rag-ui 新增「銷售助手」模式，呼叫 sales-agent-app API：

```python
# gpt-rag-ui/orchestrator_client.py 新增
async def get_sales_strategy(customer_id: str) -> dict:
    """呼叫 Sales Agent Multi-Agent 系統"""
    response = await httpx.post(
        f"{SALES_AGENT_URL}/sales/strategy",
        json={"customer_id": customer_id}
    )
    return response.json()
```

### 7.4 App Configuration 新設定

| Key | Value | 說明 |
|-----|-------|------|
| `SALES_AGENT_URL` | `https://sales-agent-app.xxx.azurecontainerapps.io` | LangGraph Agent API |
| `AZURE_SQL_CONNECTION_STRING` | `...` | Azure SQL DB 連線字串 |
| `SALES_MODEL_PATH` | `models/sales_model.pkl` | 模型檔路徑 |
| `SALES_KNOWLEDGE_INDEX` | `sales-knowledge` | 銷售知識庫 AI Search Index |
| `CALL_TRANSCRIPTS_INDEX` | `call-transcripts` | 通話文本 AI Search Index |

### 7.5 串接路徑（未來 — 即時對話整合）

```
                    即時對話串流 (Phase 3 - 未來)
                    ═══════════════════════════

    ┌────────────┐    即時語音    ┌──────────────┐
    │ 電話系統   │ ─── STT ───> │ 對話串流伺服器│
    │ (CTI)      │               │ (WebSocket)   │
    └────────────┘               └──────┬───────┘
                                        │ 每句即時推送
                                        ▼
                                ┌──────────────────────┐
                                │ LangGraph Multi-Agent│
                                │ (同 Phase 2          │
                                │  + 即時分析 Agent)   │
                                └──────┬───────────────┘
                                       │ 動態更新建議
                                       ▼
                                ┌──────────────────┐
                                │ 銷售專員螢幕     │
                                │ (即時建議面板)   │
                                └──────────────────┘
```

---

## 8. 實作路線圖

### Phase 1: 模型訓練與驗證 

| Step | 工作項目 | 產出物 |
|------|----------|--------|
| 1.1 | 資料合併（Persona CSV + 通話 xlsx by customer_id） | 合併 DataFrame |
| 1.2 | 結構化特徵處理 (50 欄位清洗 + 編碼) | Feature matrix |
| 1.3 | LLM 特徵萃取（對 1,100 通話做 batch extraction） | 對話特徵表 |
| 1.4 | 衍生特徵計算 | 完整特徵矩陣 |
| 1.5 | 模型訓練 (XGBoost + CV + HPO) | `sales_model.pkl` |
| 1.6 | SHAP 分析 + 特徵重要度報告 | 分析報告 |
| 1.7 | 銷售知識庫建構（從成功/失敗通話萃取話術） | 知識庫文件 |

### Phase 2: Multi-Agent Sales System MVP

| Step | 工作項目 | 產出物 |
|------|----------|--------|
| 2.1 | Azure SQL DB 建立 + Persona 資料匯入 | `customer_persona` table |
| 2.2 | 通話文本向量化 → Azure AI Search index | `call-transcripts` vector index |
| 2.3 | `sql_query` Tool 實作（含參數化查詢防注入） | `tools/sql_query.py` |
| 2.4 | `predict_score` Tool 實作 | `tools/predict_score.py` |
| 2.5 | `hybrid_search_transcripts` Tool 實作 | `tools/hybrid_search_transcripts.py` |
| 2.6 | `search_sales_knowledge` Tool 實作 | `tools/search_sales_knowledge.py` |
| 2.7 | LangGraph Supervisor 圖定義 | `src/graph.py` |
| 2.8 | FastAPI 服務 + Dockerfile | `src/main.py`, `Dockerfile` |
| 2.9 | Azure AI Search 銷售知識庫索引建立 | `sales-knowledge` index |
| 2.10 | gpt-rag-ui 銷售助手模式整合 | 新頁面或模式切換 |
| 2.11 | 端對端測試 + 效果驗證 | 測試報告 |

### Phase 3: 即時對話整合（未來）

| Step | 工作項目 |
|------|----------|
| 3.1 | CTI / STT 即時串流整合 |
| 3.2 | 對話中即時意圖偵測 |
| 3.3 | 動態建議更新機制 |
| 3.4 | A/B Test 框架 |

---

## 9. 待確認事項

| # | 項目 | 說明 |
|---|------|------|
| 1 | **資料量是否足夠** | 目前 1,100 通（成功 676 / 失敗 424），以傳統 ML 而言堪用，但 LLM 萃取特徵的品質是關鍵 |
| 2 | **Persona CSV 與通話 xlsx 的 join 率** | `unikey3` (Persona) vs `客代` (通話) 的匹配率需確認 |
| 3 | **`rr` 欄位意義** | Persona CSV 的 `rr` 全為 1，需確認是否為另一組標籤或僅為抽樣標記 |
| 4 | **即時 STT 串接方式** | Phase 3 需要的電話系統 API，需與東森確認 |
| 5 | **模型更新頻率** | 新通話資料累積後多久 retrain |
| 6 | **銷售知識庫維護** | 是否有專人持續更新話術/權益內容 |
