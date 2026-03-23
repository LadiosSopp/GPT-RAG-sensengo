"""
MCP Tool: Cosmos DB — Query call transcripts.

Provides call-transcript lookup by customer ID.
Uses AAD token authentication (static token acquired once at startup).
"""

import json
import logging
import os
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

    cosmos_key = os.getenv("COSMOS_KEY")
    if cosmos_key:
        client = CosmosClient(COSMOS_ENDPOINT, credential=cosmos_key)
    else:
        from azure.identity import DefaultAzureCredential
        client = CosmosClient(COSMOS_ENDPOINT, credential=DefaultAzureCredential())

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


def upsert_call_transcript(
    customer_id: str,
    call_id: str,
    call_date: str,
    status: str,
    transcript: str,
    source: str = "",
    ingested_at: str = "",
) -> str:
    """
    Upsert a call transcript document into Cosmos DB.

    Args:
        customer_id: The customer identifier (客代), used as partition key.
        call_id: Unique call identifier, used as document id.
        call_date: Call date in YYYY-MM-DD format.
        status: Call result (成功/失敗).
        transcript: Full transcript text.
        source: Origin of the transcript (e.g. 'stt_blob_ingest').
        ingested_at: ISO timestamp of ingestion.

    Returns:
        A JSON object with status and upserted document id.
    """
    logger.info(f"[cosmos] Upserting transcript customer_id={customer_id} call_id={call_id}")
    try:
        container = _get_container()
        doc = {
            "id": call_id,
            "customer_id": customer_id,
            "call_id": call_id,
            "call_date": call_date,
            "status": status,
            "transcript": transcript,
        }
        if source:
            doc["source"] = source
        if ingested_at:
            doc["ingested_at"] = ingested_at
        container.upsert_item(body=doc)
        logger.info(f"[cosmos] Upserted call_id={call_id}")
        return json.dumps({"status": "ok", "call_id": call_id}, ensure_ascii=False)

    except Exception as exc:
        logger.exception("[cosmos] Upsert failed")
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
