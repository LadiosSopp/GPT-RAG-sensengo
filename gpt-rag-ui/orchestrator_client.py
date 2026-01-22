import os
import logging
import time
import re
from typing import Optional, Tuple

import httpx
from azure.identity import ManagedIdentityCredential, AzureCliCredential, ChainedTokenCredential

from dependencies import get_config

logger = logging.getLogger("gpt_rag_ui.orchestrator_client")
config = get_config()

# Regex pattern for status events from orchestrator
STATUS_PATTERN = re.compile(r'\[STATUS:(\w+)\]')


def _get_config_value(key: str, *, default=None, allow_none: bool = False):
    try:
        return config.get_value(key, default=default, allow_none=allow_none)
    except Exception:
        if allow_none or default is not None:
            logger.debug("Configuration key '%s' not found; using default", key)
        else:
            logger.exception("Failed to read configuration value for key '%s'", key)
        return default


def _get_orchestrator_base_url() -> Optional[str]:
    value = _get_config_value("ORCHESTRATOR_BASE_URL", default=None, allow_none=True)
    if value:
        return value.rstrip("/")
    return None


# Obtain an Azure AD token via Managed Identity or Azure CLI credentials
def get_managed_identity_token():
    credential = ChainedTokenCredential(
        ManagedIdentityCredential(),
        AzureCliCredential()
    )
    return credential.get_token("https://management.azure.com/.default").token


async def call_orchestrator_stream(conversation_id: str, question: str, auth_info: dict, question_id: str | None = None, model_deployment: str | None = None, score_threshold: float | None = None, search_index: str | None = None):    
    # Read Dapr settings and target app ID
    orchestrator_app_id = "orchestrator"
    base_url = _get_orchestrator_base_url()
    if base_url:
        url = f"{base_url}/orchestrator"
    else:
        dapr_port = _get_config_value("DAPR_HTTP_PORT", default="3500")
        url = (
            f"http://127.0.0.1:{dapr_port}/v1.0/invoke/{orchestrator_app_id}/method/orchestrator"
        )

    # Read the Dapr sidecar API token, favoring environment variables to avoid config churn
    dapr_token = os.getenv("DAPR_API_TOKEN")
    if dapr_token is None:
        dapr_token = _get_config_value("DAPR_API_TOKEN", default=None, allow_none=True)
    if not dapr_token:
        logger.debug("DAPR_API_TOKEN is not set; proceeding without Dapr token header")

    # Prepare headers: content-type and optional Dapr token
    headers = {
        "Content-Type": "application/json",
    }
    if dapr_token:
        headers["dapr-api-token"] = dapr_token

    api_key = _get_config_value("ORCHESTRATOR_APP_APIKEY", default="")
    if api_key:
        headers["X-API-KEY"] = api_key
    
    # Construct request body
    payload = {
        "conversation_id": conversation_id,
        "question": question, #for backward compatibility
        "ask": question,
        "client_principal_id": auth_info.get('client_principal_id', 'no-auth'),
        "client_principal_name": auth_info.get('client_principal_name', 'anonymous'),
        "client_group_names": auth_info.get('client_group_names', []),
        "access_token": auth_info.get('access_token')
    }

    if question_id:
        payload["question_id"] = question_id
    
    # Add model deployment if specified
    if model_deployment:
        payload["model_deployment"] = model_deployment
        logger.info("[SSE-Timing] Using model deployment: %s", model_deployment)
    
    # Add score threshold if specified (0 = disabled)
    if score_threshold is not None and score_threshold > 0:
        payload["score_threshold"] = score_threshold
        logger.info("[SSE-Timing] Using score threshold: %s", score_threshold)
    
    # Add search index if specified
    if search_index:
        payload["search_index"] = search_index
        logger.info("[SSE-Timing] Using search index: %s", search_index)

    # Timing analysis for SSE streaming
    request_start_time = time.perf_counter()
    first_chunk_time = None
    chunk_count = 0
    total_chars = 0
    last_chunk_time = request_start_time

    logger.info("[SSE-Timing] Request started at %.3f", request_start_time)

    # Invoke through Dapr sidecar and stream response
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            connection_time = time.perf_counter()
            logger.info("[SSE-Timing] Connection established in %.3fs", connection_time - request_start_time)
            
            if response.status_code >= 400:
                body = await response.aread()
                raise Exception(
                    f"Error invoking orchestrator (HTTP {response.status_code}): "
                    f"{response.reason_phrase}. Details: {body.decode(errors='ignore')}"
                )
            # Parse SSE format: each message is "data: <content>\n\n"
            async for line in response.aiter_lines():
                current_time = time.perf_counter()
                
                if line.startswith("data: "):
                    chunk = line[6:]  # Remove "data: " prefix
                    if chunk:
                        # Check for status events (e.g., [STATUS:thinking])
                        # These are forwarded to frontend for UI updates
                        status_match = STATUS_PATTERN.match(chunk)
                        if status_match:
                            status_type = status_match.group(1)
                            logger.info("[SSE-Status] Received status: %s", status_type)
                            # Yield status event as-is for frontend to handle
                            yield chunk
                            continue
                        
                        chunk_count += 1
                        total_chars += len(chunk)
                        
                        if first_chunk_time is None:
                            first_chunk_time = current_time
                            ttfb = first_chunk_time - request_start_time
                            logger.info("[SSE-Timing] TTFB (Time to First Byte): %.3fs", ttfb)
                        
                        # Log every 10th chunk or first 5 chunks for detailed analysis
                        if chunk_count <= 5 or chunk_count % 10 == 0:
                            gap = current_time - last_chunk_time
                            logger.info("[SSE-Timing] Chunk #%d: +%.3fs (gap=%.4fs, chars=%d)", 
                                       chunk_count, current_time - request_start_time, gap, len(chunk))
                        
                        last_chunk_time = current_time
                        yield chunk
                elif line.startswith("event: error"):
                    # Handle error events
                    continue
                elif line and not line.startswith("event:"):
                    # Fallback for non-SSE format (backward compatibility)
                    chunk_count += 1
                    total_chars += len(line)
                    if first_chunk_time is None:
                        first_chunk_time = current_time
                        logger.info("[SSE-Timing] TTFB (non-SSE): %.3fs", first_chunk_time - request_start_time)
                    yield line
    
    # Final timing summary
    end_time = time.perf_counter()
    total_duration = end_time - request_start_time
    streaming_duration = end_time - (first_chunk_time or end_time)
    
    logger.info("[SSE-Timing] === STREAMING SUMMARY ===")
    logger.info("[SSE-Timing] Total duration: %.3fs", total_duration)
    logger.info("[SSE-Timing] TTFB: %.3fs", (first_chunk_time - request_start_time) if first_chunk_time else 0)
    logger.info("[SSE-Timing] Streaming duration: %.3fs", streaming_duration)
    logger.info("[SSE-Timing] Total chunks: %d, Total chars: %d", chunk_count, total_chars)
    if chunk_count > 0 and streaming_duration > 0:
        logger.info("[SSE-Timing] Avg chars/chunk: %.1f, Streaming rate: %.1f chars/s", 
                   total_chars / chunk_count, total_chars / streaming_duration)



async def call_orchestrator_for_feedback(
        conversation_id: str,
        question_id: str,
        ask: str,
        is_positive: bool,
        star_rating: Optional[int | str],
        feedback_text: Optional[str],
        auth_info: dict,
    ) -> bool:
    if not question_id:
        logger.warning("call_orchestrator_for_feedback called without question_id; feedback will have null question_id")
    # Read Dapr settings and target app ID
    orchestrator_app_id = "orchestrator"
    base_url = _get_orchestrator_base_url()
    if base_url:
        url = f"{base_url}/orchestrator"
    else:
        dapr_port = _get_config_value("DAPR_HTTP_PORT", default="3500")
        url = (
            f"http://127.0.0.1:{dapr_port}/v1.0/invoke/{orchestrator_app_id}/method/orchestrator"
        )

    # Read the Dapr sidecar API token
    dapr_token = os.getenv("DAPR_API_TOKEN")
    if not dapr_token:
        logger.debug("DAPR_API_TOKEN is not set; proceeding without Dapr token header")

    # Prepare headers: content-type and optional Dapr token
    headers = {
        "Content-Type": "application/json",
    }
    if dapr_token:
        headers["dapr-api-token"] = dapr_token

    api_key = _get_config_value("ORCHESTRATOR_APP_APIKEY", default="")
    if api_key:
        headers["X-API-KEY"] = api_key

    payload = {
        "type": "feedback",
        "conversation_id": conversation_id,
        "question_id": question_id,
        "access_token": auth_info.get('access_token'),
        "is_positive": is_positive,
    }
    # Include optional fields only when provided
    if star_rating is not None:
        payload["stars_rating"] = star_rating
    if feedback_text:
        payload["feedback_text"] = feedback_text
    
    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            raise Exception(f"Error calling orchestrator for feedback. HTTP status code: {response.status_code}, status: {response.reason_phrase}")
        return True