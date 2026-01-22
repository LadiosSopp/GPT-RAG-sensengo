#!/usr/bin/env python3
"""
Check Indexer Schedule - 查看 Indexer 的 CRON 排程設定
"""
import asyncio
import logging
import os
import sys
from typing import Dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

for name in ["azure.core.pipeline.policies.http_logging_policy", "azure.identity"]:
    logging.getLogger(name).setLevel(logging.WARNING)


async def check_cron_settings(app_config_endpoint: str):
    """Check CRON settings in App Configuration."""
    
    from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential, ChainedTokenCredential
    from azure.appconfiguration.aio import AzureAppConfigurationClient
    
    credential = ChainedTokenCredential(
        ManagedIdentityCredential(),
        AzureCliCredential()
    )
    
    print("\n" + "=" * 70)
    print("⏰ INDEXER SCHEDULE SETTINGS")
    print("=" * 70 + "\n")
    
    async with AzureAppConfigurationClient(app_config_endpoint, credential) as config_client:
        config: Dict[str, str] = {}
        
        # Get all settings
        async for setting in config_client.list_configuration_settings(label_filter="gpt-rag"):
            config[setting.key] = setting.value
        async for setting in config_client.list_configuration_settings(label_filter="\0"):
            if setting.key not in config:
                config[setting.key] = setting.value
    
    # CRON related settings
    cron_keys = [
        "CRON_RUN_BLOB_INDEX",
        "CRON_RUN_BLOB_PURGE", 
        "CRON_RUN_SHAREPOINT_INDEX",
        "CRON_RUN_SHAREPOINT_PURGE",
        "CRON_RUN_NL2SQL_INDEX",
        "CRON_RUN_NL2SQL_PURGE",
        "CRON_RUN_IMAGES_PURGE",
    ]
    
    print("📅 CRON Schedule Settings:")
    print("-" * 50)
    
    for key in cron_keys:
        value = config.get(key, "(not set)")
        status = "✅" if value and value != "(not set)" else "❌"
        print(f"  {status} {key}")
        print(f"     Value: {value}")
        if value and value != "(not set)":
            # Parse cron expression
            try:
                parts = value.split()
                if len(parts) >= 5:
                    minute, hour, dom, month, dow = parts[:5]
                    if parts == ["*", "*", "*", "*", "*"]:
                        print(f"     → 每分鐘執行")
                    elif parts == ["*/5", "*", "*", "*", "*"]:
                        print(f"     → 每 5 分鐘執行")
                    elif parts == ["*/30", "*", "*", "*", "*"]:
                        print(f"     → 每 30 分鐘執行")
                    elif parts == ["0", "*", "*", "*", "*"]:
                        print(f"     → 每小時執行 (整點)")
                    elif parts == ["0", "*/2", "*", "*", "*"]:
                        print(f"     → 每 2 小時執行")
                    elif minute.startswith("*/"):
                        interval = minute[2:]
                        print(f"     → 每 {interval} 分鐘執行")
                    else:
                        print(f"     → 自訂排程: 分={minute} 時={hour} 日={dom} 月={month} 週={dow}")
            except:
                pass
        print()
    
    print("-" * 50)
    print("\n📝 其他相關設定:")
    print("-" * 50)
    
    other_keys = [
        "DOCUMENTS_STORAGE_CONTAINER",
        "STORAGE_ACCOUNT_NAME",
        "AI_SEARCH_INDEX_NAME",
        "SEARCH_RAG_INDEX_NAME",
    ]
    
    for key in other_keys:
        value = config.get(key, "(not set)")
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 70)


async def main():
    if len(sys.argv) < 2:
        print("Usage: python check_cron_settings.py <APP_CONFIG_ENDPOINT>")
        sys.exit(1)
    
    await check_cron_settings(sys.argv[1])


if __name__ == "__main__":
    asyncio.run(main())
