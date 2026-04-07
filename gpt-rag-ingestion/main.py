import datetime
import json
import logging
import os
import time
import subprocess
import jsonschema
import uvicorn
from tzlocal import get_localzone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse, Response
from contextlib import asynccontextmanager
from pathlib import Path

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from utils.file_utils import get_filename
from dependencies import get_config, validate_api_key_header
from telemetry import Telemetry
from constants import APPLICATION_INSIGHTS_CONNECTION_STRING, APP_NAME
from utils.tools import is_azure_environment

# -------------------------------
# App Configuration (initialized at runtime)
# -------------------------------
app_config_client = None  # set inside lifespan after auth checks

# FastAPI app + Scheduler
# -------------------------------
def _resolve_timezone():
    tz_name = os.getenv("SCHEDULER_TIMEZONE")
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            logging.warning(f"Invalid SCHEDULER_TIMEZONE '{tz_name}', defaulting to machine timezone")
    return get_localzone()

local_tz = _resolve_timezone()
scheduler = AsyncIOScheduler(timezone=local_tz)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ALL heavy initialization is deferred to a background task so that
    # Uvicorn binds port 80 immediately and passes the startup probe.
    import asyncio

    async def _deferred_init():
        """Run all initialization and startup jobs in the background."""
        logging.info("[deferred-init] Starting background initialization...")

        # Authentication and config loading are synchronous / blocking operations.
        # Run them in a thread so they don't freeze the event loop.
        def _sync_init():
            # Compact authentication check
            env = os.environ
            has_mi = any(env.get(k) for k in ("IDENTITY_ENDPOINT", "MSI_ENDPOINT", "MSI_SECRET"))
            has_sp = all(env.get(k) for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"))
            has_cli = False
            if not is_azure_environment():
                try:
                    has_cli = subprocess.run(["az", "account", "show", "-o", "none"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
                except Exception:
                    has_cli = False
            if not (has_sp or has_mi or has_cli):
                logging.warning("Not authenticated. Exiting...")
                os._exit(1)

            logging.info("[deferred-init] Auth check passed")

            # Reduce Azure SDK noise
            for name in [
                "azure.core.pipeline.policies.http_logging_policy",
                "azure.core.pipeline.policies",
                "azure.identity", "azure", "urllib3",
            ]:
                lg = logging.getLogger(name)
                lg.setLevel(logging.CRITICAL if name.endswith("http_logging_policy") else logging.WARNING)
                lg.propagate = False
                lg.addHandler(logging.NullHandler())

            logging.info("[deferred-init] Loading App Configuration...")
            cfg = get_config()
            logging.info("[deferred-init] App Configuration loaded")
            return cfg

        try:
            cfg = await asyncio.to_thread(_sync_init)
        except Exception:
            logging.exception("[deferred-init] Failed during sync init")
            return

        global app_config_client
        app_config_client = cfg

        Telemetry.configure_monitoring(app_config_client, APPLICATION_INSIGHTS_CONNECTION_STRING, APP_NAME)

        # scheduler helper
        def _schedule(env_key, func, job_id, human_name):
            cron_expr = app_config_client.get(env_key, default=None, allow_none=True)
            if cron_expr:
                try:
                    trigger = CronTrigger.from_crontab(cron_expr, timezone=local_tz)
                    scheduler.add_job(func, trigger=trigger, id=job_id, replace_existing=True)
                    logging.info(f"[{human_name}] Scheduled @ {cron_expr}")
                    return True
                except ValueError:
                    logging.error(f"Invalid {env_key}: {cron_expr!r}")
                    return False
            else:
                logging.warning(f"[{human_name}] {env_key} not set — skipping job")
                return False

        scheduler.start()
        logging.info(f"Scheduler timezone: {local_tz}")

        s_sharepoint_index = _schedule("CRON_RUN_SHAREPOINT_INDEX", run_sharepoint_index, "sharepoint_index", "sharepoint-indexer")
        s_sharepoint_purge = _schedule("CRON_RUN_SHAREPOINT_PURGE", run_sharepoint_purge, "sharepoint_purge", "sharepoint-purger")
        s_images_purge = _schedule("CRON_RUN_IMAGES_PURGE", run_images_purge, "multimodality_images_purge", "multimodality-images-purger")
        s_blob_index = _schedule("CRON_RUN_BLOB_INDEX", run_blob_index, "blob_index", "blob-storage-indexer")
        s_blob_purge = _schedule("CRON_RUN_BLOB_PURGE", run_blob_purge, "blob_purge", "blob-storage-indexer-purger")
        s_nl2sql_index = _schedule("CRON_RUN_NL2SQL_INDEX", run_nl2sql_index, "nl2sql_index", "nl2sql-indexer")
        s_nl2sql_purge = _schedule("CRON_RUN_NL2SQL_PURGE", run_nl2sql_purge, "nl2sql_purge", "nl2sql-indexer-purger")
        s_transcript_persona = _schedule("CRON_RUN_TRANSCRIPT_PERSONA", run_transcript_persona, "transcript_persona", "transcript-persona-indexer")
        s_transcript_insight = _schedule("CRON_RUN_TRANSCRIPT_INSIGHT", run_transcript_insight, "transcript_insight", "transcript-insight-indexer")

        logging.info("[deferred-init] Scheduler configured. Skipping immediate startup run (jobs will execute on their cron schedule).")

    asyncio.create_task(_deferred_init())

    yield  # Uvicorn starts listening IMMEDIATELY

    scheduler.shutdown(wait=False)

# Load version from VERSION file 
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
try:
    APP_VERSION = VERSION_FILE.read_text().strip()
except FileNotFoundError:
    APP_VERSION = "0.0.0"

app = FastAPI(
    title="GPT-RAG Ingestion",
    description="GPT-RAG Data Ingestion FastAPI",
    version=APP_VERSION,
    lifespan=lifespan
)

# Health check endpoint — must respond quickly so startup/readiness probes pass
@app.get("/healthz")
async def healthz():
    return JSONResponse(content={"status": "ok"}, status_code=200)

# -------------------------------
# Timer job wrappers
# -------------------------------
async def run_sharepoint_index():
    logging.debug("[sharepoint-indexer] Starting")
    try:
        from jobs.sharepoint_indexer import SharePointIndexer
        await SharePointIndexer().run()
    except Exception:
        logging.exception("[sharepoint-indexer] Unexpected error")

async def run_sharepoint_purge():
    logging.debug("[sharepoint-purger] Starting")
    try:
        from jobs.sharepoint_purger import SharepointPurger
        await SharepointPurger().run()
    except Exception:
        logging.exception("[sharepoint-purger] Unexpected error")

async def run_images_purge():
    logging.info("[multimodality_images_purger] Starting")
    multi_var = (app_config_client.get("MULTIMODAL") or "").lower()
    if multi_var not in ("true", "1", "yes"):
        logging.info("[multimodality_images_purger] Skipped (MULTIMODAL!=true)")
        return
    try:
        from jobs.multimodal_images_purger import ImagesDeletedFilesPurger
        await ImagesDeletedFilesPurger().run()
    except Exception:
        logging.exception("[multimodality_images_purger] Error")

async def run_blob_index():
    logging.debug("[blob-storage-indexer] Starting")
    try:
        from jobs.blob_storage_indexer import BlobStorageDocumentIndexer
        await BlobStorageDocumentIndexer().run()
    except Exception:
        logging.exception("[blob-storage-indexer] Unexpected error")

async def run_blob_purge():
    logging.debug("[blob-storage-indexer-purger] Starting")
    try:
        from jobs.blob_storage_indexer import BlobStorageDeletedItemsCleaner
        await BlobStorageDeletedItemsCleaner().run()
    except Exception:
        logging.exception("[blob-storage-indexer-purger] Unexpected error")

async def run_sharepoint_index():
    logging.debug("[sharepoint-indexer] Starting")
    try:
        from jobs.sharepoint_indexer import SharePointIndexer
        await SharePointIndexer().run()
    except Exception:
        logging.exception("[sharepoint-indexer] Unexpected error")

async def run_sharepoint_purge():
    logging.debug("[sharepoint-purger] Starting")
    try:
        from jobs.sharepoint_purger import SharePointPurger
        await SharePointPurger().run()
    except Exception:
        logging.exception("[sharepoint-purger] Unexpected error")        

async def run_nl2sql_index():
    logging.debug("[nl2sql-indexer] Starting")
    try:
        from jobs.nl2sql_indexer import NL2SQLIndexer
        await NL2SQLIndexer().run()
    except Exception:
        logging.exception("[nl2sql-indexer] Unexpected error")

async def run_nl2sql_purge():
    logging.debug("[nl2sql-indexer-purger] Starting")
    try:
        from jobs.nl2sql_purger import NL2SQLPurger
        await NL2SQLPurger().run()
    except Exception:
        logging.exception("[nl2sql-indexer-purger] Unexpected error")

async def run_transcript_persona():
    logging.debug("[transcript-persona-indexer] Starting")
    try:
        from jobs.transcript_persona_indexer import TranscriptPersonaIndexer
        await TranscriptPersonaIndexer().run()
    except Exception:
        logging.exception("[transcript-persona-indexer] Unexpected error")

async def run_transcript_insight():
    logging.debug("[transcript-insight-indexer] Starting")
    try:
        from jobs.transcript_insight_indexer import TranscriptInsightIndexer
        await TranscriptInsightIndexer().run()
    except Exception:
        logging.exception("[transcript-insight-indexer] Unexpected error")

# -------------------------------
# HTTP-triggered document-chunking
# -------------------------------
@app.post("/document-chunking", dependencies=[Depends(validate_api_key_header)])
async def document_chunking(request: Request):
    start_time = time.time()
    # --- parse JSON ---
    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        logging.error(f"[document_chunking] Invalid JSON: {e}")
        return Response(f"Invalid JSON: {e}", status_code=400)

    # --- validate schema ---
    try:
        jsonschema.validate(body, schema=get_document_chunking_request_schema())
    except jsonschema.ValidationError as e:
        logging.error(f"[document_chunking] Validation error: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid request: {e}")

    values_list = body.get("values")
    if not values_list:
        logging.error("[document_chunking] Invalid body: missing values")
        return Response("Invalid body: missing values", status_code=400)

    logging.info(f'[document_chunking] Invoked document_chunking skill. Number of items: {len(values_list)}.')

    # Only process the last item if >1
    if len(values_list) > 1:
        logging.warning('BatchSize should be set to 1; processing only the last item.')
    item = values_list[-1]
    input_data = item["data"]
    filename = get_filename(input_data["documentUrl"])
    logging.info(f'[document_chunking] Chunking document: File {filename}, Content Type {input_data["documentContentType"]}.')

    # download and enrich
    from tools import BlobClient
    blob_client = BlobClient(input_data["documentUrl"])
    document_bytes = blob_client.download_blob()
    input_data['documentBytes'] = document_bytes
    input_data['fileName'] = filename

    # chunk
    from chunking import DocumentChunker
    chunks, errors, warnings = DocumentChunker().chunk_documents(input_data)
    for c in chunks:
        c["source"] = "blob"

    # debug log first 100 chars of each
    for idx, chunk in enumerate(chunks):
        preview = chunk.get("content", "")[:100]
        logging.debug(f"[document_chunking][{filename}] Chunk {idx+1}: {preview!r}")

    # build result
    record_id = item.get("recordId")
    result_payload = {
        "values": [
            {
                "recordId": record_id,
                "data": {"chunks": chunks},
                "errors": errors,
                "warnings": warnings
            }
        ]
    }

    elapsed = time.time() - start_time
    logging.info(f'[document_chunking] Finished in {elapsed:.2f} seconds.')

    return JSONResponse(content=result_payload)

def get_document_chunking_request_schema():
    return {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "recordId": {"type": "string"},
                        "data": {
                            "type": "object",
                            "properties": {
                                "documentUrl": {"type": "string", "minLength": 1},
                              
                                "documentSasToken": {"type": "string", "minLength": 0},

                                "documentContentType": {"type": "string", "minLength": 1}
                            },
                            "required": ["documentUrl", "documentContentType"],
                        },
                    },
                    "required": ["recordId", "data"],
                },
            }
        },
        "required": ["values"],
    }

# -------------------------------
# HTTP-triggered text-embedding
# -------------------------------
@app.post("/text-embedding", dependencies=[Depends(validate_api_key_header)])
async def text_embedding(request: Request):
    start_time = time.time()
    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        logging.error(f"[text_embedding] Invalid JSON: {e}")
        return Response(f"Invalid JSON: {e}", status_code=400)

    if not body or "values" not in body:
        logging.error("[text_embedding] Invalid body.")
        return Response("Invalid body.", status_code=400)

    logging.info(f'[text_embedding] Invoked text_embedding skill. Number of items: {len(body["values"])}.')

    from tools import AzureOpenAIClient
    aoai_client = AzureOpenAIClient()
    values = []

    for item in body["values"]:
        record_id = item.get("recordId")
        input_data = item.get("data", {}).get("text", "")
        logging.info(f'[text_embedding] Generating embeddings for: {input_data[:10]}…')

        errors = []
        warnings = []
        data_payload = {}

        try:
            contentVector = aoai_client.get_embeddings(input_data)
            data_payload = {"embedding": contentVector}
        except Exception as e:
            error_message = f"Error generating embeddings: {e}"
            logging.error(f'[text_embedding] {error_message}', exc_info=True)
            errors.append({"message": error_message})

        values.append({
            "recordId": record_id,
            "data": data_payload,
            "errors": errors,
            "warnings": warnings
        })

    results = {"values": values}

    elapsed = time.time() - start_time
    logging.info(f'[text_embedding] Finished in {elapsed:.2f} seconds.')

    return JSONResponse(content=results)

# -------------------------------
# Pipeline toggle control
# -------------------------------
PIPELINE_GROUPS = {
    "stt_analysis": {
        "name": "通話分析 (STT Analysis)",
        "job_ids": ["transcript_persona", "transcript_insight"],
    },
    "data_ingestion": {
        "name": "資料擷取 (Data Ingestion)",
        "job_ids": [
            "blob_index", "blob_purge",
            "sharepoint_index", "sharepoint_purge",
            "nl2sql_index", "nl2sql_purge",
            "multimodality_images_purge",
        ],
    },
}


def _validate_pipeline_api_key(x_api_key: str = Depends(APIKeyHeader(name='X-API-KEY'))):
    """Validate API key for pipeline endpoints.
    
    Unlike validate_api_key_header, this gracefully handles the case where
    app_config_client hasn't been initialized yet (deferred init).
    """
    if app_config_client is None:
        raise HTTPException(status_code=503, detail="Service is still initializing")
    expected = app_config_client.get('INGESTION_APP_APIKEY', default=None, allow_none=True)
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/api/pipelines", dependencies=[Depends(_validate_pipeline_api_key)])
async def get_pipelines():
    """Return status of all pipeline groups and their jobs."""
    result = {}
    for group_id, group_info in PIPELINE_GROUPS.items():
        jobs = []
        for job_id in group_info["job_ids"]:
            job = scheduler.get_job(job_id)
            if job:
                jobs.append({
                    "id": job_id,
                    "paused": job.next_run_time is None,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                })
        result[group_id] = {
            "name": group_info["name"],
            "jobs": jobs,
            "paused": all(j["paused"] for j in jobs) if jobs else True,
        }
    return JSONResponse(content=result)


@app.post("/api/pipelines/{group_id}/toggle", dependencies=[Depends(_validate_pipeline_api_key)])
async def toggle_pipeline(group_id: str):
    """Toggle a pipeline group on/off (pause/resume all jobs in the group)."""
    if group_id not in PIPELINE_GROUPS:
        raise HTTPException(status_code=404, detail=f"Unknown pipeline group: {group_id}")

    group = PIPELINE_GROUPS[group_id]
    # Determine current state: paused when every scheduled job is paused
    all_paused = True
    for job_id in group["job_ids"]:
        job = scheduler.get_job(job_id)
        if job and job.next_run_time is not None:
            all_paused = False
            break

    action = "resume" if all_paused else "pause"
    for job_id in group["job_ids"]:
        job = scheduler.get_job(job_id)
        if job:
            if action == "pause":
                scheduler.pause_job(job_id)
            else:
                scheduler.resume_job(job_id)

    logging.info(f"[pipeline-toggle] {group_id} ({group['name']}): {action}d")
    return JSONResponse(content={"group_id": group_id, "action": action, "paused": action == "pause"})


HTTPXClientInstrumentor().instrument()
FastAPIInstrumentor.instrument_app(app)

# Only run Uvicorn directly when executing this file as a script.
# When launched via `uvicorn main:app ...`, this block will not run.
if __name__ == "__main__":
    if not is_azure_environment():
        uvicorn.run("main:app", host="0.0.0.0", port=80, log_level="debug", timeout_keep_alive=60, reload=False)
