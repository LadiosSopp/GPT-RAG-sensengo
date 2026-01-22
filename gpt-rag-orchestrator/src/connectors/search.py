import aiohttp
import logging
import json
import re
import time
from typing import Optional, Any, Dict, List
from pydantic import BaseModel

from dependencies import get_config


def clean_content_for_llm(content: str) -> str:
    """
    Clean content by removing unnecessary format tags to reduce token usage
    and improve LLM response speed.
    
    Removes:
    - HTML tags (<p>, <div>, <span>, <br>, etc.)
    - Markdown headers (###, ##, #)
    - Markdown formatting (**, __, ~~, etc.)
    - Excessive whitespace and newlines
    - Common JSON artifacts
    
    Args:
        content: Raw content from search results
        
    Returns:
        Cleaned content with reduced formatting
    """
    if not content:
        return content
    
    # Remove HTML tags
    cleaned = re.sub(r'<[^>]+>', ' ', content)
    
    # Remove Markdown headers
    cleaned = re.sub(r'^#{1,6}\s+', '', cleaned, flags=re.MULTILINE)
    
    # Remove Markdown bold/italic/strikethrough
    cleaned = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', cleaned)
    cleaned = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', cleaned)
    cleaned = re.sub(r'~~([^~]+)~~', r'\1', cleaned)
    
    # Remove Markdown code blocks markers but keep content
    cleaned = re.sub(r'```[a-z]*\n?', '', cleaned)
    cleaned = re.sub(r'`([^`]+)`', r'\1', cleaned)
    
    # Remove Markdown links but keep text
    cleaned = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cleaned)
    
    # Remove Markdown image syntax
    cleaned = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', cleaned)
    
    # Remove Markdown list markers
    cleaned = re.sub(r'^\s*[-*+]\s+', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^\s*\d+\.\s+', '', cleaned, flags=re.MULTILINE)
    
    # Remove XML-like tags (common in some document formats)
    cleaned = re.sub(r'<\/?(?:json|data|content|metadata|document)>', '', cleaned, flags=re.IGNORECASE)
    
    # Remove horizontal rules
    cleaned = re.sub(r'^[-*_]{3,}\s*$', '', cleaned, flags=re.MULTILINE)
    
    # Collapse multiple whitespace/newlines into single space
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # Remove leading/trailing whitespace
    cleaned = cleaned.strip()
    
    return cleaned


class SearchResult(BaseModel):
    """Represents a single search result from AI Search."""
    title: str
    link: str
    content: str
    score: float = 0.0  # Search relevance score from AI Search


class SearchDebugInfo(BaseModel):
    """Debug information for search operations."""
    query: str
    index_name: str
    search_approach: str
    top_k: int
    embeddings_time_ms: float
    search_time_ms: float
    total_time_ms: float
    results_count: int
    score_threshold: float = 0.0  # Score threshold (0 = disabled)
    filtered_count: int = 0  # Number of results filtered by score threshold
    search_body: dict = {}
    results_preview: list = []  # Truncated content for display with scores
    tool_output: str = ""  # The full JSON string sent to LLM as tool result


class SearchClient:
    """
    Azure Cognitive Search client with hybrid search support.
    
    Handles:
    - Basic search operations (term, vector, hybrid)
    - Document retrieval by ID
    - Token acquisition and authentication
    - Embeddings generation for vector search
    """
    def __init__(self, index_name: str = None):
        """
        Initialize SearchClient with configuration.
        
        Args:
            index_name: Optional override for the search index name. If not provided,
                       uses SEARCH_RAG_INDEX_NAME from config.
        """
        # ==== Load all config parameters in one place ====
        self.cfg = get_config()
        self.endpoint = self.cfg.get("SEARCH_SERVICE_QUERY_ENDPOINT")
        self.api_version = self.cfg.get("AZURE_SEARCH_API_VERSION", "2024-07-01")
        self.credential = self.cfg.aiocredential
        
        # Hybrid search configuration
        self.search_top_k = int(self.cfg.get('SEARCH_RAGINDEX_TOP_K', 3))
        self.search_approach = self.cfg.get('SEARCH_APPROACH', 'hybrid')
        self.semantic_search_config = self.cfg.get('SEARCH_SEMANTIC_SEARCH_CONFIG', 'my-semantic-config')
        self.search_service = self.cfg.get('SEARCH_SERVICE_NAME')
        self.use_semantic = self.cfg.get('SEARCH_USE_SEMANTIC', 'false').lower() == 'true'
        # Use provided index_name or fall back to config
        self.index_name = index_name or self.cfg.get("SEARCH_RAG_INDEX_NAME", "ragindex")
        
        # Score threshold: only return results with score >= threshold (0 = disabled)
        self.score_threshold = float(self.cfg.get('SEARCH_SCORE_THRESHOLD', 0))
        
        # Initialize GenAIModelClient for embeddings (only if needed for vector/hybrid search)
        self.aoai_client = None
        if self.search_approach in ["vector", "hybrid"]:
            try:
                from connectors.aifoundry import GenAIModelClient
                self.aoai_client = GenAIModelClient()
                logging.info("[SearchClient] ✅ GenAIModelClient initialized for embeddings")
            except Exception as e:
                logging.warning("[SearchClient] ⚠️ Could not initialize GenAIModelClient for embeddings: %s", e)
                logging.warning("[SearchClient] ⚠️ Falling back to term search only")
                self.search_approach = "term"
        # ==== End config block ====

        if not self.endpoint:
            raise ValueError("SEARCH_SERVICE_QUERY_ENDPOINT not set in config")
        
        logging.info("[SearchClient] ✅ Initialized with hybrid search support")
        logging.info("[SearchClient]    Index: %s", self.index_name)
        logging.info("[SearchClient]    Approach: %s", self.search_approach)
        logging.info("[SearchClient]    Top K: %s", self.search_top_k)
        logging.info("[SearchClient]    Score Threshold: %s", self.score_threshold if self.score_threshold > 0 else "disabled")

    async def search(self, index_name: str, body: dict) -> dict:
        """
        Executes a search POST against /indexes/{index_name}/docs/search.
        """
        url = (
            f"{self.endpoint}"
            f"/indexes/{index_name}/docs/search"
            f"?api-version={self.api_version}"
        )

        # get bearer token
        try:
            token = (await self.credential.get_token("https://search.azure.com/.default")).token
        except Exception:
            logging.exception("[search] failed to acquire token")
            raise

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logging.error(f"[search] {resp.status} {text}")
                    raise RuntimeError(f"Search failed: {resp.status} {text}")
                return await resp.json()

    async def get_document(self, index_name: str, document_id: str, select_fields: list = None) -> dict:
        """
        Retrieves a single document by ID from the index.
        GET /indexes/{index_name}/docs/{document_id}
        
        Args:
            index_name: Name of the search index
            document_id: Document key/ID
            select_fields: Optional list of fields to retrieve (e.g., ['filepath', 'title'])
            
        Returns:
            Document dictionary with requested fields
        """
        # Build URL with optional $select parameter
        url = (
            f"{self.endpoint}"
            f"/indexes/{index_name}/docs('{document_id}')"
            f"?api-version={self.api_version}"
        )
        
        if select_fields:
            fields_str = ",".join(select_fields)
            url += f"&$select={fields_str}"
        
        # Get bearer token
        try:
            token = (await self.credential.get_token("https://search.azure.com/.default")).token
        except Exception:
            logging.exception("[search] failed to acquire token for get_document")
            raise

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                text = await resp.text()
                if resp.status == 404:
                    logging.warning(f"[search] Document not found: {document_id}")
                    return None
                if resp.status >= 400:
                    logging.error(f"[search] {resp.status} {text}")
                    raise RuntimeError(f"Get document failed: {resp.status} {text}")
                return await resp.json()

    async def search_knowledge_base(self, query: str) -> str:
        """
        Searches the knowledge base for relevant documents using hybrid search.
        
        :param query: The search query to find relevant documents.
        :return: Search results as a JSON string containing a list of documents with title, link and content.
        """
        
        total_start = time.time()
        logging.info(f"[Retrieval] ========== SEARCH START ==========")
        logging.info(f"[Retrieval] AI Search index: {self.index_name}")
        logging.info(f"[Retrieval] Search approach: {self.search_approach}")
        logging.info(f"[Retrieval] Top K: {self.search_top_k}")
        logging.info(f"[Retrieval] Executing search for query: {query}")

        try:
            logging.info("[Retrieval] Using Azure AI Search for document retrieval")
            
            # Build search body according to search approach
            search_body: Dict[str, Any] = {
                "select": "title,content,url,filepath,chunk_id",
                "top": self.search_top_k
            }
            
            # Generate embeddings for vector/hybrid search
            embeddings_time = 0
            if self.search_approach in ["vector", "hybrid"] and self.aoai_client:
                embeddings_start = time.time()
                logging.info(f"[Retrieval] ⏱️ Generating embeddings for query...")
                embeddings_query = await self.aoai_client.get_embeddings(query)
                embeddings_time = round(time.time() - embeddings_start, 3)
                logging.info(f"[Retrieval] ⏱️ Embeddings generated in {embeddings_time}s")
                
                if self.search_approach == "vector":
                    search_body["vectorQueries"] = [{
                        "kind": "vector",
                        "vector": embeddings_query,
                        "fields": "contentVector",
                        "k": self.search_top_k
                    }]
                elif self.search_approach == "hybrid":
                    search_body["search"] = query
                    search_body["vectorQueries"] = [{
                        "kind": "vector",
                        "vector": embeddings_query,
                        "fields": "contentVector",
                        "k": self.search_top_k
                    }]
            else:
                # Term search only
                search_body["search"] = query
            
            # Execute search with timing
            search_start = time.time()
            logging.info(f"[Retrieval] ⏱️ Executing AI Search query...")
            search_results = await self.search(
                index_name=self.index_name,
                body=search_body
            )
            search_time = round(time.time() - search_start, 3)
            logging.info(f"[Retrieval] ⏱️ AI Search query completed in {search_time}s")
            
            # Process search results with score threshold filtering
            process_start = time.time()
            results_list = []
            filtered_count = 0
            raw_results = search_results.get('value', [])
            
            # Log all raw scores for debugging (INFO level to see in production)
            raw_scores = [f"{r.get('@search.score', 0):.6f}" for r in raw_results]
            logging.info(f"[Retrieval] Raw scores from AI Search: {raw_scores}")
            
            for result in raw_results:
                # Get the search score (BM25 or hybrid RRF score)
                score = result.get('@search.score', 0) or 0
                
                # Apply score threshold filtering if enabled
                if self.score_threshold > 0 and score < self.score_threshold:
                    filtered_count += 1
                    logging.info(f"[Retrieval] ⛔ Filtered: score={score:.6f} < threshold={self.score_threshold}")
                    continue
                
                title = result.get('title', 'reference') or 'reference'
                # Prefer 'url' (full blob URL) over 'filepath' (just filename) for valid download links
                link = result.get('url') or result.get('filepath', '') or ''
                raw_content = result.get('content', '')
                
                # Clean content to remove unnecessary format tags and reduce token usage
                content = clean_content_for_llm(raw_content)
                
                # Log cleaning stats for debugging
                if len(raw_content) != len(content):
                    reduction = round((1 - len(content) / len(raw_content)) * 100, 1) if raw_content else 0
                    logging.debug(f"[Retrieval] Content cleaned: {len(raw_content)} -> {len(content)} chars ({reduction}% reduction)")
                
                # Debug log each document with formatted output (remove line breaks)
                content_preview = content[:200] if len(content) > 200 else content
                content_preview = ' '.join(content_preview.split())  # Replace all whitespace/newlines with single space
                logging.debug(f"[Retrieval] ✅ Document (score={score:.6f}): [{title}]({link}): {content_preview}")
                
                search_result = SearchResult(
                    title=title,
                    link=link,
                    content=content,
                    score=score
                )
                results_list.append(search_result.model_dump())
            
            process_time = round(time.time() - process_start, 3)
            total_time = round(time.time() - total_start, 3)
            
            logging.info(f"[Retrieval] ========== SEARCH COMPLETE ==========")
            logging.info(f"[Retrieval] ⏱️ TIMING BREAKDOWN:")
            logging.info(f"[Retrieval]    Embeddings: {embeddings_time}s")
            logging.info(f"[Retrieval]    AI Search:  {search_time}s")
            logging.info(f"[Retrieval]    Processing: {process_time}s")
            logging.info(f"[Retrieval]    TOTAL:      {total_time}s")
            
            # Log results with score threshold info
            if self.score_threshold > 0:
                logging.info(f"[Retrieval] Found {len(raw_results)} results, {filtered_count} filtered by score threshold ({self.score_threshold}), returning {len(results_list)}")
            else:
                logging.info(f"[Retrieval] Found {len(results_list)} results from Azure AI Search")
            
            # Build debug info for frontend display
            # Create search_body for display (without vector to reduce size)
            search_body_display = {k: v for k, v in search_body.items() if k != "vectorQueries"}
            if "vectorQueries" in search_body:
                search_body_display["vectorQueries"] = "[vector data omitted]"
            
            # Create results preview (truncated content with score)
            results_preview = []
            for r in results_list[:5]:  # Max 5 for display
                results_preview.append({
                    "title": r["title"],
                    "link": r["link"],
                    "score": round(r.get("score", 0), 6),  # 6 decimal places for RRF scores
                    "content_preview": r["content"][:300] + "..." if len(r["content"]) > 300 else r["content"]
                })
            
            # Store debug info in instance for strategy to retrieve
            tool_output_json = json.dumps({"results": results_list, "query": query}, ensure_ascii=False)
            self._last_search_debug = SearchDebugInfo(
                query=query,
                index_name=self.index_name,
                search_approach=self.search_approach,
                top_k=self.search_top_k,
                embeddings_time_ms=round(embeddings_time * 1000, 1),
                search_time_ms=round(search_time * 1000, 1),
                total_time_ms=round(total_time * 1000, 1),
                results_count=len(results_list),
                score_threshold=self.score_threshold,
                filtered_count=filtered_count,
                search_body=search_body_display,
                results_preview=results_preview,
                tool_output=tool_output_json
            )
            
            return tool_output_json
            
        except Exception as e:
            logging.error(f"[Retrieval] Azure AI Search failed: {e}", exc_info=True)
            logging.warning("[Retrieval] Falling back to mock results")


    async def fetch_filepath_from_index(self, document_id: str) -> Optional[str]:
        """
        Fetch filepath directly from Azure AI Search index using document ID.
        
        Args:
            document_id: Document ID from Azure Search
            
        Returns:
            Filepath string from the index, or None if not found
        """
        try:
            logging.info("[Citations] 🔍 Fetching filepath from index for document_id: %s", document_id)
            
            document = await self.get_document(
                index_name=self.index_name,
                document_id=document_id,
                select_fields=['filepath', 'title']
            )
            
            if document:
                filepath = document.get('filepath')
                if filepath:
                    logging.info("[Citations] ✅ Found filepath in index: %s", filepath)
                    return filepath
                else:
                    logging.warning("[Citations] ⚠️ Document found but 'filepath' field is empty")
            else:
                logging.warning("[Citations] ⚠️ Document not found with ID: %s", document_id)
                
        except Exception as e:
            logging.error("[Citations] ❌ Error fetching document from index: %s", e, exc_info=True)
        
        return None
    def get_last_search_debug(self) -> Optional[SearchDebugInfo]:
        """
        Get the debug info from the last search operation.
        
        Returns:
            SearchDebugInfo object or None if no search has been performed
        """
        return getattr(self, '_last_search_debug', None)