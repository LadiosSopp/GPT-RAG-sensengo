import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from orchestration.orchestrator import Orchestrator
from connectors.appconfig import AppConfigClient
from dependencies import get_config, validate_auth
from telemetry import Telemetry
from schemas import OrchestratorRequest, SalesRecommendationRequest, ORCHESTRATOR_RESPONSES
from constants import APPLICATION_INSIGHTS_CONNECTION_STRING, APP_NAME
from util.tools import is_azure_environment

# ----------------------------------------
# Initialization and logging
# - Minimal early logging so config/auth warnings are visible during startup
# - Azure SDK and HTTP pipeline logs are verbose only when LOG_LEVEL=DEBUG;
#   otherwise they’re kept at WARNING to reduce noise
# ----------------------------------------

## Early minimal logging (INFO) until config is loaded; refined by Telemetry.configure_basic
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# Suppress Azure SDK HTTP logging immediately (before any Azure imports)
for _azure_logger in [
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.identity",
    "azure.core",
    "azure"
]:
    logger = logging.getLogger(_azure_logger)
    logger.setLevel(logging.CRITICAL)
    logger.propagate = False
    logger.disabled = True
    logger.handlers.clear()
    
# Load version from VERSION file 
VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
try:
    APP_VERSION = VERSION_FILE.read_text().strip()
except FileNotFoundError:
    APP_VERSION = "0.0.0"

# 2) Create configuration client (sets cfg.auth_failed=True if auth is unavailable)
cfg: AppConfigClient = get_config()

# 3) Configure logging level/format from LOG_LEVEL
Telemetry.configure_basic(cfg)
Telemetry.log_log_level_diagnostics(cfg)

# 4) If authentication failed, exit immediately
if getattr(cfg, "auth_failed", False):
    logging.warning("The orchestrator is not authenticated (run 'az login' or configure Managed Identity). Exiting...")
    logging.shutdown()
    os._exit(1)

# ----------------------------------------
# Create FastAPI app with lifespan
# ----------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    Telemetry.configure_monitoring(cfg, APPLICATION_INSIGHTS_CONNECTION_STRING, APP_NAME)
    yield  # <-- application runs here
    # cleanup logic after shutdown

app = FastAPI(
    title="GPT-RAG Orchestrator",
    description="GPT-RAG Orchestrator FastAPI",
    version=APP_VERSION,
    lifespan=lifespan
)

@app.post(
    "/orchestrator",
    dependencies=[Depends(validate_auth)], 
    summary="Ask orchestrator a question",
    response_description="Returns the orchestrator’s response in real time, streamed via SSE.",
    responses=ORCHESTRATOR_RESPONSES
)
async def orchestrator_endpoint(
    body: OrchestratorRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-KEY"),
    dapr_api_token: Optional[str] = Header(None, alias="dapr-api-token"),
):
    """
    Accepts JSON payload with ask/question, optional conversation_id and context,
    then streams back an answer via SSE.
    """

    # Determine operation type first (defensive: body may not include type)
    op_type = getattr(body, "type", None)

    # Feedback submissions: allow missing ask/question; validate only what's required
    if op_type == "feedback":
        # Handle feedback submission
        conversation_id = body.conversation_id
        if not conversation_id:
            logging.error(f"No 'conversation_id' provided in feedback body, and payload is {body}")
            raise HTTPException(status_code=400, detail="No 'conversation_id' field in request body")

        # Create orchestrator instance and save feedback
        orchestrator = await Orchestrator.create(conversation_id=conversation_id)
        # Build feedback dict defensively; optional fields may be absent
        _qid = getattr(body, "question_id", None)
        feedback = {
            "conversation_id": conversation_id,
            "question_id": _qid,
            "is_positive": getattr(body, "is_positive", None),
            "stars_rating": getattr(body, "stars_rating", None),
            # Normalize empty strings to None
            "feedback_text": (getattr(body, "feedback_text", None) or "").strip() or None,
        }
        await orchestrator.save_feedback(feedback)
        return {"status": "success", "message": "Feedback saved successfully"}    

    # For non-feedback operations, require an ask/question
    ask = (getattr(body, "ask", None) or getattr(body, "question", None))
    if not ask:
        raise HTTPException(status_code=400, detail="No 'ask' or 'question' field in request body")

    user_context = body.user_context or {}
    debug_mode = getattr(body, "debug_mode", False) or False
    search_index = getattr(body, "search_index", None)
    prompt_mode = getattr(body, "prompt_mode", None)
    
    logging.info(f"[Orchestrator API] debug_mode={debug_mode}, conversation_id={body.conversation_id}, search_index={search_index}, prompt_mode={prompt_mode}")

    orchestrator = await Orchestrator.create(
        conversation_id=body.conversation_id,
        user_context=user_context,
        debug_mode=debug_mode,
        search_index=search_index,
        prompt_mode=prompt_mode
    )

    async def sse_event_generator():
        try:
            _qid = getattr(body, "question_id", None) 
            async for chunk in orchestrator.stream_response(ask, _qid):
                yield f"{chunk}"
        except Exception as e:
            logging.exception("Error in SSE generator")
            yield "event: error\ndata: An internal server error occurred.\n\n"

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream"
    )

# ── Sales Recommendation Endpoint ─────────────────────────────────

@app.post(
    "/sales/recommendation",
    dependencies=[Depends(validate_auth)],
    summary="Generate personalised sales recommendation for a customer",
    response_description="Returns a structured JSON sales recommendation.",
)
async def sales_recommendation_endpoint(body: SalesRecommendationRequest):
    """
    3-step sequential workflow:
      Step 1  MCP → SQL Persona + Cosmos Call Summary
      Step 2  Persona → dynamic query → MCP → AI Search membership card RAG
      Step 3  GPT-5.2 reasoning model → 推薦話術
    """
    from connectors.sales_recommendation import SalesRecommendationClient

    rec_client = SalesRecommendationClient()
    result = await rec_client.generate_recommendation(
        customer_id=body.customer_id,
        call_customer_id=body.call_customer_id,
        model_deployment=body.model_deployment,
    )

    return {
        "customer_id": body.customer_id,
        "call_customer_id": body.call_customer_id or body.customer_id,
        "recommendation": result.get("recommendation", result),
        "debug": result.get("debug"),
    }


# ── Demo page ─────────────────────────────────────────────────────

DEMO_HTML_PATH = Path(__file__).resolve().parent / "static" / "demo.html"

@app.get("/demo", summary="Sales recommendation demo page")
async def demo_page():
    """Serve the single-page demo UI for sales recommendation."""
    html = DEMO_HTML_PATH.read_text(encoding="utf-8")
    return HTMLResponse(content=html)


# Instrumentation
HTTPXClientInstrumentor().instrument()
FastAPIInstrumentor.instrument_app(app)

# Run the app locally (avoid nested event loop when started by uvicorn CLI)
if __name__ == "__main__" and not is_azure_environment():
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="info", timeout_keep_alive=60)

