#!/usr/bin/env python3
"""
ingest_byrow.py — 將 Blob Storage 中的 Excel 檔案用 by-row 模式重新 ingest 到新的 AI Search Index
=================================================================================================

用途：
  比較 by-sheet (現有 ragindex) 與 by-row (新 ragindex-byrow) 兩種 chunking 策略的回應速度差異。

使用方法：
  1. 確保已用 `az login` 登入 Azure
  2. 執行：
     python scripts/ingest_byrow.py

  3. 在前端聊天視窗中：
     - 預設使用原有 index:  直接提問
     - 切換到 by-row index: 輸入 `/index ragindex-2v3lfktkn4xam-byrow`
     - 切回預設 index:      輸入 `/index reset`

環境變數（可選覆蓋）：
  SEARCH_SERVICE_NAME   - AI Search 服務名稱（預設: srch-2v3lfktkn4xam-gprag）
  SOURCE_INDEX_NAME     - 來源 index（預設: ragindex-2v3lfktkn4xam）
  TARGET_INDEX_NAME     - 目標 by-row index（預設: ragindex-2v3lfktkn4xam-byrow）
  STORAGE_ACCOUNT_NAME  - Storage Account（預設: st2v3lfktkn4xam）
  CONTAINER_NAME        - Blob Container（預設: documents）
  BLOB_PREFIX           - 只處理特定前綴的 blob（預設: 空=全部 xlsx）
  AI_FOUNDRY_ENDPOINT   - Azure AI Foundry endpoint
  EMBEDDING_DEPLOYMENT  - Embedding model deployment name
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import openai
import tiktoken
from azure.identity import AzureCliCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    VectorSearch,
    VectorSearchProfile,
)
from azure.storage.blob import BlobServiceClient
from openpyxl import load_workbook
from tabulate import tabulate

# ============================================================================
# Configuration
# ============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Try to load from App Configuration first, fall back to env vars / defaults
def _load_app_config() -> Dict[str, str]:
    """Try to load config from Azure App Configuration, fall back to empty dict."""
    try:
        from azure.appconfiguration import AzureAppConfigurationClient
        endpoint = os.environ.get("APP_CONFIG_ENDPOINT", "https://appcs-2v3lfktkn4xam-gprag.azconfig.io")
        credential = AzureCliCredential()
        client = AzureAppConfigurationClient(endpoint, credential)
        cfg = {}
        for item in client.list_configuration_settings(label_filter="gpt-rag"):
            cfg[item.key] = item.value
        for item in client.list_configuration_settings(label_filter="\0"):  # no label
            if item.key not in cfg:
                cfg[item.key] = item.value
        logger.info(f"Loaded {len(cfg)} settings from App Configuration")
        return cfg
    except Exception as e:
        logger.warning(f"Could not load App Configuration: {e}. Using env vars only.")
        return {}


APP_CFG = _load_app_config()


def cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, APP_CFG.get(key, default))


SEARCH_SERVICE_NAME = cfg("SEARCH_SERVICE_NAME", "srch-2v3lfktkn4xam-gprag")
SEARCH_ENDPOINT = f"https://{SEARCH_SERVICE_NAME}.search.windows.net"
SOURCE_INDEX = cfg("SEARCH_RAG_INDEX_NAME", "ragindex")
TARGET_INDEX = os.environ.get("TARGET_INDEX_NAME", f"{SOURCE_INDEX}-byrow")
STORAGE_ACCOUNT = cfg("STORAGE_ACCOUNT_NAME", "st2v3lfktkn4xam")
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", cfg("DOCUMENTS_STORAGE_CONTAINER", "documents"))
BLOB_PREFIX = os.environ.get("BLOB_PREFIX", "")
# Filter: only process blobs whose name contains this substring (empty = all)
BLOB_FILTER = os.environ.get("BLOB_FILTER", "時程表")

AI_FOUNDRY_ENDPOINT = cfg("AI_FOUNDRY_ACCOUNT_ENDPOINT", "")
EMBEDDING_DEPLOYMENT = cfg("EMBEDDING_DEPLOYMENT_NAME", "")
EMBEDDING_DIMENSIONS = int(cfg("EMBEDDINGS_VECTOR_DIMENSIONS", "3072"))

CREDENTIAL = AzureCliCredential()


# ============================================================================
# Embedding Client
# ============================================================================
class EmbeddingClient:
    def __init__(self):
        from azure.identity import get_bearer_token_provider
        token_provider = get_bearer_token_provider(
            CREDENTIAL, "https://cognitiveservices.azure.com/.default"
        )
        self.client = openai.AzureOpenAI(
            azure_endpoint=AI_FOUNDRY_ENDPOINT,
            api_version="2024-10-21",
            azure_ad_token_provider=token_provider,
        )
        self.deployment = EMBEDDING_DEPLOYMENT
        self.estimator = tiktoken.encoding_for_model("text-embedding-3-large")
        self.max_tokens = 8192

    def get_embeddings(self, text: str) -> List[float]:
        tokens = self.estimator.encode(text)
        if len(tokens) > self.max_tokens:
            text = self.estimator.decode(tokens[: self.max_tokens])
        resp = self.client.embeddings.create(model=self.deployment, input=text)
        return resp.data[0].embedding


# ============================================================================
# SpreadsheetChunker (by-row mode only)
# ============================================================================
def chunk_excel_by_row(
    file_bytes: bytes,
    filename: str,
    file_url: str,
    embedding_client: EmbeddingClient,
) -> List[Dict[str, Any]]:
    """
    Read an Excel file and produce one chunk per non-empty row, with header included.
    Returns list of search documents ready for upload.
    """
    wb = load_workbook(BytesIO(file_bytes), data_only=True)
    chunks: List[Dict[str, Any]] = []
    chunk_id = 0
    filepath = _url_to_filepath(file_url)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        # Row 1 = headers
        headers = [str(cell.value) if cell.value is not None else "" for cell in ws[1]]
        # Check if the first actual data starts at row 2 or row 3
        # (some sheets have merged title in row 1, real headers in row 2)
        # Heuristic: if more than half of row 2 values look like column headers, use row 2
        row2 = [str(cell.value) if cell.value is not None else "" for cell in ws[2]] if ws.max_row >= 2 else []
        
        # For this specific file, row 1 is a merged title, row 2 has actual headers
        # Detect this pattern: if row 1 has mostly empty cells but row 2 doesn't
        non_empty_r1 = sum(1 for h in headers if h.strip())
        non_empty_r2 = sum(1 for h in row2 if h.strip())
        
        if non_empty_r1 <= 2 and non_empty_r2 > 3:
            # Row 1 is a title row, row 2 is the real header
            real_headers = row2
            data_start_row = 3
        else:
            real_headers = headers
            data_start_row = 2

        for row_idx, row in enumerate(ws.iter_rows(min_row=data_start_row), start=1):
            row_data = [str(cell.value) if cell.value is not None else "" for cell in row]
            if not any(cell.strip() for cell in row_data):
                continue

            # Build a markdown table with header + this single row
            table = tabulate([row_data], headers=real_headers, tablefmt="github")
            table = _clean_markdown_table(table)

            title = f"{sheet_name} - Row {row_idx}"
            
            # Generate embedding
            logger.info(f"  Embedding chunk {chunk_id}: {title}")
            content_vector = embedding_client.get_embeddings(table)

            parent_id = _make_parent_id(filepath)
            doc_key = _make_chunk_key(parent_id, chunk_id)

            doc = {
                "id": doc_key,
                "parent_id": parent_id,
                "metadata_storage_path": parent_id,
                "metadata_storage_name": filename,
                "metadata_storage_last_modified": datetime.now(timezone.utc),
                "metadata_security_id": [],
                "chunk_id": chunk_id,
                "content": table[:32766],  # Azure Search field limit
                "imageCaptions": "",
                "page": 0,
                "offset": 0,
                "length": len(table),
                "title": title,
                "category": "",
                "filepath": filepath,
                "url": file_url,
                "summary": "",
                "relatedImages": [],
                "relatedFiles": [],
                "source": "blob",
                "contentVector": content_vector,
                "captionVector": [0.0] * EMBEDDING_DIMENSIONS,
            }
            chunks.append(doc)
            chunk_id += 1

    logger.info(f"Generated {len(chunks)} by-row chunks from {filename}")
    return chunks


# ============================================================================
# Helpers
# ============================================================================
def _clean_markdown_table(table_str: str) -> str:
    cleaned_lines = []
    for line in table_str.splitlines():
        if set(line.strip()) <= set("-| +"):
            cleaned_lines.append(line)
            continue
        cells = line.split("|")
        if len(cells) >= 3:
            stripped_cells = [cell.strip() for cell in cells[1:-1]]
            cleaned_line = "| " + " | ".join(stripped_cells) + " |"
            cleaned_lines.append(cleaned_line)
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _url_to_filepath(url: str) -> str:
    """Extract filepath from blob URL."""
    # https://st.blob.core.windows.net/documents/path/file.xlsx -> path/file.xlsx
    parts = url.split("/")
    try:
        container_idx = parts.index("documents")
        return "/".join(parts[container_idx + 1 :])
    except ValueError:
        # fallback: everything after the container
        if len(parts) > 4:
            return "/".join(parts[4:])
        return os.path.basename(url)


def _make_parent_id(filepath: str) -> str:
    return filepath


def _make_chunk_key(parent_id: str, chunk_id: int) -> str:
    # Azure Search keys cannot start with underscore or contain special chars
    # Use hash of parent_id for stable, safe keys
    hash_prefix = hashlib.md5(parent_id.encode("utf-8")).hexdigest()[:12]
    return f"byrow_{hash_prefix}_chunk{chunk_id}"


# ============================================================================
# Azure Search Index Management
# ============================================================================
def ensure_target_index(index_client: SearchIndexClient, target_name: str, source_name: str):
    """
    Create the target index with the same schema as the source index
    (or create from scratch if source doesn't exist).
    """
    try:
        existing = index_client.get_index(target_name)
        logger.info(f"Target index '{target_name}' already exists ({len(existing.fields)} fields)")
        return
    except Exception:
        pass  # Need to create

    # Try to clone from source
    try:
        source_idx = index_client.get_index(source_name)
        logger.info(f"Cloning schema from '{source_name}' -> '{target_name}'")
        source_idx.name = target_name
        index_client.create_index(source_idx)
        logger.info(f"Created index '{target_name}' (cloned from '{source_name}')")
        return
    except Exception as e:
        logger.warning(f"Could not clone from source: {e}. Creating from scratch.")

    # Create from scratch
    fields = [
        SearchField(name="id", type=SearchFieldDataType.String, key=True, searchable=True, filterable=True, analyzer_name="keyword"),
        SearchField(name="parent_id", type=SearchFieldDataType.String, searchable=False, retrievable=True),
        SearchField(name="metadata_storage_path", type=SearchFieldDataType.String, searchable=False, retrievable=True),
        SearchField(name="metadata_storage_name", type=SearchFieldDataType.String, searchable=False, retrievable=True),
        SearchField(name="metadata_storage_last_modified", type=SearchFieldDataType.DateTimeOffset, searchable=False, retrievable=True, sortable=True, filterable=True),
        SearchField(name="metadata_security_id", type="Collection(Edm.String)", searchable=False, retrievable=True, filterable=True),
        SearchField(name="chunk_id", type=SearchFieldDataType.Int32, searchable=False, retrievable=True),
        SearchField(name="content", type=SearchFieldDataType.String, searchable=True, retrievable=True, analyzer_name="standard.lucene"),
        SearchField(name="imageCaptions", type=SearchFieldDataType.String, searchable=True, retrievable=True, analyzer_name="standard.lucene"),
        SearchField(name="page", type=SearchFieldDataType.Int32, searchable=False, retrievable=True),
        SearchField(name="offset", type=SearchFieldDataType.Int64, searchable=False, retrievable=True),
        SearchField(name="length", type=SearchFieldDataType.Int32, searchable=False, retrievable=True),
        SearchField(name="title", type=SearchFieldDataType.String, searchable=True, retrievable=True, filterable=True, analyzer_name="standard.lucene"),
        SearchField(name="category", type=SearchFieldDataType.String, searchable=True, retrievable=True, filterable=True, analyzer_name="standard.lucene"),
        SearchField(name="filepath", type=SearchFieldDataType.String, searchable=True, retrievable=True, filterable=True, analyzer_name="standard"),
        SearchField(name="url", type=SearchFieldDataType.String, searchable=False, retrievable=True),
        SearchField(name="summary", type=SearchFieldDataType.String, searchable=True, retrievable=True),
        SearchField(name="relatedImages", type="Collection(Edm.String)", searchable=False, retrievable=True),
        SearchField(name="relatedFiles", type="Collection(Edm.String)", searchable=False, retrievable=True),
        SearchField(name="source", type=SearchFieldDataType.String, searchable=False, retrievable=True, filterable=True),
        SearchField(
            name="contentVector", type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True, retrievable=True, vector_search_dimensions=EMBEDDING_DIMENSIONS, vector_search_profile_name="default"
        ),
        SearchField(
            name="captionVector", type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True, retrievable=True, vector_search_dimensions=EMBEDDING_DIMENSIONS, vector_search_profile_name="default"
        ),
    ]

    vector_search = VectorSearch(
        profiles=[VectorSearchProfile(name="default", algorithm_configuration_name="hnsw")],
        algorithms=[
            HnswAlgorithmConfiguration(
                name="hnsw",
                parameters=HnswParameters(m=4, ef_construction=400, ef_search=500, metric="cosine"),
            )
        ],
    )

    semantic_config = SemanticConfiguration(
        name="semantic-config",
        prioritized_fields=SemanticPrioritizedFields(
            content_fields=[SemanticField(field_name="content"), SemanticField(field_name="imageCaptions")],
            keywords_fields=[SemanticField(field_name="category")],
        ),
    )
    semantic_search = SemanticSearch(configurations=[semantic_config])

    index = SearchIndex(
        name=target_name,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search,
    )
    index_client.create_index(index)
    logger.info(f"Created index '{target_name}' from scratch")


# ============================================================================
# Main
# ============================================================================
def main():
    logger.info("=" * 60)
    logger.info("  ingest_byrow.py — Excel by-row re-ingestion script")
    logger.info("=" * 60)
    logger.info(f"  Search Service:  {SEARCH_SERVICE_NAME}")
    logger.info(f"  Source Index:     {SOURCE_INDEX}")
    logger.info(f"  Target Index:    {TARGET_INDEX}")
    logger.info(f"  Storage Account: {STORAGE_ACCOUNT}")
    logger.info(f"  Container:       {CONTAINER_NAME}")
    logger.info(f"  Blob Prefix:     {BLOB_PREFIX or '(all)'}")
    logger.info(f"  Blob Filter:     {BLOB_FILTER or '(all)'}")
    logger.info(f"  Embedding Dims:  {EMBEDDING_DIMENSIONS}")
    logger.info(f"  AI Foundry:      {AI_FOUNDRY_ENDPOINT}")
    logger.info(f"  Embedding Model: {EMBEDDING_DEPLOYMENT}")
    logger.info("")

    if not AI_FOUNDRY_ENDPOINT or not EMBEDDING_DEPLOYMENT:
        logger.error("AI_FOUNDRY_ACCOUNT_ENDPOINT and EMBEDDING_DEPLOYMENT_NAME must be set!")
        logger.error("These are needed to generate embeddings for the new chunks.")
        logger.error("They should be auto-loaded from App Configuration.")
        sys.exit(1)

    # Initialize clients
    embedding_client = EmbeddingClient()
    blob_service = BlobServiceClient(
        f"https://{STORAGE_ACCOUNT}.blob.core.windows.net", credential=CREDENTIAL
    )
    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=CREDENTIAL)

    # Step 1: Ensure target index exists
    logger.info("[Step 1] Ensuring target index exists...")
    ensure_target_index(index_client, TARGET_INDEX, SOURCE_INDEX)

    # Step 2: Find Excel files in blob storage
    logger.info("[Step 2] Scanning blob storage for Excel files...")
    container_client = blob_service.get_container_client(CONTAINER_NAME)
    xlsx_blobs = []
    for blob in container_client.list_blobs(name_starts_with=BLOB_PREFIX):
        name_lower = blob.name.lower()
        if name_lower.endswith(".xlsx") or name_lower.endswith(".xls"):
            if BLOB_FILTER and BLOB_FILTER not in blob.name:
                logger.info(f"  Skipped (filter): {blob.name}")
                continue
            xlsx_blobs.append(blob)
            logger.info(f"  Found: {blob.name} ({blob.size} bytes)")

    if not xlsx_blobs:
        logger.warning("No Excel files found in blob storage!")
        return

    # Step 3: Process each Excel file
    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT, index_name=TARGET_INDEX, credential=CREDENTIAL
    )

    total_chunks = 0
    for blob in xlsx_blobs:
        logger.info(f"\n[Step 3] Processing: {blob.name}")
        blob_client = container_client.get_blob_client(blob.name)

        # Download
        file_bytes = blob_client.download_blob().readall()
        file_url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER_NAME}/{blob.name}"
        filename = os.path.basename(blob.name)

        # Chunk by row
        docs = chunk_excel_by_row(file_bytes, filename, file_url, embedding_client)

        if not docs:
            logger.warning(f"  No chunks generated for {filename}")
            continue

        # Delete existing chunks for this file in target index
        parent_id = _make_parent_id(_url_to_filepath(file_url))
        try:
            # Find and delete existing docs with same parent_id
            results = search_client.search(
                search_text="*",
                filter=f"parent_id eq '{parent_id}'",
                select=["id"],
                top=1000,
            )
            existing_ids = [r["id"] for r in results]
            if existing_ids:
                logger.info(f"  Deleting {len(existing_ids)} existing chunks for {filename}")
                search_client.delete_documents([{"id": doc_id} for doc_id in existing_ids])
                time.sleep(1)  # Brief pause for consistency
        except Exception as e:
            logger.warning(f"  Could not clean existing chunks: {e}")

        # Upload new chunks in batches
        batch_size = 100
        for i in range(0, len(docs), batch_size):
            batch = docs[i : i + batch_size]
            logger.info(f"  Uploading batch {i // batch_size + 1} ({len(batch)} docs)...")
            result = search_client.upload_documents(batch)
            succeeded = sum(1 for r in result if r.succeeded)
            failed = sum(1 for r in result if not r.succeeded)
            logger.info(f"  Batch result: {succeeded} succeeded, {failed} failed")
            if failed > 0:
                for r in result:
                    if not r.succeeded:
                        logger.error(f"    Failed: {r.key} - {r.error_message}")

        total_chunks += len(docs)

    logger.info("\n" + "=" * 60)
    logger.info(f"  Done! Total chunks uploaded: {total_chunks}")
    logger.info(f"  Target index: {TARGET_INDEX}")
    logger.info("")
    logger.info("  To test in frontend:")
    logger.info(f"    /index {TARGET_INDEX}    ← switch to by-row index")
    logger.info(f"    /index reset             ← switch back to default")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
