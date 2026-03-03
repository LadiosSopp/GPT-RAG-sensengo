#!/usr/bin/env python3
"""
ingest_hybrid.py — Hybrid chunking: by-sheet + by-row 同時放入同一個 index
=========================================================================

策略：
  每個 Excel sheet 產生：
    1. 一個 by-sheet chunk（完整 markdown 表格 → 適合跨行/聚合查詢）
    2. 多個 by-row chunk（每行一個 → 適合精確查詢）

  Azure AI Search 的 hybrid search 會自然排序：
    - 精確查詢（如"38F完工日期"）→ by-row chunk 排名最高
    - 概括查詢（如"全棟用途分布"）→ by-sheet chunk 排名最高
    - 混合查詢（如"柏成設計負責哪些樓層"）→ 設計師彙整 sheet chunk + 具體行

使用方法：
  python scripts/ingest_hybrid.py

前端切換：
  /index ragindex-hybrid      ← 切換到 hybrid index
  /index reset                ← 切回預設
"""

import hashlib
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional

import openai
import tiktoken
from azure.identity import AzureCliCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.storage.blob import BlobServiceClient
from openpyxl import load_workbook
from tabulate import tabulate

# ============================================================================
# Configuration
# ============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _load_app_config() -> Dict[str, str]:
    try:
        from azure.appconfiguration import AzureAppConfigurationClient
        endpoint = os.environ.get("APP_CONFIG_ENDPOINT", "https://appcs-2v3lfktkn4xam-gprag.azconfig.io")
        credential = AzureCliCredential()
        client = AzureAppConfigurationClient(endpoint, credential)
        cfg = {}
        for item in client.list_configuration_settings(label_filter="gpt-rag"):
            cfg[item.key] = item.value
        for item in client.list_configuration_settings(label_filter="\0"):
            if item.key not in cfg:
                cfg[item.key] = item.value
        logger.info(f"Loaded {len(cfg)} settings from App Configuration")
        return cfg
    except Exception as e:
        logger.warning(f"Could not load App Configuration: {e}")
        return {}


APP_CFG = _load_app_config()


def cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, APP_CFG.get(key, default))


SEARCH_SERVICE_NAME = cfg("SEARCH_SERVICE_NAME", "srch-2v3lfktkn4xam-gprag")
SEARCH_ENDPOINT = f"https://{SEARCH_SERVICE_NAME}.search.windows.net"
SOURCE_INDEX = cfg("SEARCH_RAG_INDEX_NAME", "ragindex")
TARGET_INDEX = os.environ.get("TARGET_INDEX_NAME", "ragindex-hybrid")
STORAGE_ACCOUNT = cfg("STORAGE_ACCOUNT_NAME", "st2v3lfktkn4xam")
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", cfg("DOCUMENTS_STORAGE_CONTAINER", "documents"))
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
# Hybrid Chunker: by-sheet + by-row
# ============================================================================
def chunk_excel_hybrid(
    file_bytes: bytes,
    filename: str,
    file_url: str,
    embedding_client: EmbeddingClient,
) -> List[Dict[str, Any]]:
    """
    Produce BOTH by-sheet and by-row chunks for each sheet.
    
    For each sheet:
      - 1 by-sheet chunk: full markdown table (title = sheet name)
      - N by-row chunks: one per non-empty row (title = "sheet - Row N")
    """
    wb = load_workbook(BytesIO(file_bytes), data_only=True)
    chunks: List[Dict[str, Any]] = []
    chunk_id = 0
    filepath = _url_to_filepath(file_url)
    parent_id = _make_parent_id(filepath)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]

        # Detect header row
        headers_r1 = [str(cell.value) if cell.value is not None else "" for cell in ws[1]]
        headers_r2 = [str(cell.value) if cell.value is not None else "" for cell in ws[2]] if ws.max_row >= 2 else []
        non_empty_r1 = sum(1 for h in headers_r1 if h.strip())
        non_empty_r2 = sum(1 for h in headers_r2 if h.strip())

        if non_empty_r1 <= 2 and non_empty_r2 > 3:
            real_headers = headers_r2
            data_start_row = 3
        else:
            real_headers = headers_r1
            data_start_row = 2

        # Collect all data rows
        all_rows = []
        for row in ws.iter_rows(min_row=data_start_row):
            row_data = [str(cell.value) if cell.value is not None else "" for cell in row]
            if any(cell.strip() for cell in row_data):
                all_rows.append(row_data)

        if not all_rows:
            continue

        # ---- BY-SHEET CHUNK ----
        full_table = tabulate(all_rows, headers=real_headers, tablefmt="grid")
        full_table = _clean_markdown_table(full_table)

        logger.info(f"  [by-sheet] Embedding: {sheet_name} ({len(full_table)} chars)")
        sheet_vector = embedding_client.get_embeddings(full_table)

        sheet_doc = _make_doc(
            chunk_id=chunk_id,
            parent_id=parent_id,
            filename=filename,
            filepath=filepath,
            file_url=file_url,
            content=full_table,
            title=sheet_name,
            content_vector=sheet_vector,
            category="sheet",  # Tag to distinguish
        )
        chunks.append(sheet_doc)
        chunk_id += 1

        # ---- BY-ROW CHUNKS ----
        for row_idx, row_data in enumerate(all_rows, start=1):
            row_table = tabulate([row_data], headers=real_headers, tablefmt="github")
            row_table = _clean_markdown_table(row_table)

            title = f"{sheet_name} - Row {row_idx}"
            logger.info(f"  [by-row]   Embedding chunk {chunk_id}: {title}")
            row_vector = embedding_client.get_embeddings(row_table)

            row_doc = _make_doc(
                chunk_id=chunk_id,
                parent_id=parent_id,
                filename=filename,
                filepath=filepath,
                file_url=file_url,
                content=row_table,
                title=title,
                content_vector=row_vector,
                category="row",
            )
            chunks.append(row_doc)
            chunk_id += 1

    sheet_count = sum(1 for c in chunks if c.get("category") == "sheet")
    row_count = sum(1 for c in chunks if c.get("category") == "row")
    logger.info(f"Generated {len(chunks)} hybrid chunks from {filename} ({sheet_count} sheets + {row_count} rows)")
    return chunks


# ============================================================================
# Helpers
# ============================================================================
def _make_doc(
    chunk_id: int,
    parent_id: str,
    filename: str,
    filepath: str,
    file_url: str,
    content: str,
    title: str,
    content_vector: List[float],
    category: str = "",
) -> Dict[str, Any]:
    doc_key = _make_chunk_key(parent_id, chunk_id)
    return {
        "id": doc_key,
        "parent_id": parent_id,
        "metadata_storage_path": parent_id,
        "metadata_storage_name": filename,
        "metadata_storage_last_modified": datetime.now(timezone.utc),
        "metadata_security_id": [],
        "chunk_id": chunk_id,
        "content": content[:32766],
        "imageCaptions": "",
        "page": 0,
        "offset": 0,
        "length": len(content),
        "title": title,
        "category": category,
        "filepath": filepath,
        "url": file_url,
        "summary": "",
        "relatedImages": [],
        "relatedFiles": [],
        "source": "blob",
        "contentVector": content_vector,
        "captionVector": [0.0] * EMBEDDING_DIMENSIONS,
    }


def _clean_markdown_table(table_str: str) -> str:
    cleaned_lines = []
    for line in table_str.splitlines():
        if set(line.strip()) <= set("-| +:="):
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
    parts = url.split("/")
    try:
        container_idx = parts.index("documents")
        return "/".join(parts[container_idx + 1:])
    except ValueError:
        if len(parts) > 4:
            return "/".join(parts[4:])
        return os.path.basename(url)


def _make_parent_id(filepath: str) -> str:
    return filepath


def _make_chunk_key(parent_id: str, chunk_id: int) -> str:
    hash_prefix = hashlib.md5(parent_id.encode("utf-8")).hexdigest()[:12]
    return f"hybrid_{hash_prefix}_chunk{chunk_id}"


def ensure_target_index(index_client: SearchIndexClient, target_name: str, source_name: str):
    try:
        existing = index_client.get_index(target_name)
        logger.info(f"Target index '{target_name}' already exists ({len(existing.fields)} fields)")
        return
    except Exception:
        pass
    try:
        source_idx = index_client.get_index(source_name)
        source_idx.name = target_name
        index_client.create_index(source_idx)
        logger.info(f"Created index '{target_name}' (cloned from '{source_name}')")
    except Exception as e:
        logger.error(f"Failed to create index: {e}")
        raise


# ============================================================================
# Main
# ============================================================================
def main():
    logger.info("=" * 60)
    logger.info("  ingest_hybrid.py — Hybrid (by-sheet + by-row) ingestion")
    logger.info("=" * 60)
    logger.info(f"  Target Index:    {TARGET_INDEX}")
    logger.info(f"  Source Index:    {SOURCE_INDEX}")
    logger.info(f"  Blob Filter:    {BLOB_FILTER or '(all)'}")
    logger.info("")

    if not AI_FOUNDRY_ENDPOINT or not EMBEDDING_DEPLOYMENT:
        logger.error("AI_FOUNDRY_ACCOUNT_ENDPOINT and EMBEDDING_DEPLOYMENT_NAME must be set!")
        sys.exit(1)

    embedding_client = EmbeddingClient()
    blob_service = BlobServiceClient(
        f"https://{STORAGE_ACCOUNT}.blob.core.windows.net", credential=CREDENTIAL
    )
    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=CREDENTIAL)

    # Step 1: Ensure index
    logger.info("[Step 1] Ensuring target index...")
    ensure_target_index(index_client, TARGET_INDEX, SOURCE_INDEX)

    # Step 2: Find Excel files
    logger.info("[Step 2] Scanning blob storage...")
    container_client = blob_service.get_container_client(CONTAINER_NAME)
    xlsx_blobs = []
    for blob in container_client.list_blobs():
        name_lower = blob.name.lower()
        if name_lower.endswith(".xlsx") or name_lower.endswith(".xls"):
            if BLOB_FILTER and BLOB_FILTER not in blob.name:
                continue
            xlsx_blobs.append(blob)
            logger.info(f"  Found: {blob.name}")

    if not xlsx_blobs:
        logger.warning("No matching Excel files found!")
        return

    # Step 3: Process
    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT, index_name=TARGET_INDEX, credential=CREDENTIAL
    )
    total_chunks = 0
    total_sheets = 0
    total_rows = 0

    for blob in xlsx_blobs:
        logger.info(f"\n[Step 3] Processing: {blob.name}")
        blob_client = container_client.get_blob_client(blob.name)
        file_bytes = blob_client.download_blob().readall()
        file_url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER_NAME}/{blob.name}"
        filename = os.path.basename(blob.name)

        docs = chunk_excel_hybrid(file_bytes, filename, file_url, embedding_client)
        if not docs:
            continue

        # Clean existing chunks for this file
        parent_id = _make_parent_id(_url_to_filepath(file_url))
        try:
            results = search_client.search(
                search_text="*", filter=f"parent_id eq '{parent_id}'",
                select=["id"], top=1000,
            )
            existing_ids = [r["id"] for r in results]
            if existing_ids:
                logger.info(f"  Deleting {len(existing_ids)} existing chunks")
                search_client.delete_documents([{"id": doc_id} for doc_id in existing_ids])
                time.sleep(1)
        except Exception as e:
            logger.warning(f"  Could not clean existing chunks: {e}")

        # Upload
        batch_size = 100
        for i in range(0, len(docs), batch_size):
            batch = docs[i: i + batch_size]
            logger.info(f"  Uploading batch ({len(batch)} docs)...")
            result = search_client.upload_documents(batch)
            ok = sum(1 for r in result if r.succeeded)
            fail = sum(1 for r in result if not r.succeeded)
            logger.info(f"  Result: {ok} ok, {fail} failed")
            for r in result:
                if not r.succeeded:
                    logger.error(f"    Failed: {r.key} - {r.error_message}")

        s = sum(1 for d in docs if d.get("category") == "sheet")
        r = sum(1 for d in docs if d.get("category") == "row")
        total_chunks += len(docs)
        total_sheets += s
        total_rows += r

    logger.info("\n" + "=" * 60)
    logger.info(f"  Done! Total: {total_chunks} chunks ({total_sheets} sheets + {total_rows} rows)")
    logger.info(f"  Index: {TARGET_INDEX}")
    logger.info(f"")
    logger.info(f"  /index {TARGET_INDEX}    <- switch to hybrid")
    logger.info(f"  /index reset             <- switch back")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
