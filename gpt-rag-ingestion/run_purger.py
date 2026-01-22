#!/usr/bin/env python3
"""
Manual script to run the Blob Storage Purger.
This will clean up index records for blobs that no longer exist in Storage.

Usage:
    python run_purger.py <APP_CONFIG_ENDPOINT>
    
Example:
    python run_purger.py https://appcs-xxxxx.azconfig.io
"""
import asyncio
import logging
import os
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

async def main():
    # Check for APP_CONFIG_ENDPOINT
    if len(sys.argv) > 1:
        os.environ["APP_CONFIG_ENDPOINT"] = sys.argv[1]
        logging.info(f"Using APP_CONFIG_ENDPOINT: {sys.argv[1]}")
    elif not os.environ.get("APP_CONFIG_ENDPOINT"):
        logging.error("Error: APP_CONFIG_ENDPOINT is required.")
        logging.error("Usage: python run_purger.py <APP_CONFIG_ENDPOINT>")
        logging.error("Example: python run_purger.py https://appcs-xxxxx.azconfig.io")
        sys.exit(1)
    
    logging.info("=" * 60)
    logging.info("Starting Blob Storage Purger...")
    logging.info("=" * 60)
    
    try:
        from jobs.blob_storage_indexer import BlobStorageDeletedItemsCleaner
        
        cleaner = BlobStorageDeletedItemsCleaner()
        await cleaner.run()
        
        logging.info("=" * 60)
        logging.info("Purger completed successfully!")
        logging.info("=" * 60)
        
    except Exception as e:
        logging.exception(f"Purger failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
