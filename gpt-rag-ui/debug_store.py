"""
Debug data storage for GPT-RAG UI
Stores timing and prompting information for debug panels
"""
import time

_debug_data_store = {}

def set_debug_data(conversation_id: str, timing: dict, prompting: dict):
    """Store debug data for a conversation"""
    _debug_data_store[conversation_id] = {
        "timing": timing,
        "prompting": prompting,
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
