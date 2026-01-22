#!/usr/bin/env python3
"""
Standalone Blob Storage Purger - cleans up index records for deleted blobs.

Usage:
    python run_purger_standalone.py

Requirements:
    - az login (must be authenticated)
    - APP_CONFIG_ENDPOINT environment variable or pass as argument
"""
import asyncio
import logging
import os
import sys
from typing import Set, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Quiet noisy Azure SDK loggers
for name in ["azure.core.pipeline.policies.http_logging_policy", "azure.identity"]:
    logging.getLogger(name).setLevel(logging.WARNING)


async def run_purger(app_config_endpoint: str):
    """Main purger logic."""
    
    from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential, ChainedTokenCredential
    from azure.appconfiguration.aio import AzureAppConfigurationClient
    from azure.storage.blob.aio import BlobServiceClient
    from azure.search.documents.aio import SearchClient
    
    logging.info("Initializing credentials...")
    credential = ChainedTokenCredential(
        ManagedIdentityCredential(),
        AzureCliCredential()
    )
    
    # Load config from App Configuration
    logging.info(f"Connecting to App Configuration: {app_config_endpoint}")
    async with AzureAppConfigurationClient(app_config_endpoint, credential) as config_client:
        config: Dict[str, str] = {}
        async for setting in config_client.list_configuration_settings(label_filter="gpt-rag"):
            config[setting.key] = setting.value
        
        # Also load settings without label
        async for setting in config_client.list_configuration_settings(label_filter="\0"):
            if setting.key not in config:
                config[setting.key] = setting.value
    
    # Get required settings
    storage_account = config.get("STORAGE_ACCOUNT_NAME")
    source_container = config.get("DOCUMENTS_STORAGE_CONTAINER", "documents")
    search_endpoint = config.get("SEARCH_SERVICE_QUERY_ENDPOINT")
    search_index = config.get("AI_SEARCH_INDEX_NAME") or config.get("SEARCH_RAG_INDEX_NAME", "ragindex")
    
    if not storage_account:
        raise ValueError("STORAGE_ACCOUNT_NAME not found in App Configuration")
    if not search_endpoint:
        raise ValueError("SEARCH_SERVICE_QUERY_ENDPOINT not found in App Configuration")
    
    logging.info(f"Storage Account: {storage_account}")
    logging.info(f"Source Container: {source_container}")
    logging.info(f"Search Endpoint: {search_endpoint}")
    logging.info(f"Search Index: {search_index}")
    
    # Connect to Blob Storage
    blob_url = f"https://{storage_account}.blob.core.windows.net"
    blob_service = BlobServiceClient(blob_url, credential=credential)
    
    # Get existing blobs
    logging.info(f"Scanning blobs in container '{source_container}'...")
    existing: Set[str] = set()
    container_client = blob_service.get_container_client(source_container)
    
    async for blob in container_client.list_blobs():
        if getattr(blob, "size", None) == 0 and blob.name.endswith("/"):
            continue  # Skip folder markers
        parent_id = f"/{source_container}/{blob.name}"
        existing.add(parent_id)
    
    logging.info(f"Found {len(existing)} blobs in storage")
    
    # Connect to Search
    search_client = SearchClient(search_endpoint, search_index, credential=credential)
    
    # Get all parent_ids in index
    logging.info("Scanning index for parent_ids...")
    in_index: Set[str] = set()
    
    try:
        results = await search_client.search(
            search_text="*",
            filter="source eq 'blob'",
            select=["parent_id"],
            top=1000,
        )
        
        async for doc in results:
            pid = doc.get("parent_id")
            if pid:
                in_index.add(pid)
    except Exception as e:
        logging.warning(f"Error scanning index (may be using different filter): {e}")
        # Try without filter
        results = await search_client.search(
            search_text="*",
            select=["parent_id"],
            top=1000,
        )
        async for doc in results:
            pid = doc.get("parent_id")
            if pid:
                in_index.add(pid)
    
    logging.info(f"Found {len(in_index)} unique parent_ids in index")
    
    # Find orphans (in index but not in storage)
    to_purge = sorted(in_index - existing)
    
    if not to_purge:
        logging.info("✅ No orphan records found. Index is clean!")
        await blob_service.close()
        await search_client.close()
        return
    
    logging.info(f"🗑️ Found {len(to_purge)} orphan parent_ids to purge:")
    for pid in to_purge[:10]:  # Show first 10
        logging.info(f"   - {pid}")
    if len(to_purge) > 10:
        logging.info(f"   ... and {len(to_purge) - 10} more")
    
    # Delete orphan documents
    total_deleted = 0
    for parent_id in to_purge:
        logging.info(f"Deleting documents for: {parent_id}")
        try:
            # Search for all chunks with this parent_id
            chunks = await search_client.search(
                search_text="*",
                filter=f"parent_id eq '{parent_id}'",
                select=["id"],
                top=1000,
            )
            
            doc_ids = []
            async for chunk in chunks:
                doc_ids.append({"id": chunk["id"]})
            
            if doc_ids:
                await search_client.delete_documents(doc_ids)
                total_deleted += len(doc_ids)
                logging.info(f"   Deleted {len(doc_ids)} chunks")
        except Exception as e:
            logging.error(f"   Error deleting {parent_id}: {e}")
    
    logging.info(f"✅ Purge complete! Deleted {total_deleted} total documents from index")
    
    await blob_service.close()
    await search_client.close()


async def main():
    # Get App Config endpoint
    endpoint = os.environ.get("APP_CONFIG_ENDPOINT")
    if len(sys.argv) > 1:
        endpoint = sys.argv[1]
    
    if not endpoint:
        logging.error("Error: APP_CONFIG_ENDPOINT is required")
        logging.error("Usage: python run_purger_standalone.py <APP_CONFIG_ENDPOINT>")
        logging.error("Example: python run_purger_standalone.py https://appcs-xxxxx.azconfig.io")
        sys.exit(1)
    
    logging.info("=" * 60)
    logging.info("Blob Storage Purger - Standalone Version")
    logging.info("=" * 60)
    
    try:
        await run_purger(endpoint)
    except Exception as e:
        logging.exception(f"Purger failed: {e}")
        sys.exit(1)
    
    logging.info("=" * 60)
    logging.info("Done!")
    logging.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
