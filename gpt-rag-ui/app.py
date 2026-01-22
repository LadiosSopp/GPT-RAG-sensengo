import os
import re
import uuid
import logging
import urllib.parse
import time as time_module
import asyncio
from typing import Optional, Set, Tuple
from datetime import datetime, timedelta

import chainlit as cl
from chainlit.input_widget import Select, Slider

from orchestrator_client import call_orchestrator_stream
from feedback import register_feedback_handlers,create_feedback_actions
from dependencies import get_config
from connectors import BlobClient

from constants import APPLICATION_INSIGHTS_CONNECTION_STRING, APP_NAME, UUID_REGEX, REFERENCE_REGEX, TERMINATE_TOKEN, SUPPORTED_EXTENSIONS
from telemetry import Telemetry
from opentelemetry.trace import SpanKind

logger = logging.getLogger("gpt_rag_ui.app")

config = get_config()

Telemetry.configure_monitoring(config, APPLICATION_INSIGHTS_CONNECTION_STRING, APP_NAME)

# Model deployment options for the dropdown
# Format: {"display_name": "deployment_name"}
MODEL_OPTIONS = {
    "GPT-5 (Latest)": "gpt5-chat",
    "GPT-5 Nano (Fastest)": "gpt5-nano",
    "GPT-5 Mini (Balanced)": "gpt5-mini",
    "GPT-4.1": "chat",
    "GPT-4.1 Nano": "gpt4.1-nano",
}
DEFAULT_MODEL = "gpt5-chat"

# Search Index options for multi-tenant support
# Format: {"display_name": "index_name"}
# These can be dynamically loaded from App Configuration or AI Search
INDEX_OPTIONS = {
    "預設知識庫": "ragindex-d5teispadppru",
    "Company A 知識庫": "ragindex-company-a",
}
DEFAULT_INDEX = "ragindex-d5teispadppru"

# Status messages for user feedback during processing
# These map to [STATUS:xxx] events from orchestrator
STATUS_MESSAGES = {
    "thinking": ("🤔", "LLM 思考中"),
    "searching": ("🔍", "搜尋知識庫"),
    "generating": ("✍️", "生成回應中"),
    "done": None,  # Clear status
}

# Stage display order for dynamic status
STAGE_ORDER = ["thinking", "searching", "generating"]

# Regex pattern for status events
STATUS_PATTERN = re.compile(r'\[STATUS:(\w+)\]')

# Regex pattern for debug events (JSON payload)
DEBUG_PATTERN = re.compile(r'\[DEBUG:(.+)\]$', re.DOTALL)

ENABLE_FEEDBACK = config.get("ENABLE_USER_FEEDBACK", False, bool)
STORAGE_ACCOUNT_NAME = config.get("STORAGE_ACCOUNT_NAME", "", str)


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


def format_timing_panel(debug_info: dict) -> str:
    """
    Format timing statistics into a Markdown string.
    """
    import json
    
    lines = []
    
    total_ms = debug_info.get("total_duration_ms", 0)
    lines.append(f"**總耗時**: {total_ms:.0f} ms ({total_ms/1000:.2f} 秒)")
    lines.append("")
    
    # Timing breakdown table
    timings = debug_info.get("timings", [])
    if timings:
        lines.append("| 階段 | 開始時間 | 耗時 (ms) | 說明 |")
        lines.append("|------|----------|-----------|------|")
        for t in timings:
            stage = t.get("stage", "")
            start = t.get("start_time", "")[:19].replace("T", " ")
            duration = t.get("duration_ms", 0)
            details = t.get("details", "")
            lines.append(f"| {stage} | {start} | {duration:.1f} | {details} |")
    
    # Search timing breakdown
    search_debug = debug_info.get("search_debug", {})
    if search_debug:
        lines.append("")
        lines.append("### 🔍 搜尋時間細分")
        lines.append(f"- **Embeddings**: {search_debug.get('embeddings_time_ms', 0):.1f} ms")
        lines.append(f"- **AI Search**: {search_debug.get('search_time_ms', 0):.1f} ms")
        lines.append(f"- **總搜尋時間**: {search_debug.get('total_time_ms', 0):.1f} ms")
        lines.append(f"- **結果數量**: {search_debug.get('results_count', 0)}")
    
    return "\n".join(lines)


def format_prompting_panel(debug_info: dict) -> str:
    """
    Format prompting details into a Markdown string.
    """
    import json
    
    lines = []
    
    # Model info
    model_name = debug_info.get("model_name", "unknown")
    lines.append(f"**模型**: `{model_name}`")
    lines.append("")
    
    # System Prompt
    system_prompt = debug_info.get("system_prompt", "")
    if system_prompt:
        lines.append("### 🤖 System Prompt")
        lines.append("```")
        if len(system_prompt) > 2000:
            lines.append(system_prompt[:2000] + "\n... (truncated)")
        else:
            lines.append(system_prompt)
        lines.append("```")
        lines.append("")
    
    # User Message
    user_message = debug_info.get("user_message", "")
    if user_message:
        lines.append("### 👤 User Message")
        lines.append("```")
        lines.append(user_message)
        lines.append("```")
        lines.append("")
    
    # Search Query and Results
    search_debug = debug_info.get("search_debug", {})
    if search_debug:
        query = search_debug.get("query", "")
        if query:
            lines.append("### 🔎 Search Query")
            lines.append(f"**查詢**: `{query}`")
            lines.append("")
            lines.append(f"**索引**: `{search_debug.get('index_name', '')}`")
            lines.append(f"**方法**: `{search_debug.get('search_approach', '')}`")
            lines.append(f"**Top K**: `{search_debug.get('top_k', 0)}`")
            lines.append("")
            
            # Search body
            search_body = search_debug.get("search_body", {})
            if search_body:
                lines.append("**Search Body**:")
                lines.append("```json")
                lines.append(json.dumps(search_body, indent=2, ensure_ascii=False))
                lines.append("```")
            lines.append("")
        
        # Search Results Preview
        results_preview = search_debug.get("results_preview", [])
        if results_preview:
            lines.append("### 📄 Search Results")
            for i, r in enumerate(results_preview, 1):
                lines.append(f"**{i}. {r.get('title', 'No Title')}**")
                lines.append(f"- Link: `{r.get('link', '')}`")
                preview = r.get('content_preview', '')
                if preview:
                    lines.append(f"- Preview: {preview[:200]}...")
                lines.append("")
    
    return "\n".join(lines)


def clean_debug_info(debug_info: dict) -> dict:
    """
    Clean up debug info by removing unnecessary JSON tags and formatting.
    """
    import re
    
    cleaned = debug_info.copy()
    
    # Clean system prompt
    if 'system_prompt' in cleaned and cleaned['system_prompt']:
        prompt = cleaned['system_prompt']
        # Remove XML-like tags
        prompt = re.sub(r'<\/?json>', '', prompt, flags=re.IGNORECASE)
        prompt = re.sub(r'<\/?data>', '', prompt, flags=re.IGNORECASE)
        prompt = re.sub(r'<\/?content>', '', prompt, flags=re.IGNORECASE)
        # Try to extract content from JSON wrapper
        if prompt.strip().startswith('{'):
            try:
                import json
                parsed = json.loads(prompt)
                if isinstance(parsed, dict):
                    if 'content' in parsed:
                        prompt = parsed['content']
                    elif 'text' in parsed:
                        prompt = parsed['text']
                    elif 'prompt' in parsed:
                        prompt = parsed['prompt']
            except:
                pass
        # Truncate if too long
        if len(prompt) > 3000:
            prompt = prompt[:3000] + '\n\n... (truncated)'
        cleaned['system_prompt'] = prompt.strip()
    
    # Clean search body - remove overly verbose fields
    if 'search_debug' in cleaned and cleaned['search_debug']:
        search = cleaned['search_debug'].copy()
        # Simplify search body
        if 'search_body' in search and search['search_body']:
            body = search['search_body']
            # Keep only essential fields
            simplified_body = {}
            for key in ['search', 'filter', 'queryType', 'top', 'select']:
                if key in body:
                    simplified_body[key] = body[key]
            # Truncate vectorQueries if present
            if 'vectorQueries' in body:
                simplified_body['vectorQueries'] = '[vector data omitted]'
            search['search_body'] = simplified_body
        
        # Clean results preview - remove HTML tags but keep full content
        if 'results_preview' in search and search['results_preview']:
            cleaned_results = []
            for r in search['results_preview']:  # Keep all results
                # Clean content preview - remove HTML/Markdown tags
                content_preview = r.get('content_preview', '')
                # Remove HTML tags
                content_preview = re.sub(r'<[^>]+>', ' ', content_preview)
                # Remove Markdown formatting
                content_preview = re.sub(r'#+ ', '', content_preview)
                content_preview = re.sub(r'\*+', '', content_preview)
                content_preview = re.sub(r'`+', '', content_preview)
                # Remove extra whitespace
                content_preview = re.sub(r'\s+', ' ', content_preview).strip()
                
                cleaned_results.append({
                    'title': r.get('title', 'No Title'),
                    'link': r.get('link', ''),
                    'score': r.get('score'),  # Preserve score for display
                    'content_preview': content_preview  # Full content, no truncation
                })
            search['results_preview'] = cleaned_results
        
        cleaned['search_debug'] = search
    
    return cleaned


# Keep the old function for backward compatibility
def format_debug_panel(debug_info: dict) -> str:
    """
    Format debug info into a Markdown string for display.
    Creates two sections: Timing Statistics and Prompting Details.
    """
    timing = format_timing_panel(debug_info)
    prompting = format_prompting_panel(debug_info)
    return f"## ⏱️ 時間統計\n\n{timing}\n\n---\n\n## 📝 Prompting 詳情\n\n{prompting}"



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
    For Azure Blob Storage URLs, generates a SAS token to enable download.
    """
    href = (raw_href or "").strip()
    if not href:
        return None

    split_href = urllib.parse.urlsplit(href)
    
    # Check if this is an Azure Blob Storage URL that needs SAS token
    if split_href.scheme and split_href.netloc:
        # If it's an Azure Blob Storage URL, extract container and blob name to generate SAS
        if ".blob.core.windows.net" in split_href.netloc:
            # Parse the blob URL: https://<account>.blob.core.windows.net/<container>/<blob_path>
            path_parts = split_href.path.lstrip("/").split("/", 1)
            if len(path_parts) >= 2:
                container = path_parts[0]
                blob_name = urllib.parse.unquote(path_parts[1])
                logger.debug("Detected Azure Blob URL, extracting container=%s, blob=%s", container, blob_name)
                try:
                    sas_url = generate_blob_sas_url(container, blob_name)
                    return sas_url
                except FileNotFoundError:
                    logger.info("Reference '%s' points to missing blob - omitting", raw_href)
                    return None
                except Exception:
                    logger.warning("Failed to generate SAS for blob URL '%s' - omitting", raw_href)
                    return None
        # For other external URLs, return as-is
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


# Regex to match plain Azure Blob Storage URLs (not already in markdown link format)
# Uses file extension as the endpoint to handle URLs with parentheses and spaces in filenames
# Matches URLs that:
# 1. Are standalone (not preceded by '](')
# 2. Are wrapped in parentheses like (https://...)
AZURE_BLOB_URL_REGEX = re.compile(
    r'(?<!\]\()(https://[a-zA-Z0-9]+\.blob\.core\.windows\.net/.+?\.(?:' + '|'.join(SUPPORTED_EXTENSIONS) + r'))(?=[\s\)\]\uff09\u3002\uff0c\uff1b]|$)',
    re.IGNORECASE
)

def extract_filename_from_blob_url(url: str) -> str:
    """Extract the filename from an Azure Blob URL for display."""
    try:
        parsed = urllib.parse.urlsplit(url)
        path = urllib.parse.unquote(parsed.path)
        # Get the last part of the path (filename)
        filename = path.rsplit('/', 1)[-1] if '/' in path else path
        return filename or "文件連結"
    except Exception:
        return "文件連結"

def replace_plain_blob_urls(text: str, references: Optional[Set[str]] = None) -> str:
    """
    Replace plain Azure Blob Storage URLs with Markdown links containing SAS-signed URLs.
    The display text is the filename extracted from the URL.
    """
    def replacer(match):
        raw_url = match.group(1)
        # Resolve the URL to get a SAS-signed version
        resolved_url = resolve_reference_href(raw_url)
        if resolved_url and resolved_url != raw_url:
            if references is not None:
                references.add(resolved_url)
            # Extract filename for display
            filename = extract_filename_from_blob_url(raw_url)
            logger.debug("Replaced plain blob URL '%s' -> [%s](SAS URL)", raw_url[:80], filename)
            # Return as Markdown link with filename as display text
            return f"[{filename}]({resolved_url})"
        # If we couldn't generate SAS, still wrap in markdown with filename
        filename = extract_filename_from_blob_url(raw_url)
        return f"[{filename}]({raw_url})"

    return AZURE_BLOB_URL_REGEX.sub(replacer, text)


def replace_source_reference_links(text: str, references: Optional[Set[str]] = None) -> str:
    """
    Replace source reference links in text. Links that point to non-existent blobs are completely removed.
    Also handles plain Azure Blob URLs that are not in Markdown format.
    """
    # First, handle Markdown-formatted links [text](url)
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

    text = REFERENCE_REGEX.sub(replacer, text)
    
    # Then, handle plain Azure Blob URLs that are not in Markdown format
    text = replace_plain_blob_urls(text, references)
    
    return text

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
    # Set up model selection dropdown and score threshold slider
    settings = await cl.ChatSettings(
        [
            Select(
                id="Model",
                label="LLM 模型",
                values=list(MODEL_OPTIONS.keys()),
                initial_index=0,
            ),
            Select(
                id="SearchIndex",
                label="🗂️ 知識庫",
                values=list(INDEX_OPTIONS.keys()),
                initial_index=0,
            ),
            Slider(
                id="ScoreThreshold",
                label="搜尋相關性門檻 (Score Threshold)",
                initial=0,
                min=0,
                max=0.05,
                step=0.005,
                description="0 = 不過濾 | Hybrid/Vector搜尋的RRF分數通常在0.01~0.03之間",
            ),
        ]
    ).send()
    
    # Store initial model selection in session
    initial_model_name = list(MODEL_OPTIONS.keys())[0]
    cl.user_session.set("model_deployment", MODEL_OPTIONS[initial_model_name])
    cl.user_session.set("model_display_name", initial_model_name)
    
    # Store initial index selection in session
    initial_index_name = list(INDEX_OPTIONS.keys())[0]
    cl.user_session.set("search_index", INDEX_OPTIONS[initial_index_name])
    cl.user_session.set("index_display_name", initial_index_name)
    
    # Store initial score threshold (0 = disabled)
    cl.user_session.set("score_threshold", 0)
    logger.info(f"Chat started with model: {MODEL_OPTIONS[initial_model_name]}, index: {INDEX_OPTIONS[initial_index_name]}, score_threshold: 0")


@cl.on_settings_update
async def on_settings_update(settings):
    """Handle model selection, index selection, and score threshold changes from the UI"""
    # Handle model selection
    selected_model_name = settings.get("Model")
    if selected_model_name and selected_model_name in MODEL_OPTIONS:
        model_deployment = MODEL_OPTIONS[selected_model_name]
        cl.user_session.set("model_deployment", model_deployment)
        cl.user_session.set("model_display_name", selected_model_name)
        # Store the model name for display before next message
        cl.user_session.set("pending_model_switch", selected_model_name)
        logger.info(f"User switched model to: {model_deployment} ({selected_model_name})")
    
    # Handle search index selection
    selected_index_name = settings.get("SearchIndex")
    if selected_index_name and selected_index_name in INDEX_OPTIONS:
        search_index = INDEX_OPTIONS[selected_index_name]
        cl.user_session.set("search_index", search_index)
        cl.user_session.set("index_display_name", selected_index_name)
        # Store for display notification
        cl.user_session.set("pending_index_switch", selected_index_name)
        logger.info(f"User switched index to: {search_index} ({selected_index_name})")
    
    # Handle score threshold
    score_threshold = settings.get("ScoreThreshold", 0)
    cl.user_session.set("score_threshold", float(score_threshold))
    logger.info(f"Score threshold updated to: {score_threshold}")

@cl.on_message
async def handle_message(message: cl.Message):
    
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

        # Don't send empty token here - let the status message show first
        # await response_msg.stream_token(" ")

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
        
        # Get selected model from session
        model_deployment = cl.user_session.get("model_deployment") or DEFAULT_MODEL
        logger.info(f"Using model deployment: {model_deployment}")
        
        # Get score threshold from session (0 = disabled)
        score_threshold = cl.user_session.get("score_threshold", 0)
        logger.info(f"Using score threshold: {score_threshold}")
        
        # Check if there's a pending model switch notification to show first
        pending_model_switch = cl.user_session.get("pending_model_switch")
        if pending_model_switch:
            await cl.Message(content=f"✅ 已切換至 **{pending_model_switch}** 模型").send()
            cl.user_session.set("pending_model_switch", None)  # Clear the flag
        
        # Show initial status message with dynamic timing
        status_start_time = time_module.time()
        stage_times = {}  # Track time spent in each stage
        current_stage = "thinking"
        stage_start_time = status_start_time
        timer_running = True  # Flag to control the timer task
        
        # Hourglass animation frames for realistic sand flowing effect
        # Sequence: flowing (⏳) -> done (⌛) -> flip back to flowing (⏳)
        hourglass_frames = ["⏳", "⏳", "⌛", "⌛", "⏳", "⏳"]
        hourglass_index = [0]  # Use list to allow modification in nested function
        
        def format_dynamic_status():
            """Format status message with hourglass animation"""
            # Cycle through hourglass frames
            current_hourglass = hourglass_frames[hourglass_index[0] % len(hourglass_frames)]
            hourglass_index[0] += 1
            
            lines = []
            for stage in STAGE_ORDER:
                stage_info = STATUS_MESSAGES.get(stage)
                if not stage_info:
                    continue
                icon, name = stage_info
                if stage in stage_times:
                    # Completed stage
                    lines.append(f"✓ {icon} {name}")
                elif stage == current_stage:
                    # Current active stage - show hourglass animation
                    lines.append(f"{icon} {name} {current_hourglass}")
                # Skip future stages
            
            if lines:
                return "\n".join(lines)
            return "🤔 處理中..."
        
        status_msg = cl.Message(content=format_dynamic_status())
        await status_msg.send()
        
        # Background task to update timer every 500ms
        async def update_timer():
            nonlocal timer_running
            while timer_running:
                await asyncio.sleep(0.5)  # Update every 500ms
                if timer_running and current_stage:
                    try:
                        status_msg.content = format_dynamic_status()
                        await status_msg.update()
                    except Exception as e:
                        logger.debug(f"Timer update failed: {e}")
                        break
        
        # Start the timer task
        timer_task = asyncio.create_task(update_timer())
        
        # Get search index from session
        search_index = cl.user_session.get("search_index")
        
        generator = call_orchestrator_stream(conversation_id, message.content, auth_info, message.id, model_deployment, score_threshold, search_index)

        chunk_count = 0
        first_content_seen = False
        status_removed = False

        try:
            async for chunk in generator:
                # Check for status events (e.g., [STATUS:thinking])
                status_match = STATUS_PATTERN.match(chunk)
                if status_match:
                    status_type = status_match.group(1)
                    status_info = STATUS_MESSAGES.get(status_type)
                    
                    if status_info and not status_removed:
                        # Record time for previous stage
                        now = time_module.time()
                        if current_stage and current_stage != status_type:
                            stage_times[current_stage] = now - stage_start_time
                        
                        # Update to new stage
                        current_stage = status_type
                        stage_start_time = now
                        
                        # Update status display
                        status_msg.content = format_dynamic_status()
                        await status_msg.update()
                        logger.info(f"[Status] Stage: {status_type}")
                    elif status_type == "done" and not status_removed:
                        # Final stage - record last timing
                        if current_stage:
                            stage_times[current_stage] = time_module.time() - stage_start_time
                        current_stage = None
                    continue  # Don't process status events as content

                # Check for debug events (e.g., [DEBUG:{json}])
                debug_match = DEBUG_PATTERN.match(chunk)
                if debug_match:
                    try:
                        import json
                        debug_json = debug_match.group(1)
                        debug_info = json.loads(debug_json)
                        # Store debug info for later display
                        cl.user_session.set("last_debug_info", debug_info)
                        logger.info("[Debug] Received debug info from orchestrator")
                    except json.JSONDecodeError as e:
                        logger.warning(f"[Debug] Failed to parse debug JSON: {e}")
                    continue  # Don't process debug events as content

                # Extract and update conversation ID
                extracted_id, cleaned_chunk = extract_conversation_id_from_chunk(chunk)
                if extracted_id:
                    conversation_id = extracted_id

                cleaned_chunk = cleaned_chunk.replace("\\n", "\n")

                normalized_preview = cleaned_chunk.strip().lower()
                if not first_content_seen and normalized_preview:
                    # Remove status message when actual content starts
                    if not status_removed:
                        # Stop the timer task first
                        timer_running = False
                        timer_task.cancel()
                        try:
                            await timer_task
                        except asyncio.CancelledError:
                            pass
                        await status_msg.remove()
                        status_removed = True
                        logger.info("[Status] Removed - content starting")
                    
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
            # Stop timer and remove status message on error
            timer_running = False
            timer_task.cancel()
            try:
                await timer_task
            except asyncio.CancelledError:
                pass
            if not status_removed:
                await status_msg.remove()
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
        response_msg.content = final_text
        await response_msg.update()

        logger.info(
            "Response delivered: conversation=%s question_id=%s chunks=%s characters=%s preview='%s'",
            conversation_id,
            message.id,
            chunk_count,
            len(final_text),
            _trim_for_log(final_text),
        )

        # Display debug info in side panels via hidden data element
        debug_info = cl.user_session.get("last_debug_info")
        if debug_info:
            try:
                import json
                import html
                import base64
                # Clean up the debug info - remove unnecessary nested JSON
                cleaned_debug = clean_debug_info(debug_info)
                
                # Convert to JSON and then base64 encode to avoid HTML parsing issues
                debug_json = json.dumps(cleaned_debug, ensure_ascii=False)
                debug_b64 = base64.b64encode(debug_json.encode('utf-8')).decode('ascii')
                
                # Send as hidden data with base64 encoded content
                hidden_content = f'<div class="debug-data-hidden" data-debug-b64="{debug_b64}">DEBUG_DATA</div>'
                
                debug_msg = cl.Message(
                    content=hidden_content,
                )
                await debug_msg.send()
                
                logger.info("[Debug] Debug info sent to side panels (base64 encoded)")
                # Clear the debug info after displaying
                cl.user_session.set("last_debug_info", None)
            except Exception as e:
                logger.warning(f"[Debug] Failed to send debug info: {e}")
