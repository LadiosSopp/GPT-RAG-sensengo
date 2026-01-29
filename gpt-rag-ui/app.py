import os
import re
import uuid
import logging
import urllib.parse
import time
import json
from typing import Optional, Set, Tuple
from datetime import datetime, timedelta

import chainlit as cl
from chainlit.server import app as chainlit_server_app
from fastapi import APIRouter
from fastapi.responses import JSONResponse, HTMLResponse

from orchestrator_client import call_orchestrator_stream
from feedback import register_feedback_handlers,create_feedback_actions
from dependencies import get_config
from connectors import BlobClient
from debug_store import get_debug_data, set_debug_data, extract_debug_events_from_text, format_debug_for_display

from constants import APPLICATION_INSIGHTS_CONNECTION_STRING, APP_NAME, UUID_REGEX, REFERENCE_REGEX, TERMINATE_TOKEN
from telemetry import Telemetry
from opentelemetry.trace import SpanKind

logger = logging.getLogger("gpt_rag_ui.app")

config = get_config()

Telemetry.configure_monitoring(config, APPLICATION_INSIGHTS_CONNECTION_STRING, APP_NAME)

ENABLE_FEEDBACK = config.get("ENABLE_USER_FEEDBACK", False, bool)
STORAGE_ACCOUNT_NAME = config.get("STORAGE_ACCOUNT_NAME", "", str)

# Create a router for debug routes
debug_router = APIRouter()

@debug_router.get("/_debug/data")
async def debug_data_api():
    """API endpoint to return debug data as JSON"""
    data = get_debug_data()
    if data:
        # Map orchestrator debug events to frontend expected format
        response = {
            "timing": data.get("timing", {}),
            "prompting": data.get("prompting", {}),
            "timestamp": data.get("timestamp", 0)
        }
        
        # Extract and map detailed timing from debug_events
        debug_events = data.get("debug_events", {})
        if debug_events:
            timings_list = debug_events.get("timings", [])
            # Map operation names to frontend expected keys
            timing_map = {}
            for t in timings_list:
                op = t.get("operation", "")
                duration = t.get("duration", 0)
                # Map orchestrator operation names to frontend keys
                if op == "thread_management":
                    timing_map["thread_creation"] = duration
                elif op == "agent_management":
                    timing_map["agent_creation"] = duration
                elif op == "send_message":
                    timing_map["send_message"] = duration
                elif op == "agent_response":
                    timing_map["response_streaming"] = duration
                elif op == "total_flow":
                    timing_map["total"] = duration
                elif op == "consolidate_history":
                    timing_map["consolidate_history"] = duration
                elif op == "llm_thinking_1":
                    timing_map["llm_thinking_1"] = duration
                elif op == "llm_thinking_2":
                    timing_map["llm_thinking_2"] = duration
                elif op == "tool_execution":
                    timing_map["tool_execution"] = duration
            
            # Include RAG/tool timing from tool_calls
            tool_calls = debug_events.get("tool_calls", [])
            for tc in tool_calls:
                name = tc.get("name", "")
                duration = tc.get("duration", 0)
                if "search" in name.lower():
                    timing_map["search_query"] = duration
                    # Only set tool_execution from tool_calls if not already set from timings
                    if "tool_execution" not in timing_map:
                        timing_map["tool_execution"] = duration
            
            # Include LLM timing from llm_calls (fallback if not in timings)
            llm_calls = debug_events.get("llm_calls", [])
            for i, lc in enumerate(llm_calls):
                duration = lc.get("duration", 0)
                if i == 0 and "llm_thinking_1" not in timing_map:
                    timing_map["llm_thinking_1"] = duration
                elif i == 1 and "llm_thinking_2" not in timing_map:
                    timing_map["llm_thinking_2"] = duration
            
            # Merge mapped timing with base timing
            response["timing"].update(timing_map)
            
            # Add prompting details
            system_prompt = debug_events.get("system_prompt")
            if system_prompt:
                response["prompting"]["system_prompt"] = system_prompt.get("prompt", "")[:2000]
                response["prompting"]["template_name"] = system_prompt.get("template_name", "")
                response["prompting"]["token_estimate"] = system_prompt.get("token_estimate", 0)
            
            # Add RAG results
            rag_results = debug_events.get("rag_results", [])
            if rag_results:
                first_rag = rag_results[0]
                response["prompting"]["search_results"] = {
                    "count": first_rag.get("result_count", 0),
                    "query": first_rag.get("query", ""),
                    "approach": first_rag.get("search_approach", ""),
                    "duration": first_rag.get("duration", 0),
                    "preview": "\n---\n".join([
                        f"[{r.get('title', 'N/A')}] (score: {r.get('score', 'N/A')})\n{r.get('content_preview', r.get('content', '')[:200])}"
                        for r in first_rag.get("results", [])[:3]
                    ])
                }
            
            # Add tool calls
            if tool_calls:
                response["prompting"]["tool_calls"] = tool_calls
            
            # Add model info from LLM calls
            if llm_calls:
                response["prompting"]["model"] = llm_calls[0].get("model", "unknown")
        
        return JSONResponse(content=response)
    return JSONResponse(content={"error": "No debug data available", "status": "waiting"})

@debug_router.get("/dev")
async def dev_mode_page():
    """Enable debug mode via cookie and redirect to main app"""
    html = """<!DOCTYPE html>
<html><head><title>Debug Mode</title>
<style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}.loader{text-align:center}.spinner{width:50px;height:50px;border:3px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 20px}@keyframes spin{to{transform:rotate(360deg)}}</style>
</head><body><div class="loader"><div class="spinner"></div><div>🐛 Enabling Debug Mode...</div></div>
<script>
document.cookie = 'gptrag_debug=true;path=/;max-age=86400';
localStorage.setItem('gptrag_debug','true');
setTimeout(()=>location.href='/',500);
</script>
</body></html>"""
    response = HTMLResponse(content=html)
    response.set_cookie(key="gptrag_debug", value="true", max_age=86400)
    return response

@debug_router.get("/dev/off")
async def dev_mode_off_page():
    """Disable debug mode and redirect to main app"""
    html = """<!DOCTYPE html>
<html><head><title>Debug Mode Off</title>
<style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}.loader{text-align:center}</style>
</head><body><div class="loader"><div>✅ Debug Mode Disabled</div></div>
<script>
document.cookie = 'gptrag_debug=;path=/;max-age=0';
localStorage.removeItem('gptrag_debug');
setTimeout(()=>location.href='/',500);
</script>
</body></html>"""
    response = HTMLResponse(content=html)
    response.delete_cookie(key="gptrag_debug")
    return response

# Insert debug routes at the BEGINNING of the route list (before catch-all)
# We need to insert them before the catch-all route /{full_path:path}
chainlit_server_app.include_router(debug_router)

# Move our routes to the front of the list (before catch-all)
# This is a hack but necessary because Chainlit's catch-all would otherwise match first
routes_to_move = []
for route in chainlit_server_app.routes:
    if hasattr(route, 'path') and route.path in ['/_debug/data', '/dev', '/dev/off']:
        routes_to_move.append(route)

for route in routes_to_move:
    chainlit_server_app.routes.remove(route)
    chainlit_server_app.routes.insert(0, route)  # Insert at beginning

logger.info("Debug routes registered and moved to front: /_debug/data and /dev")

def _normalize_container_name(container: Optional[str]) -> str:
    if not container:
        return ""
    return container.strip().strip("/")


DOCUMENTS_CONTAINER = _normalize_container_name(
    config.get("DOCUMENTS_STORAGE_CONTAINER", "", str)
)
IMAGES_CONTAINER = _normalize_container_name(
    config.get("DOCUMENTS_IMAGES_STORAGE_CONTAINER", "", str)
)
IMAGE_EXTENSIONS = {"bmp", "jpeg", "jpg", "png", "tiff"}

def extract_conversation_id_from_chunk(chunk: str) -> Tuple[Optional[str], str]:
    match = UUID_REGEX.match(chunk)
    if match:
        conv_id = match.group(1)
        logger.debug("Extracted conversation id %s from stream chunk", conv_id)
        return conv_id, chunk[match.end():]
    return None, chunk

def generate_blob_sas_url(container: str, blob_name: str, expiry_hours: int = 1) -> str:
    """
    Generate a time-limited SAS URL for direct blob download.
    This bypasses Container Apps routing completely.
    Raises FileNotFoundError if the blob does not exist.
    """
    try:
        blob_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{container}/{blob_name}"
        blob_client = BlobClient(blob_url=blob_url)
        if not blob_client.exists():
            logger.info("Blob not found: %s/%s - reference will be omitted", container, blob_name)
            raise FileNotFoundError(f"Blob '{container}/{blob_name}' not found")
        
        # Generate SAS token with read permission
        from datetime import datetime, timedelta, timezone
        expiry = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
        
        # Try to generate SAS URL (requires azure-storage-blob with SAS support)
        try:
            sas_url = blob_client.generate_sas_url(expiry=expiry, permissions="r")
            logger.debug(
                "Generated SAS URL for %s/%s (expires in %sh)",
                container,
                blob_name,
                expiry_hours,
            )
            return sas_url
        except AttributeError:
            # Fallback: return direct blob URL (relies on public access or managed identity at client side)
            logger.warning(
                "SAS generation not supported, using direct blob URL for %s/%s",
                container,
                blob_name,
            )
            return blob_url
    except FileNotFoundError:
        # Re-raise FileNotFoundError so the caller can handle it
        raise
    except Exception as e:
        logger.exception("Failed to generate blob URL for %s/%s", container, blob_name)
        raise

def resolve_reference_href(raw_href: str) -> Optional[str]:
    """
    Resolve a reference href to a SAS URL. Returns None if the blob doesn't exist.
    """
    href = (raw_href or "").strip()
    if not href:
        return None

    split_href = urllib.parse.urlsplit(href)
    if split_href.scheme or split_href.netloc:
        return href

    if href.startswith("/api/download/") or href.startswith("api/download/"):
        return href

    path = urllib.parse.unquote(split_href.path.replace("\\", "/")).lstrip("/")
    query = f"?{split_href.query}" if split_href.query else ""
    fragment = f"#{split_href.fragment}" if split_href.fragment else ""

    extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    container = DOCUMENTS_CONTAINER
    if extension in IMAGE_EXTENSIONS and IMAGES_CONTAINER:
        container = IMAGES_CONTAINER
    elif not container and IMAGES_CONTAINER:
        container = IMAGES_CONTAINER

    # Extract clean blob name
    if container:
        if path.startswith(f"{container}/"):
            blob_name = path[len(container)+1:]
        elif path:
            blob_name = path
        else:
            blob_name = ""
    else:
        blob_name = path

    if not blob_name:
        return None

    # Generate direct SAS URL to Azure Blob Storage (bypasses Container Apps completely)
    try:
        sas_url = generate_blob_sas_url(container, blob_name)
    except FileNotFoundError:
        logger.info("Reference '%s' points to missing blob %s/%s - omitting from output", raw_href, container, blob_name)
        return None
    except Exception:
        logger.warning("Failed to build SAS URL for reference '%s' - omitting from output", raw_href)
        return None
    
    # Add original query and fragment if present
    if sas_url and (query or fragment):
        separator = "&" if "?" in sas_url else "?"
        return f"{sas_url}{separator}{query.lstrip('?')}{fragment}"

    return sas_url


def replace_source_reference_links(text: str, references: Optional[Set[str]] = None) -> str:
    """
    Replace source reference links in text. Links that point to non-existent blobs are completely removed.
    """
    def replacer(match):
        display_text = match.group(1)
        raw_href = match.group(2)
        # Resolve the original link into a signed blob URL when possible, otherwise drop it.
        resolved_href = resolve_reference_href(raw_href)
        if resolved_href:
            if references is not None:
                references.add(resolved_href)
            logger.debug("Resolved reference '%s' -> '%s'", raw_href, resolved_href)
            return f"[{display_text}]({resolved_href})"
        # Returning an empty string removes the reference completely when the blob is missing
        logger.debug("Omitting reference '[%s](%s)' - target not found", display_text, raw_href)
        return ""

    return REFERENCE_REGEX.sub(replacer, text)

def check_authorization() -> dict:
    app_user = cl.user_session.get("user")
    if app_user:
        metadata = app_user.metadata or {}
        return {
            'authorized': metadata.get('authorized', True),
            'client_principal_id': metadata.get('client_principal_id', 'no-auth'),
            'client_principal_name': metadata.get('client_principal_name', 'anonymous'),
            'client_group_names': metadata.get('client_group_names', []),
            'access_token': metadata.get('access_token')
        }

    return {
        'authorized': True,
        'client_principal_id': 'no-auth',
        'client_principal_name': 'anonymous',
        'client_group_names': [],
        'access_token': None
    }

# Check if authentication is enabled
ENABLE_AUTHENTICATION = config.get("ENABLE_AUTHENTICATION", False, bool)
if ENABLE_AUTHENTICATION:
    import auth

tracer = Telemetry.get_tracer(__name__)

# Register feedback handlers
if ENABLE_FEEDBACK:
    register_feedback_handlers(check_authorization)

# Chainlit event handlers
@cl.on_chat_start
async def on_chat_start():
    # Default debug mode is ON (can be toggled by /debug command)
    debug_mode = config.get("DEBUG_MODE_ENABLED", True, bool)
    cl.user_session.set("debug_mode", debug_mode)

@cl.on_message
async def handle_message(message: cl.Message):
    # Handle debug command
    msg_lower = message.content.strip().lower()
    if msg_lower == "/debug" or msg_lower == "/debug on":
        cl.user_session.set("debug_mode", True)
        await cl.Message(content="""🐛 **Debug Mode 已啟用** - 回應會顯示詳細的執行資訊、時間和 RAG 結果

💡 **重要**: 請按 F5 重新整理頁面，或訪問 `/dev` 來啟用右側的 Debug Panel""").send()
        return
    elif msg_lower == "/debug off":
        cl.user_session.set("debug_mode", False)
        await cl.Message(content="✅ **Debug Mode 已關閉**").send()
        return
    elif msg_lower == "/debug status":
        debug_mode = cl.user_session.get("debug_mode", False)
        status = "啟用 🟢" if debug_mode else "關閉 🔴"
        await cl.Message(content=f"🐛 **Debug Mode 狀態**: {status}").send()
        return
    
    with tracer.start_as_current_span('handle_message', kind=SpanKind.SERVER) as span:

        message.id = message.id or str(uuid.uuid4())
        conversation_id = cl.user_session.get("conversation_id") or ""
        response_msg = cl.Message(content="")

        def _trim_for_log(value: str, limit: int = 400) -> str:
            clean_value = (value or "").strip().replace("\n", " ")
            if len(clean_value) > limit:
                return f"{clean_value[:limit].rstrip()}..."
            return clean_value

        app_user = cl.user_session.get("user")
        if app_user and not app_user.metadata.get('authorized', True):
            await response_msg.stream_token(
                "Oops! It looks like you don’t have access to this service. "
                "If you think you should, please reach out to your administrator for help."
            )
            logger.warning(
                "Blocked unauthorized request: conversation=%s user=%s",
                conversation_id or "new",
                app_user.metadata.get('client_principal_id', 'unknown'),
            )
            return
        
        span.set_attribute('question_id', message.id)
        span.set_attribute('conversation_id', conversation_id)
        span.set_attribute('user_id', app_user.metadata.get('client_principal_id', 'no-auth') if app_user else 'anonymous')

        principal = app_user.metadata.get('client_principal_name', 'anonymous') if app_user else 'anonymous'
        logger.info(
            "User request received: conversation=%s question_id=%s user=%s preview='%s'",
            conversation_id or "new",
            message.id,
            principal,
            _trim_for_log(message.content),
        )

        await response_msg.stream_token(" ")

        buffer = ""
        full_text = ""
        references = set()
        auth_info = check_authorization()
        logger.info(
            "Forwarding request to orchestrator: conversation=%s question_id=%s user=%s authorized=%s groups=%d",
            conversation_id or "new",
            message.id,
            principal,
            auth_info.get("authorized"),
            len(auth_info.get("client_group_names", [])),
        )
        logger.debug(
            "Orchestrator payload preview: conversation=%s question_id=%s preview='%s'",
            conversation_id or "new",
            message.id,
            _trim_for_log(message.content),
        )
        
        # Check if debug mode is enabled
        debug_mode = cl.user_session.get("debug_mode", False)
        
        generator = call_orchestrator_stream(conversation_id, message.content, auth_info, message.id, debug_mode=debug_mode)

        chunk_count = 0
        first_content_seen = False
        
        # Timing tracking for debug mode
        request_start_time = time.time()
        first_chunk_time = None
        
        # Debug events collected from stream
        collected_debug_events = None

        try:
            async for chunk in generator:
                # Track first chunk time (TTFB)
                if first_chunk_time is None:
                    first_chunk_time = time.time()
                # logging.info("[app] Chunk received: %s", chunk)

                # Extract and update conversation ID
                extracted_id, cleaned_chunk = extract_conversation_id_from_chunk(chunk)
                if extracted_id:
                    conversation_id = extracted_id

                cleaned_chunk = cleaned_chunk.replace("\\n", "\n")
                
                # Extract debug events from chunk (if present)
                cleaned_chunk, debug_events = extract_debug_events_from_text(cleaned_chunk)
                if debug_events:
                    collected_debug_events = debug_events
                    logger.info("[Debug] Debug events extracted from stream: summary=%s, events_count=%s",
                               'summary' in debug_events, len(debug_events.get('events', [])))
                    if 'summary' in debug_events:
                        summary_timings = debug_events.get('summary', {}).get('timings', [])
                        logger.info("[Debug] Summary timings count: %d", len(summary_timings))
                        for t in summary_timings[:5]:  # Log first 5
                            logger.info("[Debug] Timing: %s = %s", t.get('operation'), t.get('duration_seconds'))

                normalized_preview = cleaned_chunk.strip().lower()
                if not first_content_seen and normalized_preview:
                    if (
                        normalized_preview.startswith("<!doctype")
                        or normalized_preview.startswith("<html")
                        or "<html" in normalized_preview[:120]
                        or "azure container apps" in normalized_preview
                    ):
                        logger.error(
                            "Received HTML payload from orchestrator: conversation=%s question_id=%s",
                            conversation_id or "pending",
                            message.id,
                        )
                        raise RuntimeError("orchestrator returned html placeholder")
                    first_content_seen = True

                # Track and rewrite references as blob download links
                chunk_refs: Set[str] = set()
                cleaned_chunk = replace_source_reference_links(cleaned_chunk, chunk_refs)
                if chunk_refs:
                    references.update(chunk_refs)
                    logger.info(
                        "Streaming response references detected: conversation=%s question_id=%s refs=%s",
                        conversation_id or "pending",
                        message.id,
                        sorted(chunk_refs),
                    )

                buffer += cleaned_chunk
                full_text += cleaned_chunk
                chunk_count += 1

                # Handle TERMINATE token
                token_index = buffer.find(TERMINATE_TOKEN)
                if token_index != -1:
                    if token_index > 0:
                        await response_msg.stream_token(buffer[:token_index])
                    logger.debug(
                        "Terminate token detected, draining remaining orchestrator stream: conversation=%s question_id=%s",
                        conversation_id or "pending",
                        message.id,
                    )
                    async for _ in generator:
                        pass  # drain
                    break

                # Stream safe part of buffer
                if token_index != -1:
                    safe_flush_length = len(buffer) - (len(TERMINATE_TOKEN) - 1)
                else:
                    safe_flush_length = len(buffer)

                if safe_flush_length > 0:
                    await response_msg.stream_token(buffer[:safe_flush_length])
                    buffer = buffer[safe_flush_length:]

        except Exception as e:
            user_error_message = (
                "We hit a technical issue while processing your request. "
                "Please contact the application support team and share reference "
                f"{message.id}."
            )
            logger.exception(
                "Failed while processing orchestrator response: conversation=%s question_id=%s",
                conversation_id or "pending",
                message.id,
            )
            full_text = user_error_message
            buffer = ""
            await response_msg.stream_token(user_error_message)

        finally:
            try:
                await generator.aclose()
            except RuntimeError as exc:
                if "async generator ignored GeneratorExit" not in str(exc):
                    raise

        cl.user_session.set("conversation_id", conversation_id)
        if references:
            logger.info(
                "Aggregated response references: conversation=%s question_id=%s refs=%s",
                conversation_id,
                message.id,
                sorted(references),
            )
        if ENABLE_FEEDBACK:
            response_msg.actions = create_feedback_actions(
                message.id, conversation_id, message.content
            )
        final_text = replace_source_reference_links(
            full_text.replace(TERMINATE_TOKEN, ""), references
        )
        
        # Calculate timing info
        total_time = time.time() - request_start_time
        ttfb = (first_chunk_time - request_start_time) if first_chunk_time else total_time
        streaming_time = (time.time() - first_chunk_time) if first_chunk_time else 0
        
        # Format debug events if collected
        formatted_debug = None
        if collected_debug_events:
            formatted_debug = format_debug_for_display(collected_debug_events)
            logger.info("[Debug] Formatted debug data: summary=%s, timings=%d, llm_calls=%d, rag=%d",
                       bool(formatted_debug.get('summary')), 
                       len(formatted_debug.get('timings', [])),
                       len(formatted_debug.get('llm_calls', [])),
                       len(formatted_debug.get('rag_results', [])))
        
        # Store debug data via API (accessible by debug-panels.js)
        # Start with basic timing data
        timing_data = {
            "ttfb": round(ttfb, 2), 
            "streaming": round(streaming_time, 2), 
            "response_streaming": round(streaming_time, 2),
            "total": round(total_time, 2), 
            "chunks": chunk_count
        }
        
        # Extract orchestrator timing from debug events
        if formatted_debug and formatted_debug.get('timings'):
            logger.info("[Debug] Extracting timings from formatted_debug, count=%d", len(formatted_debug['timings']))
            for t in formatted_debug['timings']:
                op = t.get('operation', '')
                duration = t.get('duration', 0)
                logger.info("[Debug] Timing entry: op=%s, duration=%s", op, duration)
                if op and duration:
                    # Map operation names to timing panel keys
                    timing_data[op] = round(duration, 2)
            logger.info("[Debug] Final timing_data keys: %s", list(timing_data.keys()))
        
        prompting_data = {"user_message": message.content, "conversation_id": conversation_id}
        
        # Extract detailed debug info for prompting panel
        if formatted_debug:
            # System prompt
            if formatted_debug.get('system_prompt'):
                prompting_data['system_prompt'] = formatted_debug['system_prompt'].get('prompt', '')
            
            # RAG search results - include FULL results
            if formatted_debug.get('rag_results'):
                rag_results = formatted_debug['rag_results']
                prompting_data['search_results'] = {
                    'count': sum(r.get('result_count', 0) for r in rag_results),
                    'queries': [r.get('query', '') for r in rag_results],
                    'results': []  # Full results
                }
                for rag in rag_results:
                    for doc in rag.get('results', []):
                        prompting_data['search_results']['results'].append({
                            'title': doc.get('title', 'Untitled'),
                            'link': doc.get('link', ''),
                            'content': doc.get('content_preview', ''),  # Full content preview
                            'score': doc.get('score')
                        })
            
            # Tool calls
            if formatted_debug.get('tool_calls'):
                prompting_data['tool_calls'] = formatted_debug['tool_calls']
            
            # LLM calls
            if formatted_debug.get('llm_calls'):
                prompting_data['llm_calls'] = formatted_debug['llm_calls']
        
        try:
            set_debug_data(conversation_id, timing_data, prompting_data, formatted_debug)
            logger.debug("Debug data stored for conversation %s", conversation_id)
        except Exception as e:
            logger.debug("Failed to store debug data: %s", e)
        
        # Also clean debug events from final_text (in case they weren't removed during streaming)
        final_text_cleaned, _ = extract_debug_events_from_text(final_text)
        
        response_msg.content = final_text_cleaned
        await response_msg.update()
        
        # Debug panel is now handled by JavaScript (debug-panels.js)
        # No need for Python-based display_debug_panel

        logger.info(
            "Response delivered: conversation=%s question_id=%s chunks=%s characters=%s preview='%s'",
            conversation_id,
            message.id,
            chunk_count,
            len(final_text_cleaned),
            _trim_for_log(final_text_cleaned),
        )


# Note: display_debug_panel removed - debug info is now displayed by JavaScript (debug-panels.js)