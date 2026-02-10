"""
Connector for querying call transcripts stored in Cosmos DB.

Provides a function-tool compatible interface for the LLM agent to query
call transcript records by customer ID, status, date, or free-text search.
"""
import json
import logging
from typing import Optional
from azure.cosmos.aio import CosmosClient
from dependencies import get_config

logger = logging.getLogger(__name__)


class CallTranscriptClient:
    """
    Queries the call-transcripts Cosmos DB container.
    Designed to be used as a FunctionTool in Azure AI Agent.
    """

    CONTAINER_NAME = "call-transcripts"

    def __init__(self):
        cfg = get_config()
        self.database_account_name = cfg.get("DATABASE_ACCOUNT_NAME")
        self.database_name = cfg.get("DATABASE_NAME")
        self.db_uri = f"https://{self.database_account_name}.documents.azure.com:443/"
        self.credential = cfg.aiocredential
        logger.info("[CallTranscriptClient] Initialized (db=%s, container=%s)",
                     self.database_name, self.CONTAINER_NAME)

    async def query_call_transcripts(
        self,
        customer_id: Optional[str] = None,
        status: Optional[str] = None,
        call_date: Optional[str] = None,
        keyword: Optional[str] = None,
        top: int = 10,
        include_full_transcript: str = "false",
    ) -> str:
        """
        Query call transcript records from the database.
        Use this function to look up customer call records, analyse call outcomes,
        or search for specific conversation content.

        :param customer_id: Filter by customer ID (客代). Example: "22003659".
        :param status: Filter by call outcome. Allowed values: "成功" or "失敗".
        :param call_date: Filter by call date in YYYY-MM-DD format. Example: "2026-01-09".
        :param keyword: Search keyword within the transcript text.
        :param top: Maximum number of results to return (default 10, max 50).
        :param include_full_transcript: Set to "true" to return full transcript without truncation. Default "false".
        :return: JSON string with matching call transcript records.
        """
        top = min(int(top), 50)
        full_transcript = str(include_full_transcript).lower() == "true"

        # Build SQL query dynamically
        conditions = []
        params = []

        if customer_id:
            conditions.append("c.customer_id = @customer_id")
            params.append({"name": "@customer_id", "value": str(customer_id)})

        if status:
            conditions.append("c.status = @status")
            params.append({"name": "@status", "value": status})

        if call_date:
            conditions.append("c.call_date = @call_date")
            params.append({"name": "@call_date", "value": call_date})

        if keyword:
            conditions.append("CONTAINS(c.transcript, @keyword, true)")
            params.append({"name": "@keyword", "value": keyword})

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = (
            f"SELECT c.id, c.customer_id, c.call_id, c.call_date, c.status, "
            f"c.transcript "
            f"FROM c WHERE {where_clause} "
            f"ORDER BY c.call_date DESC "
            f"OFFSET 0 LIMIT {top}"
        )

        logger.info("[CallTranscriptClient] Query: %s | Params: %s", query, params)

        try:
            async with CosmosClient(self.db_uri, credential=self.credential) as client:
                db = client.get_database_client(self.database_name)
                container = db.get_container_client(self.CONTAINER_NAME)

                # Use cross-partition query when no customer_id filter
                partition_key = str(customer_id) if customer_id else None

                items = container.query_items(
                    query=query,
                    parameters=params if params else None,
                    partition_key=partition_key,
                )

                results = []
                async for item in items:
                    # Truncate long transcripts unless full transcript requested
                    if not full_transcript:
                        transcript = item.get("transcript", "")
                        if len(transcript) > 2000:
                            item["transcript"] = transcript[:2000] + "... [truncated, ask for full transcript to see complete content]"
                            item["transcript_length"] = len(transcript)
                    # Remove Cosmos internal fields
                    for k in ["_rid", "_self", "_etag", "_attachments", "_ts"]:
                        item.pop(k, None)
                    results.append(item)

                summary = {
                    "total_results": len(results),
                    "query_filters": {
                        "customer_id": customer_id,
                        "status": status,
                        "call_date": call_date,
                        "keyword": keyword,
                    },
                    "records": results,
                }

                logger.info("[CallTranscriptClient] Returned %d results", len(results))
                return json.dumps(summary, ensure_ascii=False)

        except Exception as e:
            logger.error("[CallTranscriptClient] Query failed: %s", e, exc_info=True)
            return json.dumps({
                "error": f"Failed to query call transcripts: {str(e)}",
                "total_results": 0,
                "records": [],
            }, ensure_ascii=False)
