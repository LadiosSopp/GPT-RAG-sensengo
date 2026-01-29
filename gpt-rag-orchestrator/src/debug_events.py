"""
Debug Events Module for GPT-RAG Orchestrator

This module defines a protocol for sending debug/diagnostic information
through SSE streams to the frontend for display in debug panels.

Debug events are prefixed with [DEBUG_EVENT] and contain JSON data.
"""
import json
import time
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger("gpt_rag_orchestrator.debug_events")

class DebugEventType(Enum):
    """Types of debug events that can be sent to frontend"""
    TIMING = "timing"           # Function execution timing
    SYSTEM_PROMPT = "system_prompt"  # System prompt/instructions
    RAG_RESULT = "rag_result"    # RAG search results
    TOOL_CALL = "tool_call"     # Tool invocation details
    LLM_CALL = "llm_call"       # LLM call details
    AGENT_EVENT = "agent_event" # Agent lifecycle events
    SUMMARY = "summary"         # Overall execution summary

# Debug event prefix marker (used to identify debug events in SSE stream)
DEBUG_EVENT_PREFIX = "[DEBUG_EVENT]"
DEBUG_EVENT_SUFFIX = "[/DEBUG_EVENT]"


@dataclass
class TimingEvent:
    """Records timing for a specific operation"""
    operation: str          # Name of the operation
    duration_seconds: float # How long it took
    start_time: float       # Unix timestamp when started
    end_time: float         # Unix timestamp when ended
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass 
class SystemPromptEvent:
    """Records the system prompt sent to LLM"""
    prompt: str             # Full system prompt text
    token_estimate: int     # Estimated token count
    template_name: str      # Source template name
    context_vars: Dict[str, Any] = field(default_factory=dict)  # Variables used


@dataclass
class RAGResultEvent:
    """Records RAG search results"""
    query: str              # Search query
    result_count: int       # Number of results
    search_approach: str    # hybrid, vector, term
    duration_seconds: float # Search duration
    results: List[Dict[str, Any]] = field(default_factory=list)  # Simplified results


@dataclass
class ToolCallEvent:
    """Records a tool/function call"""
    tool_name: str          # Name of the tool
    input_params: Dict[str, Any]  # Input parameters
    output_preview: str     # Truncated output preview
    duration_seconds: float # Execution time
    success: bool           # Whether it succeeded
    error_message: Optional[str] = None


@dataclass
class LLMCallEvent:
    """Records an LLM call"""
    model: str              # Model name
    input_tokens: int       # Input token count (estimated)
    output_tokens: int      # Output token count (estimated)
    duration_seconds: float # Total duration
    streaming: bool         # Whether streaming was used


@dataclass
class AgentEvent:
    """Records agent lifecycle events"""
    event_type: str         # created, started, tool_call, completed, etc.
    agent_id: Optional[str] = None
    thread_id: Optional[str] = None
    message: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ExecutionSummary:
    """Summary of the entire execution"""
    total_duration_seconds: float
    llm_calls: int
    tool_calls: int
    rag_searches: int
    token_estimate: Dict[str, int]  # input, output, total
    timings: List[Dict[str, Any]] = field(default_factory=list)


class DebugEventCollector:
    """
    Collects debug events during request processing.
    Events can be formatted and yielded through SSE stream.
    """
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.events: List[Dict[str, Any]] = []
        self.timings: Dict[str, Dict[str, Any]] = {}
        self.start_time = time.time()
        self._pending_timers: Dict[str, float] = {}
        
    def start_timer(self, operation: str) -> None:
        """Start a timer for an operation"""
        if not self.enabled:
            return
        self._pending_timers[operation] = time.time()
        
    def stop_timer(self, operation: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[float]:
        """Stop a timer and record the timing event"""
        if not self.enabled or operation not in self._pending_timers:
            return None
            
        start_time = self._pending_timers.pop(operation)
        end_time = time.time()
        duration = end_time - start_time
        
        timing = TimingEvent(
            operation=operation,
            duration_seconds=round(duration, 3),
            start_time=start_time,
            end_time=end_time,
            metadata=metadata or {}
        )
        self.timings[operation] = asdict(timing)
        self._add_event(DebugEventType.TIMING, asdict(timing))
        return duration
        
    def record_system_prompt(self, prompt: str, template_name: str = "", context_vars: Dict = None) -> None:
        """Record the system prompt used"""
        if not self.enabled:
            return
            
        # Estimate tokens (rough: ~4 chars per token)
        token_estimate = len(prompt) // 4
        
        event = SystemPromptEvent(
            prompt=prompt,
            token_estimate=token_estimate,
            template_name=template_name,
            context_vars=context_vars or {}
        )
        self._add_event(DebugEventType.SYSTEM_PROMPT, asdict(event))
        
    def record_rag_result(
        self, 
        query: str, 
        results: List[Dict], 
        search_approach: str,
        duration_seconds: float
    ) -> None:
        """Record RAG search results"""
        if not self.enabled:
            return
            
        # Simplify results for display (truncate content)
        simplified_results = []
        for r in results[:10]:  # Max 10 results
            simplified = {
                "title": r.get("title", "")[:100],
                "link": r.get("link", ""),
                "content_preview": r.get("content", "")[:500] + ("..." if len(r.get("content", "")) > 500 else ""),
                "score": r.get("@search.score", r.get("score", None))
            }
            simplified_results.append(simplified)
            
        event = RAGResultEvent(
            query=query,
            result_count=len(results),
            search_approach=search_approach,
            duration_seconds=round(duration_seconds, 3),
            results=simplified_results
        )
        self._add_event(DebugEventType.RAG_RESULT, asdict(event))
        
    def record_tool_call(
        self,
        tool_name: str,
        input_params: Dict,
        output: str,
        duration_seconds: float,
        success: bool = True,
        error_message: str = None
    ) -> None:
        """Record a tool/function call"""
        if not self.enabled:
            return
            
        # Truncate output for display
        output_preview = str(output)[:1000] + ("..." if len(str(output)) > 1000 else "")
        
        event = ToolCallEvent(
            tool_name=tool_name,
            input_params=input_params,
            output_preview=output_preview,
            duration_seconds=round(duration_seconds, 3),
            success=success,
            error_message=error_message
        )
        self._add_event(DebugEventType.TOOL_CALL, asdict(event))
        
    def record_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        duration_seconds: float,
        streaming: bool = True
    ) -> None:
        """Record an LLM call"""
        if not self.enabled:
            return
            
        event = LLMCallEvent(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_seconds=round(duration_seconds, 3),
            streaming=streaming
        )
        self._add_event(DebugEventType.LLM_CALL, asdict(event))
        
    def record_agent_event(
        self,
        event_type: str,
        agent_id: str = None,
        thread_id: str = None,
        message: str = ""
    ) -> None:
        """Record an agent lifecycle event"""
        if not self.enabled:
            return
            
        event = AgentEvent(
            event_type=event_type,
            agent_id=agent_id,
            thread_id=thread_id,
            message=message
        )
        self._add_event(DebugEventType.AGENT_EVENT, asdict(event))
        
    def _add_event(self, event_type: DebugEventType, data: Dict[str, Any]) -> None:
        """Add an event to the collection"""
        self.events.append({
            "type": event_type.value,
            "timestamp": time.time(),
            "data": data
        })
        
    def format_event_for_stream(self, event: Dict[str, Any]) -> str:
        """Format a single event for SSE streaming"""
        return f"{DEBUG_EVENT_PREFIX}{json.dumps(event)}{DEBUG_EVENT_SUFFIX}"
        
    def get_summary(self) -> Dict[str, Any]:
        """Generate execution summary"""
        total_duration = time.time() - self.start_time
        
        llm_calls = sum(1 for e in self.events if e["type"] == DebugEventType.LLM_CALL.value)
        tool_calls = sum(1 for e in self.events if e["type"] == DebugEventType.TOOL_CALL.value)
        rag_searches = sum(1 for e in self.events if e["type"] == DebugEventType.RAG_RESULT.value)
        
        # Calculate token estimates from LLM events
        input_tokens = sum(
            e["data"].get("input_tokens", 0) 
            for e in self.events 
            if e["type"] == DebugEventType.LLM_CALL.value
        )
        output_tokens = sum(
            e["data"].get("output_tokens", 0) 
            for e in self.events 
            if e["type"] == DebugEventType.LLM_CALL.value
        )
        
        summary = ExecutionSummary(
            total_duration_seconds=round(total_duration, 3),
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            rag_searches=rag_searches,
            token_estimate={"input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens},
            timings=list(self.timings.values())
        )
        
        return {
            "type": DebugEventType.SUMMARY.value,
            "timestamp": time.time(),
            "data": asdict(summary)
        }
        
    def iter_events_for_stream(self):
        """Yield all events formatted for SSE stream"""
        for event in self.events:
            yield self.format_event_for_stream(event)
            
    def get_final_debug_block(self) -> str:
        """
        Generate a final debug block containing summary and all events.
        This is sent at the end of the stream.
        """
        summary = self.get_summary()
        
        final_block = {
            "summary": summary["data"],
            "events": self.events
        }
        
        return f"{DEBUG_EVENT_PREFIX}{json.dumps(final_block)}{DEBUG_EVENT_SUFFIX}"


def parse_debug_event(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a debug event from SSE stream text.
    Returns None if text doesn't contain a debug event.
    """
    if DEBUG_EVENT_PREFIX not in text:
        return None
        
    try:
        start_idx = text.find(DEBUG_EVENT_PREFIX) + len(DEBUG_EVENT_PREFIX)
        end_idx = text.find(DEBUG_EVENT_SUFFIX, start_idx)
        
        if end_idx == -1:
            # No end marker, assume rest of string
            json_str = text[start_idx:]
        else:
            json_str = text[start_idx:end_idx]
            
        return json.loads(json_str)
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning(f"Failed to parse debug event: {e}")
        return None


def extract_debug_events_from_text(text: str) -> tuple[str, List[Dict[str, Any]]]:
    """
    Extract all debug events from text and return cleaned text plus events.
    
    Returns:
        Tuple of (cleaned_text, list_of_debug_events)
    """
    events = []
    cleaned_text = text
    
    while DEBUG_EVENT_PREFIX in cleaned_text:
        start_idx = cleaned_text.find(DEBUG_EVENT_PREFIX)
        end_idx = cleaned_text.find(DEBUG_EVENT_SUFFIX, start_idx)
        
        if end_idx == -1:
            break
            
        # Extract the event
        event_str = cleaned_text[start_idx + len(DEBUG_EVENT_PREFIX):end_idx]
        try:
            event = json.loads(event_str)
            events.append(event)
        except json.JSONDecodeError:
            pass
            
        # Remove from cleaned text
        cleaned_text = cleaned_text[:start_idx] + cleaned_text[end_idx + len(DEBUG_EVENT_SUFFIX):]
        
    return cleaned_text.strip(), events
