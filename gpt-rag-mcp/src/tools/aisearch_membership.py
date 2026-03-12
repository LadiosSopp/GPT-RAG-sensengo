"""
MCP Tool: Azure AI Search — Query membership card information.

Searches the RAG index for membership card benefits, pricing,
and competitor comparisons using hybrid search (keyword + vector).
"""

import json
import logging
import os
from typing import Optional

import aiohttp
from azure.identity import DefaultAzureCredential, AzureCliCredential, ChainedTokenCredential

logger = logging.getLogger(__name__)

# ── Configuration (env vars with defaults matching App Configuration) ──
SEARCH_ENDPOINT = os.getenv(
    "SEARCH_SERVICE_QUERY_ENDPOINT",
    "https://srch-2v3lfktkn4xam-gprag.search.windows.net",
)
SEARCH_INDEX = os.getenv("SEARCH_RAG_INDEX_NAME", "ragindex")
SEARCH_API_VERSION = os.getenv("AZURE_SEARCH_API_VERSION", "2024-07-01")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
SEARCH_TOP_K = int(os.getenv("SEARCH_MEMBERSHIP_TOP_K", "5"))

# Cache credential across calls
_credential: Optional[ChainedTokenCredential] = None


def _get_credential() -> ChainedTokenCredential:
    global _credential
    if _credential is None:
        _credential = ChainedTokenCredential(
            DefaultAzureCredential(),
            AzureCliCredential(),
        )
    return _credential


async def _get_auth_header() -> dict:
    """Return auth header: API key if set, otherwise AAD bearer token."""
    if SEARCH_API_KEY:
        return {"api-key": SEARCH_API_KEY}

    credential = _get_credential()
    token = credential.get_token("https://search.azure.com/.default")
    return {"Authorization": f"Bearer {token.token}"}


async def search_membership_info(query: str, top_k: int = 0) -> str:
    """
    Search the RAG index for membership card related knowledge.

    Args:
        query: Natural language query about membership card benefits,
               pricing, or competitor comparisons.
        top_k: Maximum number of results to return (default uses env config).

    Returns:
        JSON string with a list of relevant document chunks,
        each containing title, filepath, content, and score.
    """
    if top_k <= 0:
        top_k = SEARCH_TOP_K

    logger.info(f"[aisearch] Searching membership info: query={query!r}, top_k={top_k}")

    search_body = {
        "search": query,
        "top": top_k,
        "select": "title,filepath,content",
        "queryType": "simple",
    }

    url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/search?api-version={SEARCH_API_VERSION}"

    try:
        auth_header = await _get_auth_header()
        headers = {
            "Content-Type": "application/json",
            **auth_header,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                json=search_body,
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error(f"[aisearch] Search failed: {resp.status} {text}")
                    return json.dumps({"error": f"Search failed: {resp.status}", "detail": text})

                data = await resp.json()

        results = []
        for doc in data.get("value", []):
            results.append({
                "title": doc.get("title", ""),
                "filepath": doc.get("filepath", ""),
                "content": doc.get("content", ""),
                "score": doc.get("@search.score", 0),
            })

        logger.info(f"[aisearch] Found {len(results)} results for query={query!r}")
        return json.dumps({"query": query, "results": results}, ensure_ascii=False)

    except Exception as exc:
        logger.exception("[aisearch] search_membership_info failed")
        return json.dumps({"error": str(exc)})
