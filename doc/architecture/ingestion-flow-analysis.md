# GPT-RAG Ingestion 流程分析與效能調整指南

## 📋 概覽

本文檔分析 `gpt-rag-ingestion` 服務的函數呼叫流程，包括各函數的用途、輸入輸出定義、呼叫順序，以及可調整的效能參數。

---

## 🔄 主要流程 (Main Flow)

### 1. 啟動順序

```
main.py (FastAPI lifespan)
    │
    ├── _ensure_auth_or_exit()     # 驗證認證
    ├── get_config()               # 載入 App Configuration
    ├── Telemetry.configure_monitoring()  # 設定監控
    ├── scheduler.start()          # 啟動排程器
    │
    └── 排程任務 (Cron Jobs)
        ├── run_blob_index()       # Blob Storage 索引
        ├── run_blob_purge()       # Blob Storage 清理
        ├── run_sharepoint_index() # SharePoint 索引
        ├── run_sharepoint_purge() # SharePoint 清理
        ├── run_nl2sql_index()     # NL2SQL 索引
        ├── run_nl2sql_purge()     # NL2SQL 清理
        └── run_images_purge()     # 圖片清理
```

---

## 📂 核心模組結構

```
gpt-rag-ingestion/
├── main.py                    # FastAPI 入口
├── jobs/                      # 排程任務
│   ├── blob_storage_indexer.py   # 🔑 主要索引器
│   ├── sharepoint_indexer.py
│   ├── nl2sql_indexer.py
│   └── *_purger.py
├── chunking/                  # 文檔切分
│   ├── document_chunking.py      # 切分入口
│   ├── chunker_factory.py        # Chunker 工廠
│   └── chunkers/                 # 各種 Chunker
│       ├── base_chunker.py
│       ├── doc_analysis_chunker.py   # 🔑 Document Intelligence
│       ├── multimodal_chunker.py     # 多模態 (圖片處理)
│       ├── langchain_chunker.py      # 純文字
│       ├── spreadsheet_chunker.py    # Excel
│       └── json_chunker.py           # JSON
└── tools/                     # Azure 服務客戶端
    ├── doc_intelligence.py       # Document Intelligence API
    ├── aoai.py                   # Azure OpenAI (Embeddings)
    ├── aisearch.py               # AI Search
    └── blob.py                   # Blob Storage
```

---

## 🔍 Blob Storage Indexer 詳細流程

### 類別: `BlobStorageDocumentIndexer`

#### `run()` - 主入口

```python
async def run(self) -> None
```

| 項目 | 說明 |
|------|------|
| **輸入** | 無 (從 App Configuration 讀取設定) |
| **輸出** | 無 (結果寫入 AI Search 和 Log Container) |
| **呼叫順序** | 見下方流程 |

**執行流程:**
```
run()
│
├── 1. _ensure_clients()           # 初始化 Azure 客戶端
│
├── 2. _load_latest_index_state()  # 載入現有索引狀態 (dedup)
│       └── 返回: Dict[parent_id, last_modified]
│
├── 3. 列舉 Blob Container
│       └── 比對 last_modified 決定是否需重新索引
│
├── 4. _gather_limited()           # 並行處理 (max_concurrency)
│       └── _process_one()         # 處理單一文件
│
└── 5. _write_run_summary()        # 寫入執行摘要
```

#### `_process_one()` - 處理單一文件

```python
async def _process_one(
    self,
    blob_name: str,         # Blob 路徑
    last_modified: datetime, # 最後修改時間
    content_type: str,      # MIME 類型
    run_id: str             # 執行批次 ID
) -> Dict[str, Any]         # {"status": "success/error", "chunks": int}
```

**執行流程:**
```
_process_one()
│
├── 1. blob_client.get_blob_properties()  # 取得 metadata
│
├── 2. blob_client.download_blob()        # 下載文件內容
│
├── 3. DocumentChunker().chunk_documents(data)  # 🔑 核心切分
│       │
│       ├── ChunkerFactory().get_chunker(data)
│       │       │
│       │       └── 依據副檔名選擇 Chunker:
│       │           ├── pdf/png/jpg... → DocAnalysisChunker / MultimodalChunker
│       │           ├── docx/pptx → DocAnalysisChunker (需 DocInt 4.0)
│       │           ├── xlsx/xls → SpreadsheetChunker
│       │           ├── vtt → TranscriptionChunker
│       │           ├── json → JSONChunker
│       │           └── md/txt/html/py → LangChainChunker
│       │
│       └── chunker.get_chunks()
│
├── 4. _to_search_doc()                   # 轉換為 Search 文檔格式
│
└── 5. _replace_parent_docs()             # 上傳到 AI Search
        ├── _delete_parent_docs()         # 刪除舊 chunks
        └── _upload_in_batches()          # 批次上傳新 chunks
```

---

## 📄 Document Chunking 詳細流程

### 類別: `DocumentChunker`

```python
def chunk_documents(self, data: dict) -> Tuple[list, list, list]
```

| 項目 | 說明 |
|------|------|
| **輸入** | `data` dict 包含 `documentUrl`, `documentBytes`, `documentContentType`, `fileName` |
| **輸出** | `(chunks, errors, warnings)` |

---

### 類別: `ChunkerFactory`

```python
def get_chunker(self, data: dict) -> BaseChunker
```

**Chunker 選擇邏輯:**

| 副檔名 | Chunker | 說明 |
|--------|---------|------|
| `pdf`, `png`, `jpg`, `jpeg`, `bmp`, `tiff` | `DocAnalysisChunker` 或 `MultimodalChunker` | 依 MULTIMODAL 設定 |
| `docx`, `pptx` | `DocAnalysisChunker` | 需 Document Intelligence 4.0 |
| `xlsx`, `xls` | `SpreadsheetChunker` | Excel 專用 |
| `vtt` | `TranscriptionChunker` | 字幕/轉錄檔 |
| `json` | `JSONChunker` | JSON 結構化資料 |
| `md`, `txt`, `html`, `py`, `csv`, `xml` | `LangChainChunker` | 純文字類 |
| `nl2sql` | `NL2SQLChunker` | 自然語言轉 SQL |

---

### 類別: `DocAnalysisChunker` (核心)

**流程:**
```
get_chunks()
│
├── 1. _analyze_document_with_retry()     # 呼叫 Document Intelligence
│       └── docint_client.analyze_document_from_bytes()
│           │
│           ├── POST /documentintelligence/documentModels/prebuilt-layout:analyze
│           │   Body: {"base64Source": <base64_encoded_bytes>}
│           │
│           └── Polling loop until status == "succeeded"
│               └── 返回: {"content": <markdown>, "figures": [...]}
│
├── 2. _number_pagebreaks()               # 標記頁碼
│
├── 3. _chunk_content()                   # 切分內容
│       │
│       ├── _choose_splitter()
│       │   ├── Markdown → MarkdownTextSplitter
│       │   └── 其他 → RecursiveCharacterTextSplitter
│       │
│       └── splitter.split_text(content)
│           └── yield (chunk_text, token_count)
│
└── 4. _create_chunk() (for each chunk)   # 建立 chunk 物件
        │
        └── aoai_client.get_embeddings()  # 🔑 生成向量
            └── POST /openai/deployments/{model}/embeddings
```

---

### 類別: `BaseChunker._create_chunk()`

```python
def _create_chunk(
    self,
    chunk_id: int,          # 序號
    content: str,           # 內容文字
    summary: str = "",      # 摘要
    embedding_text: str = "",  # 用於生成向量的文字
    title: str = "",        # 標題
    page: int = 0,          # 頁碼
    offset: int = 0,        # 位置偏移
    related_images: list = None,  # 相關圖片
    related_files: list = None    # 相關文件
) -> dict
```

**輸出結構:**
```python
{
    "chunk_id": int,
    "url": str,              # 原始文件 URL
    "filepath": str,         # 文件路徑
    "content": str,          # 內容 (max 32766 bytes)
    "summary": str,
    "contentVector": list,   # Embedding 向量 (3072 維)
    "captionVector": list,   # 標題向量
    "title": str,
    "page": int,
    "offset": int,
    "length": int,
    "relatedImages": list,
    "relatedFiles": list
}
```

---

## ⚙️ 可調整的效能參數

### 🎯 高影響參數 (建議優先調整)

| 參數 | 預設值 | 說明 | 效能影響 |
|------|--------|------|----------|
| **`CHUNKING_NUM_TOKENS`** | `2048` | 每個 chunk 的最大 token 數 | ⬆️ 較大 = 較少 chunks、較少 embedding 呼叫、但檢索精度可能下降 |
| **`CHUNKING_MIN_CHUNK_SIZE`** | `100` | 最小 chunk 大小 (小於此值會被跳過) | 過小會產生無意義的 chunks |
| **`TOKEN_OVERLAP`** | `100` | chunk 之間的重疊 token 數 | ⬆️ 較大 = 更好的上下文連續性、但更多冗餘 |
| **`INDEXER_MAX_CONCURRENCY`** | `8` | 並行處理文件數 | ⬆️ 較大 = 更快、但可能觸發 rate limit |
| **`INDEXER_BATCH_SIZE`** | `500` | AI Search 批次上傳大小 | Azure 建議 500-1000 |

### 📊 Document Intelligence 參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| **`DOC_INTELLIGENCE_API_VERSION`** | `2024-11-30` | API 版本 (4.0+ 支援 docx/pptx) |
| **`MULTIMODAL`** | `false` | 啟用圖片處理 (MultimodalChunker) |
| **`MINIMUM_FIGURE_AREA_PERCENTAGE`** | `4.0` | 圖片最小面積百分比 (低於此值忽略) |

### 🔢 Embedding 參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| **`EMBEDDINGS_VECTOR_DIMENSIONS`** | `3072` | 向量維度 (text-embedding-3-large) |
| **`EMBEDDING_DEPLOYMENT_NAME`** | - | Azure OpenAI embedding 模型部署名稱 |

### 📁 Storage 參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| **`DOCUMENTS_STORAGE_CONTAINER`** | `documents` | 文檔來源 container |
| **`BLOB_PREFIX`** | `""` | 只處理特定前綴的 blobs |
| **`JOBS_LOG_CONTAINER`** | `jobs` | 執行日誌 container |

---

## 🚀 效能調整建議

### 1. Chunking 策略優化

| 場景 | 建議設定 | 原因 |
|------|----------|------|
| **長文檔、需要完整上下文** | `CHUNKING_NUM_TOKENS=4096`, `TOKEN_OVERLAP=200` | 減少 chunk 數量、保持上下文 |
| **短問答、高精度需求** | `CHUNKING_NUM_TOKENS=1024`, `TOKEN_OVERLAP=50` | 更細粒度、更精確的檢索 |
| **混合文檔** | 保持預設 `2048/100` | 平衡策略 |

### 2. 並行處理優化

```python
# 建議根據 Document Intelligence 和 OpenAI 的 rate limit 調整
INDEXER_MAX_CONCURRENCY = 8    # 預設 (安全)
INDEXER_MAX_CONCURRENCY = 16   # 高 throughput (需監控 429 錯誤)
INDEXER_MAX_CONCURRENCY = 4    # 低 throughput (rate limit 嚴格時)
```

### 3. 減少 API 呼叫

| 優化項目 | 方法 | 節省 |
|----------|------|------|
| **跳過未變更文件** | 系統已內建 (比對 `last_modified`) | Document Intelligence + Embedding 費用 |
| **增大 chunk 大小** | `CHUNKING_NUM_TOKENS=4096` | Embedding 呼叫次數 -50% |
| **停用小圖片** | `MINIMUM_FIGURE_AREA_PERCENTAGE=10` | 圖片處理費用 |

### 4. 成本 vs 品質權衡

| 優先級 | 設定 | 效果 |
|--------|------|------|
| **成本優先** | 大 chunk、小 overlap | 較少 API 呼叫、可能降低檢索精度 |
| **品質優先** | 小 chunk、大 overlap | 更精確檢索、較高 API 成本 |
| **平衡** | `2048/100` (預設) | 推薦的起始點 |

---

## 🔧 調整範例

### 範例 1: 優化長文檔處理

```env
# App Configuration 設定
CHUNKING_NUM_TOKENS=4096
TOKEN_OVERLAP=200
CHUNKING_MIN_CHUNK_SIZE=200
```

### 範例 2: 高 throughput 批次處理

```env
INDEXER_MAX_CONCURRENCY=16
INDEXER_BATCH_SIZE=1000
```

### 範例 3: 啟用多模態圖片處理

```env
MULTIMODAL=true
MINIMUM_FIGURE_AREA_PERCENTAGE=5.0
DOCUMENTS_IMAGES_STORAGE_CONTAINER=documents-images
```

---

## 📊 監控指標

建議監控以下指標以評估效能:

| 指標 | 來源 | 正常範圍 |
|------|------|----------|
| 每文件處理時間 | Application Insights | < 30 秒 (一般文件) |
| Chunk 數量 / 文件 | Job logs | 10-100 (依文件大小) |
| Embedding API 延遲 | Application Insights | < 500ms |
| 429 Rate Limit 錯誤 | Application Insights | 0 (理想) |
| Document Intelligence 處理時間 | Application Insights | < 60 秒 / 文件 |

---

## 🏢 多租戶 Ingestion 配置 (2026-01-20)

### 配置方式

Ingestion 透過 App Configuration 指定目標容器和索引。

**重要**: 配置項必須使用 `gpt-rag` label！

| 配置項 | 預設值 | 多租戶範例 |
|--------|--------|------------|
| `DOCUMENTS_STORAGE_CONTAINER` | `documents` | `documents-company-a` |
| `SEARCH_RAG_INDEX_NAME` | `ragindex-{token}` | `ragindex-company-a` |

### 配置讀取時機

- 配置在**容器啟動時**從 App Configuration 載入並快取
- 修改配置後**必須重啟容器**才會生效

### 手動觸發 Ingestion 步驟

```powershell
# 1. 更新 App Configuration (注意 --label gpt-rag)
az appconfig kv set --name appcs-{token} --key "DOCUMENTS_STORAGE_CONTAINER" --value "documents-company-a" --label "gpt-rag" --auth-mode login -y
az appconfig kv set --name appcs-{token} --key "SEARCH_RAG_INDEX_NAME" --value "ragindex-company-a" --label "gpt-rag" --auth-mode login -y

# 2. 重啟容器 (建立新 Revision)
az containerapp revision copy --name ca-{token}-dataingest --resource-group rg-{name} --cpu 0.5 --memory 1.0Gi

# 3. 監控執行結果
az containerapp logs show --name ca-{token}-dataingest --resource-group rg-{name} --type console --tail 100 | Select-String "RUN-COMPLETE|sourceContainer"
```

### 驗證 Index 資料

```powershell
$headers = @{"api-key"="{search-admin-key}"; "Content-Type"="application/json"}
$body = '{"search":"*","top":0,"count":true}'
$r = Invoke-RestMethod -Uri "https://srch-{token}.search.windows.net/indexes/ragindex-company-a/docs/search?api-version=2024-07-01" -Headers $headers -Method POST -Body $body
Write-Host "ragindex-company-a: $($r.'@odata.count') chunks"
```

---

## � 大檔案處理效能測試 (2026-01-20)

### 測試環境

- **Container App**: `ca-{token}-dataingest` revision 0000009
- **CRON**: `*/5 * * * *` (每 5 分鐘)
- **APScheduler**: `max_instances=1` (保護機制，避免重複執行)

### 測試結果

| 檔案 | 大小 | 處理時間 | Chunks | 狀態 |
|------|------|----------|--------|------|
| 蔦屋拜訪.pptx | 21 MB | 5.87 秒 | 5 | ✅ 成功 |
| 20241217台灣沉浸式劇場表演.pptx | 25.4 MB | - | - | ✅ 成功 |
| 20241219台灣沉浸式劇場表演 V2-F.pptx | 27.4 MB | - | - | ✅ 成功 |
| 室內高爾夫練習場20250826.pptx | 31.3 MB | 33.61 秒 | 22 | ✅ 成功 |
| 中台拍賣市場分析-20250918-F.pptx | 32.5 MB | 16.54 秒 | 31 | ✅ 成功 |
| 野獸國合作報告_20250124.pptx | 37.9 MB | 12.78 秒 | 6 | ✅ 成功 |
| 世界知名景觀台調查V4.pptx | 41.6 MB | 17.26 秒 | 7 | ✅ 成功 |
| 202508_六大會機器人報告V4.pptx | 44.3 MB | 12.62 秒 | 14 | ✅ 成功 |
| 世界著名大樓20250314.pptx | **95 MB** | >40 分鐘 | - | ⏳ 處理中 |
| 競業商場訪查報告_20250506.pptx | **97 MB** | >40 分鐘 | - | ⏳ 處理中 |

### 關鍵發現

1. **21-44 MB 檔案**: 都能在 5-35 秒內完成處理
2. **95+ MB 檔案**: Document Intelligence 需要非常長的處理時間 (>40 分鐘)
3. **APScheduler 保護機制**: 當前一個 job 仍在執行時，新的 CRON 觸發會被**跳過** (不會重置)
4. **處理時間與 chunks 數量不成正比**: 取決於文件內容複雜度

### 超大檔案處理建議

| 檔案大小 | 建議處理方式 |
|----------|--------------|
| < 50 MB | 正常放入 `documents` 容器 |
| 50-100 MB | 可嘗試，但處理時間可能較長 |
| > 100 MB | 建議分割檔案或使用 `documents-large` 容器隔離 |

### 問題檔案類型

| 問題類型 | 範例 | 解決方案 |
|----------|------|----------|
| Token 超限 Excel | 展演館場地調查2025.xlsx (502K tokens) | 移至 `documents-large` 隔離 |
| 超大 PowerPoint | 95+ MB 檔案 | 考慮分割或隔離 |

---

## �📝 關鍵函數參考表

| 函數 | 位置 | 輸入 | 輸出 | 可調參數 |
|------|------|------|------|----------|
| `BlobStorageDocumentIndexer.run()` | jobs/blob_storage_indexer.py | - | - | `max_concurrency`, `batch_size` |
| `DocumentChunker.chunk_documents()` | chunking/document_chunking.py | data dict | (chunks, errors, warnings) | - |
| `ChunkerFactory.get_chunker()` | chunking/chunker_factory.py | data dict | BaseChunker | `MULTIMODAL` |
| `DocAnalysisChunker.get_chunks()` | chunking/chunkers/doc_analysis_chunker.py | - | list[dict] | `CHUNKING_NUM_TOKENS`, `TOKEN_OVERLAP`, `CHUNKING_MIN_CHUNK_SIZE` |
| `BaseChunker._create_chunk()` | chunking/chunkers/base_chunker.py | chunk 參數 | dict | `EMBEDDINGS_VECTOR_DIMENSIONS` |
| `DocumentIntelligenceClient.analyze_document_from_bytes()` | tools/doc_intelligence.py | file_bytes, filename | (result, errors) | `DOC_INTELLIGENCE_API_VERSION` |
| `AzureOpenAIClient.get_embeddings()` | tools/aoai.py | text | list[float] | `EMBEDDING_DEPLOYMENT_NAME` |
