"""
Debug data storage for GPT-RAG UI
Stores timing, prompting, RAG results, and execution details for debug panels
"""
import time
import json
import re
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gpt_rag_ui.debug_store")

# Debug event markers (must match orchestrator's debug_events.py)
DEBUG_EVENT_PREFIX = "[DEBUG_EVENT]"
DEBUG_EVENT_SUFFIX = "[/DEBUG_EVENT]"

_debug_data_store = {}


def set_debug_data(conversation_id: str, timing: dict, prompting: dict, 
                   debug_events: Optional[Dict] = None):
    """Store debug data for a conversation"""
    _debug_data_store[conversation_id] = {
        "timing": timing,
        "prompting": prompting,
        "debug_events": debug_events or {},
        "timestamp": time.time()
    }
    # Keep only last 100 entries
    if len(_debug_data_store) > 100:
        oldest = min(_debug_data_store.keys(), key=lambda k: _debug_data_store[k].get('timestamp', 0))
        del _debug_data_store[oldest]


def get_debug_data(conversation_id: str = None):
    """Get debug data, optionally filtered by conversation_id"""
    if conversation_id and conversation_id in _debug_data_store:
        return _debug_data_store[conversation_id]
    # Return most recent if no specific conversation
    if _debug_data_store:
        latest = max(_debug_data_store.keys(), key=lambda k: _debug_data_store[k].get('timestamp', 0))
        return _debug_data_store[latest]
    return None


def extract_debug_events_from_text(text: str) -> tuple[str, Optional[Dict[str, Any]]]:
    """
    Extract debug events from SSE stream text.
    
    Returns:
        Tuple of (cleaned_text, debug_data_dict)
        debug_data_dict contains 'summary' and 'events' if found
    """
    if DEBUG_EVENT_PREFIX not in text:
        return text, None
    
    debug_data = None
    cleaned_text = text
    
    while DEBUG_EVENT_PREFIX in cleaned_text:
        start_idx = cleaned_text.find(DEBUG_EVENT_PREFIX)
        end_idx = cleaned_text.find(DEBUG_EVENT_SUFFIX, start_idx)
        
        if end_idx == -1:
            # No end marker found, might be incomplete
            break
            
        # Extract the JSON content
        json_start = start_idx + len(DEBUG_EVENT_PREFIX)
        json_str = cleaned_text[json_start:end_idx]
        
        # Clean control characters that break JSON parsing
        # Replace problematic control characters with escaped versions
        json_str_cleaned = json_str.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        # Also handle any other control characters (0x00-0x1F except the ones we just escaped)
        import re as re_clean
        json_str_cleaned = re_clean.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str_cleaned)
        
        try:
            parsed = json.loads(json_str_cleaned)
            # The final debug block contains 'summary' and 'events'
            if 'summary' in parsed and 'events' in parsed:
                debug_data = parsed
            elif isinstance(parsed, dict):
                # Individual event
                if debug_data is None:
                    debug_data = {'events': []}
                if 'events' not in debug_data:
                    debug_data['events'] = []
                debug_data['events'].append(parsed)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse debug event JSON: {e}")
        
        # Remove the debug event from text
        cleaned_text = cleaned_text[:start_idx] + cleaned_text[end_idx + len(DEBUG_EVENT_SUFFIX):]
    
    return cleaned_text.strip(), debug_data


def format_debug_for_display(debug_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format debug data for display in the UI.
    
    Returns a structured dict with:
    - summary: execution summary
    - timings: list of timing info
    - system_prompt: the system prompt used
    - rag_results: RAG search results
    - tool_calls: list of tool calls
    - llm_calls: list of LLM calls
    """
    if not debug_data:
        return {}
    
    result = {
        "summary": {},
        "timings": [],
        "system_prompt": None,
        "rag_results": [],
        "tool_calls": [],
        "llm_calls": [],
        "agent_events": []
    }
    
    # Extract summary
    if 'summary' in debug_data:
        result['summary'] = debug_data['summary']
        
        # Extract timings from summary (this is where orchestrator stores them)
        summary_timings = debug_data['summary'].get('timings', [])
        for t in summary_timings:
            result['timings'].append({
                "operation": t.get('operation', ''),
                "duration": t.get('duration_seconds', 0),
                "metadata": t.get('metadata', {})
            })
    
    # Process events
    events = debug_data.get('events', [])
    for event in events:
        event_type = event.get('type', '')
        data = event.get('data', {})
        
        if event_type == 'timing':
            # Also add timing events (in case they're sent as individual events)
            result['timings'].append({
                "operation": data.get('operation', ''),
                "duration": data.get('duration_seconds', 0),
                "metadata": data.get('metadata', {})
            })
        elif event_type == 'system_prompt':
            result['system_prompt'] = {
                "prompt": data.get('prompt', ''),
                "token_estimate": data.get('token_estimate', 0),
                "template_name": data.get('template_name', ''),
                "context_vars": data.get('context_vars', {})
            }
        elif event_type == 'rag_result':
            result['rag_results'].append({
                "query": data.get('query', ''),
                "result_count": data.get('result_count', 0),
                "search_approach": data.get('search_approach', ''),
                "duration": data.get('duration_seconds', 0),
                "results": data.get('results', [])
            })
        elif event_type == 'tool_call':
            result['tool_calls'].append({
                "name": data.get('tool_name', ''),
                "duration": data.get('duration_seconds', 0),
                "success": data.get('success', True),
                "input": data.get('input_params', {}),
                "output_preview": data.get('output_preview', '')
            })
        elif event_type == 'llm_call':
            result['llm_calls'].append({
                "model": data.get('model', ''),
                "input_tokens": data.get('input_tokens', 0),
                "output_tokens": data.get('output_tokens', 0),
                "duration": data.get('duration_seconds', 0)
            })
        elif event_type == 'agent_event':
            result['agent_events'].append({
                "event_type": data.get('event_type', ''),
                "message": data.get('message', ''),
                "timestamp": data.get('timestamp', 0)
            })
    
    return result