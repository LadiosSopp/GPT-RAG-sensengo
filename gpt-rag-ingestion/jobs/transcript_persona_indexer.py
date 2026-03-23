"""
Transcript Persona Indexer
==========================

Scheduled job that:
1. Monitors a Blob Storage container for new STT transcript JSON files
2. Upserts each transcript into Cosmos DB via MCP tool
3. Uses LLM to analyse transcripts and merge insights into the customer's
   persona text, then updates via MCP tool
4. Records update timestamp and source on the persona row

All Cosmos DB and Azure SQL access goes through the MCP Server.

Blob JSON schema (one file per call):
{
    "customer_id": "22003659",
    "call_id": "abc123",
    "call_date": "2026-03-17",
    "status": "成功",
    "transcript": "專員|270|您好...\\n顧客|5280|嗯嗯..."
}

Env / App Config keys:
    CRON_RUN_TRANSCRIPT_PERSONA  – cron expression for scheduling
    TRANSCRIPT_BLOB_CONTAINER    – source container (default: call-transcripts-stt)
    MCP_APP_ENDPOINT             – MCP Server URL (e.g. http://localhost:5000)
    MCP_APP_APIKEY               – MCP Server API key (optional)
    TRANSCRIPT_PERSONA_DEPLOYMENT – LLM deployment for persona merge (optional override)
"""

import asyncio
import dataclasses
import inspect
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from azure.identity.aio import (
    AzureCliCredential,
    ChainedTokenCredential,
    ManagedIdentityCredential,
)
from azure.storage.blob.aio import BlobServiceClient

from dependencies import get_config
from utils.tools import is_azure_environment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt for LLM persona merge
# ---------------------------------------------------------------------------
PERSONA_MERGE_PROMPT = """\
你是客戶側寫分析師。以下是一位客戶的現有人物側寫和最新的通話逐字稿。

【現有側寫】
{existing_persona}

【最新通話逐字稿】
通話日期: {call_date}
推銷結果: {status}
---
{transcript}
---

請根據以上通話內容，更新並輸出合併後的客戶側寫（純文字）。
規則：
1. 保留原側寫中仍然有效的資訊
2. 從通話中提取新的偏好、態度、關注點、購買意向等
3. 如有矛盾以最新通話為準
4. 簡潔扼要，重點明確，不超過 500 字
5. 僅輸出最終合併的側寫文字，不要前言或解釋
"""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class TranscriptPersonaConfig:
    # Blob Storage
    storage_account_name: str = ""
    source_container: str = "call-transcripts-stt"
    jobs_log_container: str = "jobs"
    processed_container: str = "call-transcripts-stt-processed"

    # MCP Server
    mcp_endpoint: str = "http://localhost:5000"
    mcp_api_key: str = ""
    mcp_timeout: int = 120

    # LLM
    persona_deployment: str = ""  # override chat deployment for persona merge

    # Behaviour
    max_concurrency: int = 4
    indexer_name: str = "transcript-persona-indexer"

    @staticmethod
    def from_app_config() -> "TranscriptPersonaConfig":
        app = get_config()

        if not is_azure_environment():
            default_mcp = "http://localhost:5000"
        else:
            default_mcp = "http://localhost:80"

        try:
            mcp_key = app.get("MCP_APP_APIKEY")
        except Exception:
            mcp_key = ""

        return TranscriptPersonaConfig(
            storage_account_name=app.get("STORAGE_ACCOUNT_NAME", ""),
            source_container=app.get("TRANSCRIPT_BLOB_CONTAINER", "call-transcripts-stt"),
            jobs_log_container=app.get("JOBS_LOG_CONTAINER", "jobs"),
            processed_container=app.get(
                "TRANSCRIPT_PROCESSED_CONTAINER", "call-transcripts-stt-processed"
            ),
            mcp_endpoint=app.get("MCP_APP_ENDPOINT", default=default_mcp),
            mcp_api_key=mcp_key or "",
            mcp_timeout=int(app.get("MCP_CLIENT_TIMEOUT", default="120")),
            persona_deployment=app.get("TRANSCRIPT_PERSONA_DEPLOYMENT", ""),
            max_concurrency=int(app.get("TRANSCRIPT_MAX_CONCURRENCY", "4")),
        )


# ---------------------------------------------------------------------------
# Lightweight MCP Client (JSON-RPC over Streamable HTTP)
# ---------------------------------------------------------------------------
class MCPClient:
    """Minimal async MCP client that calls tools via Streamable HTTP transport."""

    def __init__(self, endpoint: str, api_key: str = "", timeout: int = 120):
        self._url = endpoint.rstrip("/") + "/mcp"
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._mcp_session_id: Optional[str] = None
        self._request_id = 0

    async def _ensure_session(self):
        if self._session is None:
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if self._api_key:
                headers["X-API-KEY"] = self._api_key
            self._session = aiohttp.ClientSession(
                headers=headers, timeout=self._timeout
            )

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    async def _init_session(self):
        """Send MCP initialize handshake."""
        await self._ensure_session()
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "transcript-persona-indexer", "version": "1.0.0"},
            },
        }
        async with self._session.post(self._url, json=payload) as resp:
            resp.raise_for_status()
            # Capture session ID from response header
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self._mcp_session_id = sid
                self._session.headers.update({"mcp-session-id": sid})
            result = await resp.json()

        # Send initialized notification
        self._request_id += 1
        notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        async with self._session.post(self._url, json=notif) as resp:
            pass  # notification, no response body expected

        return result

    async def call_tool(self, tool_name: str, **arguments) -> Any:
        """Call an MCP tool and return the parsed result."""
        if self._mcp_session_id is None:
            await self._init_session()

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        async with self._session.post(self._url, json=payload) as resp:
            resp.raise_for_status()
            body = await resp.json()

        if "error" in body:
            raise RuntimeError(f"MCP error: {body['error']}")

        # Extract text content from result
        result = body.get("result", {})
        contents = result.get("content", [])
        texts = [c.get("text", "") for c in contents if c.get("type") == "text"]
        return "\n".join(texts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _gather_limited(coros, limit: int):
    sem = asyncio.Semaphore(limit)

    async def _run(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*(_run(c) for c in coros), return_exceptions=True)


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------
class TranscriptPersonaIndexer:
    """
    Flow per run:
        1. List blobs in source_container
        2. For each JSON blob:
           a. Parse → validate schema
           b. Upsert transcript doc into Cosmos DB (via MCP)
           c. Fetch existing persona from SQL (via MCP)
           d. Call LLM to merge persona
           e. Update persona + tracking columns in SQL (via MCP)
           f. Move blob to processed_container
        3. Write run summary to jobs container
    """

    def __init__(self, cfg: Optional[TranscriptPersonaConfig] = None):
        self.cfg = cfg or TranscriptPersonaConfig.from_app_config()
        self._credential: Optional[ChainedTokenCredential] = None
        self._blob_service: Optional[BlobServiceClient] = None
        self._mcp: Optional[MCPClient] = None

    # ── Clients ───────────────────────────────────────────────────
    async def _ensure_clients(self):
        if not self._credential:
            client_id = os.environ.get("AZURE_CLIENT_ID")
            self._credential = ChainedTokenCredential(
                AzureCliCredential(),
                ManagedIdentityCredential(client_id=client_id),
            )
        if not self._blob_service:
            acc = self.cfg.storage_account_name
            self._blob_service = BlobServiceClient(
                f"https://{acc}.blob.core.windows.net", credential=self._credential
            )
        if not self._mcp:
            self._mcp = MCPClient(
                endpoint=self.cfg.mcp_endpoint,
                api_key=self.cfg.mcp_api_key,
                timeout=self.cfg.mcp_timeout,
            )

    async def _close_clients(self):
        if self._mcp:
            await self._mcp.close()
        if self._blob_service:
            try:
                await self._blob_service.close()
            except Exception:
                pass
        if self._credential and hasattr(self._credential, "close"):
            try:
                res = self._credential.close()
                if inspect.isawaitable(res):
                    await res
            except Exception:
                pass

    # ── MCP tool wrappers ─────────────────────────────────────────
    async def _mcp_upsert_transcript(self, doc: dict):
        """Upsert transcript document into Cosmos DB via MCP."""
        result = await self._mcp.call_tool(
            "upsert_transcript",
            customer_id=doc["customer_id"],
            call_id=doc["call_id"],
            call_date=doc.get("call_date", ""),
            status=doc.get("status", ""),
            transcript=doc.get("transcript", ""),
            source=doc.get("source", ""),
            ingested_at=doc.get("ingested_at", ""),
        )
        parsed = json.loads(result)
        if "error" in parsed:
            raise RuntimeError(f"MCP upsert_transcript failed: {parsed['error']}")
        logger.info(
            f"[{self.cfg.indexer_name}] MCP upsert_transcript: "
            f"customer_id={doc['customer_id']} call_id={doc['call_id']}"
        )

    async def _mcp_fetch_persona(self, customer_id: str) -> Optional[str]:
        """Fetch existing persona from SQL via MCP. Returns None if not found."""
        result = await self._mcp.call_tool(
            "query_customer_persona", customer_id=customer_id
        )
        parsed = json.loads(result)
        if "error" in parsed:
            return None  # customer not found
        return parsed.get("persona") or parsed.get("re_summary_text") or ""

    async def _mcp_update_persona(
        self, customer_id: str, persona_text: str, source: str
    ) -> bool:
        """Update persona text + tracking in SQL via MCP."""
        result = await self._mcp.call_tool(
            "update_persona",
            customer_id=customer_id,
            persona_text=persona_text,
            source=source,
        )
        parsed = json.loads(result)
        if "error" in parsed:
            logger.warning(
                f"[{self.cfg.indexer_name}] MCP update_persona failed: {parsed['error']}"
            )
            return False
        return True

    # ── LLM persona merge ─────────────────────────────────────────
    def _merge_persona_with_llm(
        self, existing_persona: str, transcript: str, call_date: str, status: str
    ) -> str:
        from tools import AzureOpenAIClient

        aoai = AzureOpenAIClient(document_filename="transcript-persona")
        # Allow deployment override
        if self.cfg.persona_deployment:
            aoai.chat_deployment = self.cfg.persona_deployment

        prompt = PERSONA_MERGE_PROMPT.format(
            existing_persona=existing_persona or "（無現有側寫）",
            call_date=call_date,
            status=status,
            transcript=transcript[:6000],  # cap to avoid token overflow
        )
        return aoai.get_completion(prompt, max_tokens=1024)

    # ── Blob move (source → processed) ───────────────────────────
    async def _move_blob(self, blob_name: str):
        """Copy blob to processed container then delete from source."""
        src_container = self._blob_service.get_container_client(self.cfg.source_container)
        dst_container = self._blob_service.get_container_client(self.cfg.processed_container)

        # Ensure destination container exists
        try:
            await dst_container.create_container()
        except Exception:
            pass  # already exists

        src_blob = src_container.get_blob_client(blob_name)
        dst_blob = dst_container.get_blob_client(blob_name)

        await dst_blob.start_copy_from_url(src_blob.url)
        await src_blob.delete_blob()
        logger.info(f"[{self.cfg.indexer_name}] Moved {blob_name} → {self.cfg.processed_container}")

    # ── Per-blob processing ───────────────────────────────────────
    async def _process_one(self, blob_name: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {"blob": blob_name, "status": "success"}
        try:
            # 1. Download & parse JSON
            container = self._blob_service.get_container_client(self.cfg.source_container)
            blob_client = container.get_blob_client(blob_name)
            download = await blob_client.download_blob()
            raw = await download.readall()
            doc = json.loads(raw.decode("utf-8"))

            customer_id = doc.get("customer_id", "").strip()
            call_id = doc.get("call_id", "").strip()
            call_date = doc.get("call_date", "")
            status = doc.get("status", "")
            transcript = doc.get("transcript", "")

            if not customer_id or not call_id:
                raise ValueError(f"Missing customer_id or call_id in {blob_name}")

            # 2. Upsert into Cosmos DB (via MCP)
            cosmos_doc = {
                "customer_id": customer_id,
                "call_id": call_id,
                "call_date": call_date,
                "status": status,
                "transcript": transcript,
                "source": "stt_blob_ingest",
                "ingested_at": _utc_now_iso(),
            }
            await self._mcp_upsert_transcript(cosmos_doc)

            # 3. Fetch existing persona (via MCP)
            existing = await self._mcp_fetch_persona(customer_id)

            # 4. LLM merge (sync → thread)
            if existing is not None:  # customer exists in SQL
                merged = await asyncio.to_thread(
                    self._merge_persona_with_llm, existing, transcript, call_date, status
                )

                # 5. Update SQL persona (via MCP)
                updated = await self._mcp_update_persona(
                    customer_id, merged, f"transcript_ingest:{call_id}"
                )
                result["persona_updated"] = updated
            else:
                logger.warning(
                    f"[{self.cfg.indexer_name}] Customer {customer_id} not found in SQL — "
                    "transcript saved to Cosmos only"
                )
                result["persona_updated"] = False

            # 6. Move blob to processed container
            await self._move_blob(blob_name)
            result["customer_id"] = customer_id
            result["call_id"] = call_id

        except Exception as exc:
            logger.exception(f"[{self.cfg.indexer_name}] Error processing {blob_name}")
            result["status"] = "error"
            result["error"] = str(exc)

        return result

    # ── Run summary ───────────────────────────────────────────────
    async def _write_summary(self, summary: dict, run_id: str):
        try:
            jobs = self._blob_service.get_container_client(self.cfg.jobs_log_container)
            try:
                await jobs.create_container()
            except Exception:
                pass
            blob = jobs.get_blob_client(
                f"{self.cfg.indexer_name}/{run_id}/summary.json"
            )
            await blob.upload_blob(
                json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"),
                overwrite=True,
            )
        except Exception:
            logger.exception(f"[{self.cfg.indexer_name}] Failed to write run summary")

    # ── Public entry point ────────────────────────────────────────
    async def run(self) -> None:
        await self._ensure_clients()
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        logger.info(f"[{self.cfg.indexer_name}] Starting run {run_id}")

        summary = {
            "indexerType": self.cfg.indexer_name,
            "runId": run_id,
            "runStartedAt": _utc_now_iso(),
            "runFinishedAt": None,
            "sourceContainer": self.cfg.source_container,
            "blobsFound": 0,
            "success": 0,
            "failed": 0,
            "personaUpdated": 0,
            "status": "running",
        }

        try:
            container = self._blob_service.get_container_client(self.cfg.source_container)

            # Ensure source container exists
            try:
                await container.create_container()
            except Exception:
                pass

            blobs: List[str] = []
            async for b in container.list_blobs():
                if b.name.endswith(".json"):
                    blobs.append(b.name)

            summary["blobsFound"] = len(blobs)
            logger.info(f"[{self.cfg.indexer_name}] Found {len(blobs)} JSON blobs to process")

            if blobs:
                results = await _gather_limited(
                    (self._process_one(name) for name in blobs),
                    self.cfg.max_concurrency,
                )

                for r in results:
                    if isinstance(r, dict):
                        if r.get("status") == "success":
                            summary["success"] += 1
                            if r.get("persona_updated"):
                                summary["personaUpdated"] += 1
                        else:
                            summary["failed"] += 1
                    else:
                        summary["failed"] += 1

            summary["status"] = "finished"

        except Exception as exc:
            logger.exception(f"[{self.cfg.indexer_name}] Run failed")
            summary["status"] = "failed"
            summary["error"] = str(exc)
        finally:
            summary["runFinishedAt"] = _utc_now_iso()
            await self._write_summary(summary, run_id)
            logger.info(f"[{self.cfg.indexer_name}] Run {run_id} complete: {json.dumps(summary, ensure_ascii=False)}")
            await self._close_clients()
