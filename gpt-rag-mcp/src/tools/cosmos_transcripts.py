"""
MCP Tool: Cosmos DB — Query call transcripts.

Provides call-transcript lookup by customer ID.
Uses AAD token authentication (static token acquired once at startup).
"""

import json
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

# ── Connection config ──────────────────────────────────────────────
COSMOS_ENDPOINT = os.getenv(
    "COSMOS_ENDPOINT",
    "https://cosmos-2v3lfktkn4xam-gprag.documents.azure.com:443/",
)
COSMOS_DATABASE = os.getenv("COSMOS_DATABASE", "cosmos-db2v3lfktkn4xam-gprag")
COSMOS_CONTAINER = os.getenv("COSMOS_CONTAINER", "call-transcripts")

# Lazy-initialised module-level client
_container = None


def _get_container():
    """Return a cached Cosmos container client (sync SDK)."""
    global _container
    if _container is not None:
        return _container

    from azure.cosmos import CosmosClient
    from azure.core.credentials import AccessToken

    cosmos_key = os.getenv("COSMOS_KEY")
    if cosmos_key:
        client = CosmosClient(COSMOS_ENDPOINT, credential=cosmos_key)
    else:
        # Acquire AAD token once via Azure CLI
        res = subprocess.run(
            "az account get-access-token --resource https://cosmos.azure.com/ "
            "--query accessToken -o tsv",
            shell=True,
            capture_output=True,
            text=True,
        )
        token = res.stdout.strip()
        if not token:
            raise RuntimeError(f"Failed to get Cosmos AAD token: {res.stderr.strip()}")

        class _StaticCred:
            def __init__(self, tok):
                self._tok = tok

            def get_token(self, *_a, **_kw):
                return AccessToken(self._tok, int(time.time()) + 3600)

        client = CosmosClient(COSMOS_ENDPOINT, credential=_StaticCred(token))

    _container = (
        client.get_database_client(COSMOS_DATABASE)
        .get_container_client(COSMOS_CONTAINER)
    )
    return _container


def get_call_transcripts(customer_id: str) -> str:
    """
    Retrieve all call transcripts for a customer from Cosmos DB.

    Args:
        customer_id: The customer identifier (客代).

    Returns:
        A JSON array of call transcript records, each containing:
        call_id, call_date, status (成功/失敗), and transcript text.
    """
    logger.info(f"[cosmos] Querying call transcripts for customer_id={customer_id}")
    try:
        container = _get_container()
        items = list(container.query_items(
            query="SELECT c.call_id, c.customer_id, c.call_date, c.status, c.transcript "
                  "FROM c WHERE c.customer_id = @cid",
            parameters=[{"name": "@cid", "value": customer_id}],
            enable_cross_partition_query=True,
        ))
        logger.info(f"[cosmos] Found {len(items)} transcripts")
        return json.dumps(items, ensure_ascii=False)

    except Exception as exc:
        logger.exception("[cosmos] Query failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def get_call_summary(customer_id: str) -> str:
    """
    Get a brief summary of call history for a customer (without full transcripts).

    Args:
        customer_id: The customer identifier (客代).

    Returns:
        A JSON object with total_calls, success/failure counts,
        and a list of call metadata (date, status, transcript preview).
    """
    logger.info(f"[cosmos] Querying call summary for customer_id={customer_id}")
    try:
        container = _get_container()
        items = list(container.query_items(
            query="SELECT c.call_id, c.call_date, c.status, LEFT(c.transcript, 200) AS preview "
                  "FROM c WHERE c.customer_id = @cid",
            parameters=[{"name": "@cid", "value": customer_id}],
            enable_cross_partition_query=True,
        ))

        success = sum(1 for i in items if i.get("status") == "成功")
        failed = sum(1 for i in items if i.get("status") == "失敗")

        summary = {
            "customer_id": customer_id,
            "total_calls": len(items),
            "success_count": success,
            "failure_count": failed,
            "calls": [
                {
                    "call_id": i.get("call_id"),
                    "call_date": i.get("call_date"),
                    "status": i.get("status"),
                    "preview": i.get("preview", "")[:200],
                }
                for i in items
            ],
        }
        return json.dumps(summary, ensure_ascii=False)

    except Exception as exc:
        logger.exception("[cosmos] Summary query failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
