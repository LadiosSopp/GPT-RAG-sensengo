
import logging
import json
import re
import time
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List
from pydantic import BaseModel
from dataclasses import dataclass, field, asdict

# Suppress Azure SDK HTTP logging BEFORE importing azure packages
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

from azure.ai.agents.models import (
    BingGroundingTool,
    FunctionTool,
    ListSortOrder,
    MessageDeltaChunk,
    MessageDeltaTextUrlCitationAnnotation,
    MessageTextContent,
)

from .base_agent_strategy import BaseAgentStrategy
from .agent_strategies import AgentStrategies

from dependencies import get_config
from connectors import SearchClient


# ============================================================
# Debug Info Data Classes
# ============================================================

@dataclass
class TimingInfo:
    """Timing information for each stage."""
    stage: str
    start_time: str  # ISO format timestamp
    duration_ms: float
    details: str = ""


@dataclass
class DebugInfo:
    """Complete debug information for a request."""
    request_id: str = ""
    model_name: str = ""
    system_prompt: str = ""
    user_message: str = ""
    search_debug: dict = field(default_factory=dict)
    timings: List[Dict] = field(default_factory=list)
    total_duration_ms: float = 0
    # Agent and Tool monitoring info
    agent_id: str = ""
    agent_reused: bool = False
    agent_source: str = ""  # "model_specific", "conversation", "generic", "new"
    tools_configured: List[str] = field(default_factory=list)
    tools_updated: bool = False
    # LLM stages input/output tracking
    llm_stages: List[Dict] = field(default_factory=list)  # Each stage: {stage, input, output, tool_calls}
    final_response: str = ""


# ============================================================
# Citation Processing Helper
# ============================================================

# Pre-compiled regex for citation placeholders (e.g., 【7:0†source】)
# Compiled once at module load for better performance
CITATION_PLACEHOLDER_PATTERN = re.compile(r'【(\d+):(\d+)†[^】]*】')

def truncate_title(title: str, max_length: int = 30) -> str:
    """
    Truncate title to max_length, cutting at the last space before the limit.
    
    Args:
        title: The title to truncate
        max_length: Maximum length (default 30)
        
    Returns:
        Truncated title with '...' if needed
    """
    if not title or len(title) <= max_length:
        return title
    
    # Find the last space before max_length
    truncated = title[:max_length]
    last_space = truncated.rfind(' ')
    
    if last_space > 0:
        return truncated[:last_space] + '...'
    else:
        # No space found, just truncate at max_length
        return truncated + '...'


def process_bing_citations(delta: MessageDeltaChunk) -> str:
    """
    Process Bing Grounding citations from message delta.
    Replaces placeholders like 【3:0†source】 with proper [title](url) format.
    
    Note: Only works with OpenAI/Azure OpenAI models that include url_citation
    annotations. Other models (e.g., DeepSeek) don't provide annotations,
    so placeholders are simply removed.
    
    Args:
        delta: The message delta chunk containing text and potential annotations
    """
    text = delta.text
    if not text:
        return text
    
    # Collect annotation objects from the delta
    raw = getattr(delta, "delta", None)
    annotations = []
    
    if raw:
        raw_content = getattr(raw, "content", [])
        for piece in raw_content:
            txt = getattr(piece, "text", None)
            if txt:
                anns = getattr(txt, "annotations", None)
                if anns:
                    annotations.extend(anns)
    
    # Process URL citations (used by Bing Grounding with OpenAI/Azure models)
    for ann in annotations:
        placeholder = None
        url = None
        title = None
        
        # Convert annotation to dict (handles Pydantic models, etc.)
        ann_dict = None
        if hasattr(ann, 'model_dump'):
            ann_dict = ann.model_dump()
        elif hasattr(ann, 'dict'):
            ann_dict = ann.dict()
        elif hasattr(ann, '__dict__'):
            ann_dict = ann.__dict__
        elif isinstance(ann, dict):
            ann_dict = ann
        
        if ann_dict:
            # Handle nested _data structure (Azure SDK format)
            if '_data' in ann_dict:
                ann_dict = ann_dict['_data']
            
            ann_type = ann_dict.get('type', '')
            if ann_type == 'url_citation' or 'url_citation' in ann_dict:
                placeholder = ann_dict.get('text')
                url_citation = ann_dict.get('url_citation', {})
                
                if isinstance(url_citation, dict):
                    url = url_citation.get('url')
                    title = url_citation.get('title')
                else:
                    url = getattr(url_citation, 'url', None)
                    title = getattr(url_citation, 'title', None)
        
        if not title:
            title = url
        
        if url and placeholder and placeholder in text:
            display_title = truncate_title(title, 30)
            citation = f"[{display_title}]({url})"
            text = text.replace(placeholder, citation)
    
    # Clean up citation placeholders for models that don't include annotations (e.g., DeepSeek)
    # Uses pre-compiled CITATION_PLACEHOLDER_PATTERN for better performance
    text = CITATION_PLACEHOLDER_PATTERN.sub('', text)
    
    return text


# ============================================================
# Main Strategy Class
# ============================================================

class SingleAgentRAGStrategyV1(BaseAgentStrategy):
    """
    Implements a single-agent Retrieval-Augmented Generation (RAG) strategy
    using Azure AI Foundry. This class handles creating an agent, sending
    a user message, streaming the response, and cleaning up resources.
    """

    async def create():
        """
        Factory method to create an instance of SingleAgentRAGStrategyV1.
        Initializes the agent and tools.
        """
        logging.debug("[Agent Flow] Creating SingleAgentRAGStrategyV1 instance...")
        instance = SingleAgentRAGStrategyV1()

        return instance    

    def __init__(self):
        """
        Initialize base credentials and tools.
        """
        super().__init__()

        # Force all logs at DEBUG or above to appear
        logging.debug("[Init] Initializing SingleAgentRAGStrategyV1...")

        cfg = get_config()
        self.strategy_type = AgentStrategies.SINGLE_AGENT_RAG_V1
        
        # Agent Tools Initialization Section
        # =========================================================

        # Allow the user to specify an existing agent ID (optional)
        # Use a safe default to avoid raising when key is not present
        # Support model-specific agent IDs: AGENT_ID_<model_name> (e.g., AGENT_ID_gpt5-chat)
        self.existing_agent_id = cfg.get("AGENT_ID", "") or None
        
        # Load model-specific agent IDs mapping
        self.agent_ids_by_model = {}
        for model_name in ["gpt5-chat", "gpt5-nano", "gpt5-mini", "chat", "gpt4.1-nano"]:
            agent_id = cfg.get(f"AGENT_ID_{model_name}", "") or None
            if agent_id:
                self.agent_ids_by_model[model_name] = agent_id
                logging.debug(f"[Init] Loaded agent ID for {model_name}: {agent_id}")
        
        if self.agent_ids_by_model:
            logging.info(f"[Init] Loaded {len(self.agent_ids_by_model)} model-specific agent IDs")

        # Initialize tool containers
        self.tools_list = []
        self.tool_resources = {}

        # --- Initialize SearchClient for retrieval function tool ---
        aisearch_enabled = cfg.get("SEARCH_RETRIEVAL_ENABLED", True, type=bool)
        
        if not aisearch_enabled:
            logging.warning("[Init] SEARCH_RETRIEVAL_ENABLED set to false. SearchClient Function Tool will not be available.")
            self.search_client = None
        else:
            logging.info("[Init] Setting up SearchClient and custom retrieval function tool...")
            
            # Initialize SearchClient (handles embeddings internally)
            try:
                self.search_client = SearchClient()
                logging.info("[Init] ✅ SearchClient initialized with hybrid search support")
            except Exception as e:
                logging.error("[Init] ❌ Could not initialize SearchClient: %s", e)
                raise
        
            # Use SearchClient's search_knowledge_base method as the retrieval function
            retrieval_functions = {self.search_client.search_knowledge_base}
            retrieval_tool = FunctionTool(functions=retrieval_functions)
            
            # Add retrieval function definitions to tools list
            for tool_def in retrieval_tool.definitions:
                self.tools_list.append(tool_def)
                logging.debug(f"[Init] Added retrieval function tool: {tool_def}")
            
            logging.info("[Init] Custom retrieval function tool configured successfully")

        # --- Initialize BingGroundingTool (if configured) ---
        bing_enabled = cfg.get("BING_RETRIEVAL_ENABLED", False, type=bool)
        if not bing_enabled:
            logging.warning("[Init] BING_RETRIEVAL_ENABLED set to false. BingGroundingTool will not be available.")
        else:
            bing_conn = cfg.get("BING_CONNECTION_ID", "")
            if bing_conn:
                bing = BingGroundingTool(connection_id=bing_conn, count=5)
                bing_def = bing.definitions[0]
                self.tools_list.append(bing_def)
                logging.debug(f"[Init] Added BingGroundingTool to tools_list: {bing_def}")
            else:
                logging.error("[Init] BING_CONNECTION_ID not set in App Config variables. ")            
                
        logging.debug(f"[Init] Final tools_list: {self.tools_list}")
        logging.debug(f"[Init] Final tool_resources: {self.tool_resources}")


    async def initiate_agent_flow(self, user_message: str):
        """
        Initiates the agent flow using custom retrieval function.
        
        - Uses custom search_knowledge_base function as FunctionTool
        - Function is auto-executed when agent needs to search for information
        - Optionally uses BingGroundingTool if BING_CONNECTION_ID is configured
        """
        flow_start = time.time()
        flow_start_iso = datetime.now(timezone.utc).isoformat()
        logging.debug(f"[Agent Flow] invoke_stream called with user_message: {user_message!r}")
        
        # Apply dynamic score threshold from user settings (if set)
        if self.search_client and hasattr(self, 'score_threshold') and self.score_threshold is not None:
            self.search_client.score_threshold = self.score_threshold
            logging.info(f"[Agent Flow] Applied dynamic score_threshold: {self.score_threshold}")
        
        # Apply dynamic search index if specified
        if self.search_client and hasattr(self, 'search_index') and self.search_index:
            self.search_client.index_name = self.search_index
            logging.info(f"[Agent Flow] Applied dynamic search_index: {self.search_index}")
        
        conv = self.conversation
        thread_id = conv.get("thread_id")
        agent_id = conv.get("agent_id")  # Reuse agent from conversation if exists
        
        # Initialize debug info collector
        self._debug_info = DebugInfo(
            request_id=conv.get("id", ""),
            model_name=self.model_name,
            user_message=user_message,
            timings=[]
        )
        
        # Helper function to record timing
        def record_timing(stage: str, start_time: float, details: str = ""):
            duration = round((time.time() - start_time) * 1000, 1)
            self._debug_info.timings.append({
                "stage": stage,
                "start_time": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration,
                "details": details
            })
            return duration

        async with self.project_client as project_client:
            # Step 0: Register custom retrieval function for auto-execution
            if self.search_client:
                project_client.agents.enable_auto_function_calls({self.search_client.search_knowledge_base})
            
            # Step 1: Manage thread lifecycle (create or reuse)
            step_start = time.time()
            thread = await self._get_or_create_thread(project_client, thread_id)
            conv["thread_id"] = thread.id
            record_timing("get_or_create_thread", step_start, f"Thread: {thread.id[:20]}...")

            # Step 2: Create or reuse agent (from conversation or config)
            step_start = time.time()
            agent, create_agent, system_prompt, agent_source, tools_updated = await self._get_or_create_agent(
                project_client, conversation_agent_id=agent_id
            )
            conv["agent_id"] = agent.id  # Persist for future reuse
            record_timing("get_or_create_agent", step_start, "Created new agent" if create_agent else f"Reused: {agent.id[:20]}...")
            
            # Store agent and tool monitoring info in debug info
            self._debug_info.agent_id = agent.id
            self._debug_info.agent_reused = not create_agent
            self._debug_info.agent_source = agent_source
            self._debug_info.tools_updated = tools_updated
            self._debug_info.tools_configured = [str(t.get('type', t)) if isinstance(t, dict) else str(getattr(t, 'type', t)) for t in self.tools_list]
            
            # Store system prompt in debug info
            self._debug_info.system_prompt = system_prompt

            # Step 3: Send user message to thread
            step_start = time.time()
            await self._send_user_message(project_client, thread.id, user_message)
            record_timing("send_user_message", step_start, f"Message: {len(user_message)} chars")

            # Step 4: Stream agent response (timing handled inside _stream_agent_response)
            async for chunk in self._stream_agent_response(
                project_client, agent.id, thread.id
            ):
                yield chunk

            # Step 5: Consolidate conversation history
            step_start = time.time()
            await self._consolidate_conversation_history(project_client, thread.id)
            record_timing("consolidate_history", step_start, "Fetched conversation history")

            # Step 6: Cleanup temporary agent (disabled for agent reuse optimization)
            # Keeping agent alive for faster subsequent requests
            # if create_agent:
            #     step_start = time.time()
            #     await self._cleanup_agent(project_client, agent.id)
            #     record_timing("cleanup_agent", step_start, "Deleted temporary agent")
            
            # Calculate total duration and finalize debug info
            total_duration = round((time.time() - flow_start) * 1000, 1)
            self._debug_info.total_duration_ms = total_duration
            
            # Get search debug info if available
            if self.search_client:
                search_debug = self.search_client.get_last_search_debug()
                if search_debug:
                    self._debug_info.search_debug = search_debug.model_dump()
            
            # Yield debug info as final event
            debug_json = json.dumps(asdict(self._debug_info), ensure_ascii=False)
            logging.info(f"[Agent Flow] Sending DEBUG info to frontend")
            yield f"[DEBUG:{debug_json}]"
            
            logging.info(f"[Agent Flow] Total flow time: {round(time.time() - flow_start, 2)}s")

    # ============================================================
    # Agent Flow Helper Methods (extracted from initiate_agent_flow)
    # ============================================================

    async def _get_or_create_thread(self, project_client, thread_id: Optional[str]):
        """
        Create a new thread or retrieve an existing one.
        
        Args:
            project_client: Azure AI Foundry project client
            thread_id: Existing thread ID or None
            
        Returns:
            Thread object (either newly created or retrieved)
        """
        try:
            if thread_id:
                logging.debug(f"[Agent Flow] thread_id exists; calling get(thread_id={thread_id})")
                thread = await project_client.agents.threads.get(thread_id)
                logging.info(f"[Agent Flow] Reused thread with ID: {thread.id}")
            else:
                logging.debug("[Agent Flow] thread_id not found; calling create()")
                thread = await project_client.agents.threads.create()
                logging.info(f"[Agent Flow] Created new thread with ID: {thread.id}")
            
            logging.debug(f"[Agent Flow] Stored thread.id = {thread.id}")
            return thread
        except Exception as e:
            logging.error(f"[Agent Flow] Failed to create/retrieve thread: {e}", exc_info=True)
            raise Exception(f"Thread creation failed: {str(e)}") from e

    async def _get_or_create_agent(self, project_client, conversation_agent_id: str = None):
        """
        Create a new agent or retrieve an existing one.
        
        Priority order for agent reuse:
        1. conversation_agent_id (from previous conversation turn)
        2. Model-specific agent ID from AGENT_ID_<model_name>
        3. self.existing_agent_id (from AGENT_ID env var - fallback)
        4. Create new agent
        
        Args:
            project_client: Azure AI Foundry project client
            conversation_agent_id: Agent ID from conversation (for reuse)
            
        Returns:
            Tuple of (agent, create_agent_flag, system_prompt, agent_source, tools_updated)
        """
        create_agent = False
        instructions = ""
        agent_source = "new"
        tools_updated = False
        
        # Determine which agent_id to use
        # Priority: model-specific > conversation (only if model matches) > generic fallback
        # This ensures model switch always uses the correct agent
        model_specific_agent_id = self.agent_ids_by_model.get(self.model_name)
        
        # If we have a model-specific agent ID, use it (ignore conversation agent for cross-model consistency)
        if model_specific_agent_id:
            reuse_agent_id = model_specific_agent_id
            agent_source = "model_specific"
            logging.info(f"[Agent Flow] Using model-specific agent for {self.model_name}: {model_specific_agent_id}")
        elif conversation_agent_id:
            # Fallback to conversation agent only if no model-specific agent exists
            reuse_agent_id = conversation_agent_id
            agent_source = "conversation"
            logging.debug(f"[Agent Flow] Using conversation agent: {conversation_agent_id}")
        else:
            # Ultimate fallback to generic AGENT_ID
            reuse_agent_id = self.existing_agent_id
            if reuse_agent_id:
                agent_source = "generic"
                logging.debug(f"[Agent Flow] Using generic agent: {reuse_agent_id}")
        
        try:
            if reuse_agent_id:
                try:
                    logging.debug(f"[Agent Flow] Attempting to reuse agent: {reuse_agent_id}")
                    agent = await project_client.agents.get_agent(reuse_agent_id)
                    instructions = getattr(agent, 'instructions', '') or ''
                    
                    # Always update agent tools to ensure correct configuration
                    # This fixes issues where agent has wrong or outdated tools
                    existing_tools = getattr(agent, 'tools', []) or []
                    existing_tool_count = len(existing_tools) if existing_tools else 0
                    required_tool_count = len(self.tools_list) if self.tools_list else 0
                    
                    logging.debug(f"[Agent Flow] Existing tools: {existing_tool_count}, Required: {required_tool_count}")
                    
                    # Always update tools to ensure they match current configuration
                    if self.tools_list:
                        logging.info(f"[Agent Flow] 🔧 Updating agent tools: {existing_tool_count} -> {required_tool_count}")
                        try:
                            # Only pass tool_resources if it's not empty
                            update_kwargs = {
                                "agent_id": agent.id,
                                "tools": self.tools_list,
                            }
                            if self.tool_resources:
                                update_kwargs["tool_resources"] = self.tool_resources
                            
                            agent = await project_client.agents.update_agent(**update_kwargs)
                            tools_updated = True
                            logging.info(f"[Agent Flow] ✅ Agent tools updated: {agent.id}")
                        except Exception as update_err:
                            logging.warning(f"[Agent Flow] ⚠️ Failed to update agent tools: {update_err}")
                            # Continue with existing agent even if tool update fails
                    
                    logging.info(f"[Agent Flow] ✅ Reused existing agent: {agent.id}")
                    return agent, False, instructions, agent_source, tools_updated
                except Exception as e:
                    logging.warning(f"[Agent Flow] ⚠️ Could not reuse agent {reuse_agent_id}: {e}")
                    logging.info("[Agent Flow] Creating new agent instead...")
                    agent_source = "new"  # Reset to new since reuse failed
            
            # Create new agent
            logging.debug("[Agent Flow] Creating new agent...")
            cfg = get_config()
            bing_enabled = bool(cfg.get("BING_CONNECTION_ID", ""))
            aisearch_enabled = cfg.get("SEARCH_RETRIEVAL_ENABLED", True, type=bool)
            
            prompt_context = {
                "strategy": self.strategy_type.value,
                "user_context": self.user_context or {},
                "bing_grounding_enabled": bing_enabled,
                "aisearch_enabled": aisearch_enabled,
            }

            instructions = await self._read_prompt(
                "main",
                use_jinja2=True,
                jinja2_context=prompt_context,
            )
            
            agent = await project_client.agents.create_agent(
                model=self.model_name,
                name="gpt-rag-agent",
                instructions=instructions,
                tools=self.tools_list,
                tool_resources=self.tool_resources
            )
            create_agent = True
            agent_source = "new"
            logging.info(f"[Agent Flow] ✅ Created new agent: {agent.id}")
            
            return agent, create_agent, instructions, agent_source, tools_updated
        except Exception as e:
            logging.error(f"[Agent Flow] Failed to create/retrieve agent: {e}", exc_info=True)
            raise Exception(f"Agent creation failed: {str(e)}") from e

    async def _send_user_message(self, project_client, thread_id: str, user_message: str):
        """
        Send user message to the thread.
        
        Args:
            project_client: Azure AI Foundry project client
            thread_id: Target thread ID
            user_message: User's message text
        """
        try:
            logging.debug(f"[Agent Flow] Sending user message into thread {thread_id}: {user_message!r}")
            await project_client.agents.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_message
            )
            logging.debug("[Agent Flow] User message sent.")
        except Exception as e:
            logging.error(f"[Agent Flow] Failed to send message to thread {thread_id}: {e}", exc_info=True)
            raise Exception(f"Message sending failed: {str(e)}") from e

    async def _stream_agent_response(self, project_client, agent_id: str, thread_id: str):
        """
        Stream agent response with citation processing.
        Captures Bing Grounding results to map citations for models that don't include annotations.
        Sends status events to frontend for user feedback during long operations.
        Collects timing information for debug display.
        """
        try:
            stream_start = time.time()
            stream_start_iso = datetime.now(timezone.utc).isoformat()
            tool_start = None
            tool_start_iso = None
            response_start = None
            response_start_iso = None
            delta_count = 0
            total_chars = 0
            last_event_time = stream_start
            event_count = 0
            last_status = None  # Track last sent status to avoid duplicates
            response_chunks = []  # Collect response chunks for debug info
            
            # Phase tracking for accurate timing
            current_phase = "stream_start"
            phase_start = stream_start
            phase_start_iso = stream_start_iso
            thinking_count = 0  # Track multiple thinking phases
            
            def record_phase_end(phase_name: str, details: str = ""):
                """Record the end of a phase and calculate duration."""
                nonlocal phase_start, phase_start_iso
                duration = round((time.time() - phase_start) * 1000, 1)
                self._debug_info.timings.append({
                    "stage": phase_name,
                    "start_time": phase_start_iso,
                    "duration_ms": duration,
                    "details": details
                })
                return duration
            
            def start_new_phase():
                """Start a new phase timer."""
                nonlocal phase_start, phase_start_iso
                phase_start = time.time()
                phase_start_iso = datetime.now(timezone.utc).isoformat()
            
            # Add initial timing (0ms for stream start marker)
            self._debug_info.timings.append({
                "stage": "stream_start",
                "start_time": stream_start_iso,
                "duration_ms": 0,
                "details": "Agent run stream initiated"
            })
            
            async with await project_client.agents.runs.stream(
                thread_id=thread_id,
                agent_id=agent_id
            ) as stream:
                async for event_type, event_data, raw in stream:
                    current_time = time.time()
                    event_count += 1
                    gap = round(current_time - last_event_time, 3)
                    elapsed = round(current_time - stream_start, 3)
                    
                    # Log ALL events for detailed analysis
                    logging.info(f"[Stream-Event] #{event_count} +{elapsed}s (gap={gap}s) type={event_type}")
                    
                    last_event_time = current_time
                    
                    # === Send status events to frontend ===
                    # Status format: [STATUS:status_type] - will be parsed by frontend
                    
                    # When run starts - LLM is thinking
                    if event_type == "thread.run.in_progress" and last_status != "thinking":
                        # Record previous phase if any meaningful time passed
                        if current_phase == "stream_start":
                            api_wait = round((current_time - stream_start) * 1000, 1)
                            if api_wait > 100:  # Only record if > 100ms
                                self._debug_info.timings.append({
                                    "stage": "api_init",
                                    "start_time": stream_start_iso,
                                    "duration_ms": api_wait,
                                    "details": "API connection and initialization"
                                })
                        
                        thinking_count += 1
                        current_phase = f"llm_thinking_{thinking_count}"
                        start_new_phase()
                        last_status = "thinking"
                        yield "[STATUS:thinking]"
                    
                    # Track tool execution time
                    if event_type == "thread.run.step.created":
                        step_type = getattr(event_data, 'type', 'unknown')
                        step_type_str = str(step_type).lower()
                        logging.info(f"[Stream-Event] Step created: {step_type}")
                        if "tool" in step_type_str:
                            # Record the thinking phase that just ended
                            if current_phase.startswith("llm_thinking"):
                                record_phase_end(current_phase, f"LLM thinking phase {thinking_count}")
                            
                            tool_start = time.time()
                            tool_start_iso = datetime.now(timezone.utc).isoformat()
                            current_phase = "tool_execution"
                            start_new_phase()
                            # LLM decided to call a tool - send searching status
                            if last_status != "searching":
                                last_status = "searching"
                                logging.info("[Stream-Event] Sending STATUS:searching")
                                yield "[STATUS:searching]"
                    
                    if event_type == "thread.run.step.completed":
                        step_type = getattr(event_data, 'type', 'unknown')
                        step_type_str = str(step_type).lower()
                        if "tool" in step_type_str and tool_start:
                            tool_duration = round((time.time() - tool_start) * 1000, 1)
                            step_details = getattr(event_data, 'step_details', None)
                            tool_name = "unknown"
                            tool_calls_info = []
                            if step_details:
                                for tc in getattr(step_details, 'tool_calls', []):
                                    tool_type = getattr(tc, 'type', 'unknown')
                                    tool_name = str(tool_type)
                                    logging.info(f"[Stream] Tool executed: {tool_type} ({round(tool_duration/1000, 2)}s)")
                                    
                                    # Capture tool call details for debug info
                                    tc_info = {
                                        "type": str(tool_type),
                                        "id": getattr(tc, 'id', ''),
                                    }
                                    # Try to get function call details
                                    if hasattr(tc, 'function'):
                                        func = tc.function
                                        tc_info["function_name"] = getattr(func, 'name', '')
                                        tc_info["arguments"] = getattr(func, 'arguments', '')[:500] if getattr(func, 'arguments', '') else ''
                                        tc_info["output"] = getattr(func, 'output', '')[:1000] if getattr(func, 'output', '') else ''
                                    tool_calls_info.append(tc_info)
                            
                            # Add to LLM stages for debug display
                            self._debug_info.llm_stages.append({
                                "stage": "tool_execution",
                                "tool_name": tool_name,
                                "tool_calls": tool_calls_info,
                                "duration_ms": tool_duration
                            })
                            
                            # Record tool timing
                            record_phase_end("tool_execution", f"Tool: {tool_name}")
                                        
                            tool_start = None
                            tool_start_iso = None
                            
                            # Mark that we're waiting for next phase (could be thinking or response)
                            current_phase = "post_tool"
                            start_new_phase()
                            
                            # Tool completed, now generating response
                            if last_status != "generating":
                                last_status = "generating"
                                logging.info("[Stream-Event] Sending STATUS:generating")
                                yield "[STATUS:generating]"
                        elif "message" in step_type_str and response_start:
                            # Record response generation phase
                            record_phase_end("response_generation", f"Generated {total_chars} characters")
                            logging.info(f"[Stream] Response generated, {total_chars} chars")
                    
                    # Track response generation time
                    if event_type == "thread.run.step.created":
                        step_type = getattr(event_data, 'type', 'unknown')
                        step_type_str = str(step_type).lower()
                        if "message" in step_type_str:
                            # Record the phase that just ended (thinking or post_tool)
                            if current_phase.startswith("llm_thinking"):
                                record_phase_end(current_phase, f"LLM thinking phase {thinking_count}")
                            elif current_phase == "post_tool":
                                # Record post-tool processing time as thinking
                                thinking_count += 1
                                record_phase_end(f"llm_thinking_{thinking_count}", f"LLM processing tool results")
                            
                            response_start = time.time()
                            response_start_iso = datetime.now(timezone.utc).isoformat()
                            current_phase = "response_generation"
                            start_new_phase()
                            # About to generate response
                            if last_status != "generating":
                                last_status = "generating"
                                logging.info("[Stream-Event] Sending STATUS:generating (message creation)")
                                yield "[STATUS:generating]"
                    
                    # Stream message deltas with citation processing
                    if event_type == "thread.message.delta" and hasattr(event_data, "text"):
                        chunk = event_data.text
                        delta_count += 1
                        total_chars += len(chunk) if chunk else 0
                        
                        # Collect chunks for debug info (limit to first 2000 chars)
                        if chunk and sum(len(c) for c in response_chunks) < 2000:
                            response_chunks.append(chunk)
                        
                        # Clear status once we start receiving actual content
                        if last_status and delta_count == 1:
                            last_status = None
                            yield "[STATUS:done]"
                        
                        # Log every delta for debugging streaming granularity
                        logging.debug(f"[Stream] Delta #{delta_count}: {len(chunk) if chunk else 0} chars")
                        
                        # Only process citations if chunk contains citation placeholder character
                        # This avoids unnecessary regex/annotation processing for most chunks
                        if chunk and '【' in chunk:
                            chunk = process_bing_citations(event_data)
                        
                        # Remove markdown strikethrough syntax (~~text~~) that causes rendering issues
                        if chunk and '~~' in chunk:
                            chunk = chunk.replace('~~', '')
                        
                        if not chunk:
                            chunk = raw or ""
                        if chunk:
                            yield chunk
                    
                    # Handle run failure
                    if event_type == "thread.run.failed":
                        last_error = event_data.last_error
                        err_code = getattr(last_error, 'code', 'unknown')
                        err_msg = getattr(last_error, 'message', 'No message')
                        logging.error(f"[Stream] Run failed - Code: {err_code}, Message: {err_msg}")
                        logging.error(f"[Stream] Full error object: {last_error}")
                        raise Exception(f"Agent failed ({err_code}): {err_msg}")
                
                # Log streaming statistics
                if response_start:
                    response_time = round(time.time() - response_start, 2)
                    chars_per_sec = round(total_chars / response_time, 1) if response_time > 0 else 0
                    logging.info(f"[Stream] Response generated in {response_time}s, deltas={delta_count}, chars={total_chars}, rate={chars_per_sec} chars/s")
                    
                    # Add response stage to llm_stages
                    full_response = ''.join(response_chunks)
                    self._debug_info.final_response = full_response[:2000] + ('...' if len(full_response) > 2000 else '')
                    self._debug_info.llm_stages.append({
                        "stage": "response_generation",
                        "output": self._debug_info.final_response,
                        "total_chars": total_chars,
                        "duration_ms": round(response_time * 1000, 1)
                    })
                    
                logging.info(f"[Stream] Total streaming time: {round(time.time() - stream_start, 2)}s")
                
        except Exception as e:
            logging.error(f"[Orchestrator] Streaming failed: {e}", exc_info=True)
            raise Exception(f"Agent response streaming failed: {str(e)}") from e

    async def _consolidate_conversation_history(self, project_client, thread_id: str):
        """
        Fetch and consolidate conversation history from thread.
        
        Args:
            project_client: Azure AI Foundry project client
            thread_id: Thread ID to fetch history from
        """
        try:
            logging.debug("[Orchestrator] Fetching conversation history from thread...")
            conv = self.conversation
            conv["messages"] = []
            
            messages = project_client.agents.messages.list(
                thread_id=thread_id,
                order=ListSortOrder.ASCENDING
            )
            
            msg_count = 0
            total_chars = 0
            async for msg in messages:
                # Defensive check: skip messages with empty or missing content
                if not msg.content:
                    logging.debug(f"[Orchestrator] Skipping message {msg.id} with empty content")
                    continue
                
                # Debug: Log message structure to understand different model formats
                logging.debug(f"[Orchestrator] Message {msg.id}: role={msg.role}, content_items={len(msg.content)}")
                
                last_content = msg.content[-1]
                logging.debug(f"[Orchestrator] Last content type: {type(last_content).__name__}")
                
                if isinstance(last_content, MessageTextContent):
                    text_obj = last_content.text
                    text_val = text_obj.value
                    
                    # Debug: Check for annotations in the final message (may contain citations)
                    annotations = getattr(text_obj, 'annotations', None)
                    if annotations:
                        logging.debug(f"[Orchestrator] Found {len(annotations)} annotations in message {msg.id}")
                        for i, ann in enumerate(annotations):
                            logging.debug(f"[Orchestrator] Annotation {i}: {ann}")
                    else:
                        logging.debug(f"[Orchestrator] No annotations in message {msg.id}")
                    
                    msg_count += 1
                    total_chars += len(text_val)
                    
                    conv["messages"].append({
                        "role": msg.role,
                        "text": text_val
                    })
            
            logging.info(f"[Orchestrator] Retrieved {msg_count} messages ({total_chars:,} chars total)")

            if self.user_context:
                conv['user_context'] = self.user_context
        except Exception as e:
            logging.error(f"[Orchestrator] Failed to consolidate conversation history for thread {thread_id}: {e}", exc_info=True)
            # Don't raise here - conversation history is non-critical, log and continue

    async def _cleanup_agent(self, project_client, agent_id: str):
        """
        Delete temporary agent after completion.
        
        Args:
            project_client: Azure AI Foundry project client
            agent_id: Agent ID to delete
        """
        try:
            logging.debug(f"[Agent Flow] Deleting agent with ID: {agent_id}")
            await project_client.agents.delete_agent(agent_id)
            logging.debug("[Agent Flow] Agent deletion complete.")
        except Exception as e:
            logging.error(f"[Agent Flow] Failed to delete agent {agent_id}: {e}", exc_info=True)
            # Don't raise here - cleanup failure is non-critical, log and continue