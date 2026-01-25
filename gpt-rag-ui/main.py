import logging
import os
import json
from io import BytesIO

from fastapi import Response, Request, FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, RedirectResponse, JSONResponse

# Configure logging FIRST
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s'
)

# Reduce noise from chatty Azure SDK loggers so troubleshooting signals stand out.
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

logger = logging.getLogger("gpt_rag_ui.main")

from connectors import BlobClient
from connectors import AppConfigClient
from dependencies import get_config

# Load environment variables from Azure App Configuration
config : AppConfigClient = get_config()
logger.info("Configuration loaded from Azure App Configuration")

# Import debug_store early for ASGI wrapper use
from debug_store import get_debug_data

# Import chainlit_app AFTER config is ready
from chainlit.server import app as chainlit_app

# Note: Debug middleware will be wrapped at the ASGI level after all routes are defined
logger.info("Chainlit app imported, will add debug middleware wrapper at ASGI level")
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

def download_from_blob(file_name: str) -> bytes:
    logger.info("Preparing blob download for '%s'", file_name)

    blob_url = f"https://{account_name}.blob.core.windows.net/{file_name}"
    logger.debug("Constructed blob URL %s", blob_url)
    
    try:
        blob_client = BlobClient(blob_url=blob_url)
        blob_data = blob_client.download_blob()
        logger.debug("Successfully downloaded blob data for '%s'", file_name)
        return blob_data
    except Exception as e:
        logger.exception("Error downloading blob '%s'", file_name)
        raise

account_name = config.get("STORAGE_ACCOUNT_NAME")
documents_container = config.get("DOCUMENTS_STORAGE_CONTAINER")
images_container = config.get("DOCUMENTS_IMAGES_STORAGE_CONTAINER")

def handle_file_download(file_path: str):
    try:
        file_bytes = download_from_blob(file_path)
        if not file_bytes:
            return Response("File not found or empty.", status_code=404, media_type="text/plain")
    except Exception as e:
        error_message = str(e)
        status_code = 404 if "BlobNotFound" in error_message else 500
        logger.exception("Download error for '%s'", file_path)
        return Response(
            f"{'Blob not found' if status_code == 404 else 'Internal server error'}: {error_message}.",
            status_code=status_code,
            media_type="text/plain"
        )
    
    actual_file_name = os.path.basename(file_path)
    return StreamingResponse(
        BytesIO(file_bytes),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{actual_file_name}"'}
    )

# TODO: Validate blob metadata_security_id to prevent unauthorized access.

# Create a separate FastAPI app for blob downloads that will be mounted
blob_download_app = FastAPI()
logger.info("Created FastAPI sub-application for blob downloads")

@blob_download_app.get("/{container_name}/{file_path:path}")
async def download_blob_file(container_name: str, file_path: str):
    logger.info("Download request received: container=%s file=%s", container_name, file_path)
    normalized = container_name.strip().strip("/")
    target_container = None
    if normalized == documents_container:
        target_container = documents_container
    elif normalized == images_container:
        target_container = images_container
    
    if not target_container:
        logger.warning("Rejected download for unknown container '%s'", container_name)
        return Response("Container not found", status_code=404, media_type="text/plain")
    
    return handle_file_download(f"{target_container}/{file_path}")

logger.debug("Registered download_blob_file route on blob_download_app")

# Mount the blob download app BEFORE importing chainlit handlers
try:
    chainlit_app.mount("/api/download", blob_download_app)
    logger.info("Mounted blob download app at /api/download")
    logger.debug("Chainlit routes post-mount: %s", [r.path for r in chainlit_app.routes])
except Exception as e:
    logger.exception("Failed to mount blob_download_app")
    raise

# Debug mode routes - only keep the JS file route (other routes handled by ASGI wrapper)
from debug_store import set_debug_data

@chainlit_app.get("/api/debug-panels.js")
async def serve_debug_panels_js():
    """Serve the debug panels JavaScript file"""
    js_path = os.path.join(os.path.dirname(__file__), "public", "debug-panels.js")
    if os.path.exists(js_path):
        return FileResponse(js_path, media_type="application/javascript")
    return Response("Debug panels not found", status_code=404)

logger.info("Debug panels JS route registered at /api/debug-panels.js")

# Import Chainlit event handlers
import app as chainlit_handlers

logger.info("Chainlit handlers imported")

# Note: The ASGI entry point 'app' is defined at the bottom of this file as DebugASGIWrapper(chainlit_app)

# Provide friendly app metadata used by OpenAPI (read version from VERSION file when present)
chainlit_app.title = getattr(chainlit_app, "title", "GPT-RAG UI")
try:
    if os.path.exists("VERSION"):
        chainlit_app.version = open("VERSION").read().strip()
except Exception:
    chainlit_app.version = getattr(chainlit_app, "version", "dev")

# Safe OpenAPI generator: try normal get_openapi, fall back to minimal schema on error
from fastapi.openapi.utils import get_openapi

def _safe_openapi():
    if getattr(chainlit_app, "openapi_schema", None):
        return chainlit_app.openapi_schema
    try:
        chainlit_app.openapi_schema = get_openapi(
            title=chainlit_app.title,
            version=chainlit_app.version,
            routes=chainlit_app.routes,
        )
    except Exception as exc:
        # Log the original exception and return a tiny fallback openapi schema so /docs and /openapi.json don't 500
        logger.exception("OpenAPI generation failed; returning fallback schema")
        chainlit_app.openapi_schema = {
            "openapi": "3.0.0",
            "info": {"title": chainlit_app.title, "version": chainlit_app.version},
            "paths": {},
        }
    return chainlit_app.openapi_schema

chainlit_app.openapi = _safe_openapi

# Wrap the app with debug middleware at ASGI level - this runs BEFORE Chainlit processes any routes
class DebugASGIWrapper:
    """ASGI wrapper that intercepts debug routes before they reach Chainlit"""
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            
            # Handle /_debug/data endpoint
            if path == "/_debug/data":
                data = get_debug_data()
                body = json.dumps(data if data else {"error": "No debug data available", "status": "waiting"})
                
                async def send_response(send):
                    await send({
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [[b"content-type", b"application/json"]],
                    })
                    await send({
                        "type": "http.response.body",
                        "body": body.encode(),
                    })
                
                await send_response(send)
                return
            
            # Handle /dev route
            if path in ["/dev", "/dev/"]:
                html_content = """<!DOCTYPE html>
<html>
<head><title>Enabling Debug Mode...</title>
<style>body{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white}.loader{text-align:center}.spinner{width:50px;height:50px;border:3px solid rgba(255,255,255,0.3);border-top-color:white;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 20px}@keyframes spin{to{transform:rotate(360deg)}}</style>
</head>
<body><div class="loader"><div class="spinner"></div><div>🐛 Enabling Debug Mode...</div></div>
<script>localStorage.setItem('gptrag_debug','true');console.log('[Debug] Debug mode enabled');setTimeout(function(){window.location.href='/';},500);</script>
</body></html>"""
                
                async def send_html(send):
                    await send({
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [[b"content-type", b"text/html; charset=utf-8"]],
                    })
                    await send({
                        "type": "http.response.body",
                        "body": html_content.encode(),
                    })
                
                await send_html(send)
                return
        
        # Pass all other requests to the Chainlit app
        await self.app(scope, receive, send)

# The actual ASGI app with debug middleware wrapper
app = DebugASGIWrapper(chainlit_app)
logger.info("Debug ASGI middleware wrapper installed - /_debug/data and /dev routes active")

FastAPIInstrumentor.instrument_app(chainlit_app)
HTTPXClientInstrumentor().instrument()