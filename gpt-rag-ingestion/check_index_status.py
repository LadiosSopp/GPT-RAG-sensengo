#!/usr/bin/env python3
"""
Check Index Status - 檢查檔案是否已被加入 AI Search Index

Usage:
    python check_index_status.py <APP_CONFIG_ENDPOINT> [filename]

Examples:
    # 列出所有已索引的檔案
    python check_index_status.py https://appcs-xxxxx.azconfig.io
    
    # 搜尋特定檔案
    python check_index_status.py https://appcs-xxxxx.azconfig.io myfile.pdf
"""
import asyncio
import logging
import os
import sys
from typing import Dict, Set, List
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

for name in ["azure.core.pipeline.policies.http_logging_policy", "azure.identity"]:
    logging.getLogger(name).setLevel(logging.WARNING)


async def check_index_status(app_config_endpoint: str, search_filename: str = None):
    """Check index status and list indexed files."""
    
    from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential, ChainedTokenCredential
    from azure.appconfiguration.aio import AzureAppConfigurationClient
    from azure.storage.blob.aio import BlobServiceClient
    from azure.search.documents.aio import SearchClient
    
    credential = ChainedTokenCredential(
        ManagedIdentityCredential(),
        AzureCliCredential()
    )
    
    # Load config
    logging.info(f"Connecting to App Configuration...")
    async with AzureAppConfigurationClient(app_config_endpoint, credential) as config_client:
        config: Dict[str, str] = {}
        async for setting in config_client.list_configuration_settings(label_filter="gpt-rag"):
            config[setting.key] = setting.value
        async for setting in config_client.list_configuration_settings(label_filter="\0"):
            if setting.key not in config:
                config[setting.key] = setting.value
    
    storage_account = config.get("STORAGE_ACCOUNT_NAME")
    source_container = config.get("DOCUMENTS_STORAGE_CONTAINER", "documents")
    search_endpoint = config.get("SEARCH_SERVICE_QUERY_ENDPOINT")
    search_index = config.get("AI_SEARCH_INDEX_NAME") or config.get("SEARCH_RAG_INDEX_NAME", "ragindex")
    
    print("\n" + "=" * 70)
    print("📊 INDEX STATUS CHECK")
    print("=" * 70)
    print(f"Storage Account : {storage_account}")
    print(f"Container       : {source_container}")
    print(f"Search Index    : {search_index}")
    print("=" * 70 + "\n")
    
    # Connect to Blob Storage
    blob_url = f"https://{storage_account}.blob.core.windows.net"
    blob_service = BlobServiceClient(blob_url, credential=credential)
    container_client = blob_service.get_container_client(source_container)
    
    # Get blobs in storage
    print("📁 FILES IN BLOB STORAGE:")
    print("-" * 50)
    blobs_in_storage: Dict[str, dict] = {}
    try:
        async for blob in container_client.list_blobs():
            if getattr(blob, "size", None) == 0 and blob.name.endswith("/"):
                continue
            blobs_in_storage[blob.name] = {
                "size": blob.size,
                "last_modified": blob.last_modified,
            }
    except Exception as e:
        print(f"  ⚠️ Error listing blobs: {e}")
    
    if not blobs_in_storage:
        print("  (empty - no files in container)")
    else:
        for name, info in sorted(blobs_in_storage.items()):
            size_kb = info['size'] / 1024
            print(f"  📄 {name}")
            print(f"     Size: {size_kb:.1f} KB | Modified: {info['last_modified']}")
    
    print(f"\n  Total: {len(blobs_in_storage)} file(s)\n")
    
    # Connect to Search Index
    search_client = SearchClient(search_endpoint, search_index, credential=credential)
    
    # Get indexed documents
    print("🔎 FILES IN SEARCH INDEX:")
    print("-" * 50)
    
    indexed_files: Dict[str, List[dict]] = defaultdict(list)
    total_chunks = 0
    
    try:
        # Search with pagination
        skip = 0
        page_size = 1000
        
        while True:
            results = await search_client.search(
                search_text="*",
                select=["id", "parent_id", "metadata_storage_name", "metadata_storage_last_modified", "chunk_id"],
                top=page_size,
                skip=skip,
            )
            
            batch_count = 0
            async for doc in results:
                batch_count += 1
                total_chunks += 1
                
                parent_id = doc.get("parent_id", "")
                filename = doc.get("metadata_storage_name", parent_id.split("/")[-1] if parent_id else "unknown")
                
                indexed_files[filename].append({
                    "id": doc.get("id"),
                    "chunk_id": doc.get("chunk_id", 0),
                    "parent_id": parent_id,
                    "last_modified": doc.get("metadata_storage_last_modified"),
                })
            
            if batch_count < page_size:
                break
            skip += page_size
            
    except Exception as e:
        print(f"  ⚠️ Error querying index: {e}")
    
    if not indexed_files:
        print("  (empty - no documents in index)")
    else:
        for filename, chunks in sorted(indexed_files.items()):
            chunks_count = len(chunks)
            last_mod = chunks[0].get("last_modified", "N/A")
            parent_id = chunks[0].get("parent_id", "")
            
            # 檢查是否符合搜尋條件
            if search_filename and search_filename.lower() not in filename.lower():
                continue
                
            print(f"  ✅ {filename}")
            print(f"     Chunks: {chunks_count} | Parent: {parent_id}")
            print(f"     Last Modified: {last_mod}")
    
    print(f"\n  Total: {len(indexed_files)} file(s), {total_chunks} chunk(s)\n")
    
    # Compare
    print("📋 COMPARISON:")
    print("-" * 50)
    
    blob_names = set(blobs_in_storage.keys())
    index_names = set(indexed_files.keys())
    
    # Files in blob but not in index (pending)
    pending = blob_names - index_names
    if pending:
        print("\n  ⏳ PENDING (in blob, not yet indexed):")
        for name in sorted(pending):
            print(f"     - {name}")
    
    # Files in index but not in blob (orphaned)
    orphaned = index_names - blob_names
    if orphaned:
        print("\n  🗑️ ORPHANED (in index, but blob deleted):")
        for name in sorted(orphaned):
            print(f"     - {name}")
    
    # Files in both (synced)
    synced = blob_names & index_names
    if synced:
        print(f"\n  ✅ SYNCED: {len(synced)} file(s) are indexed and up-to-date")
    
    if not pending and not orphaned:
        print("\n  🎉 Everything is in sync!")
    
    print("\n" + "=" * 70)
    
    await blob_service.close()
    await search_client.close()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python check_index_status.py <APP_CONFIG_ENDPOINT> [filename]")
        print("Example: python check_index_status.py https://appcs-xxxxx.azconfig.io myfile.pdf")
        sys.exit(1)
    
    endpoint = sys.argv[1]
    search_filename = sys.argv[2] if len(sys.argv) > 2 else None
    
    await check_index_status(endpoint, search_filename)


if __name__ == "__main__":
    asyncio.run(main())
