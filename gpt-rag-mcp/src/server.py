# server.py
import contextlib
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.middleware.cors import CORSMiddleware

from mcp.server.fastmcp import FastMCP
from tools.wikipedia import search_wikipedia
from tools.sql_persona import get_customer_persona, search_customers, get_persona_update_info, update_tags_tracking, update_customer_persona
from tools.cosmos_transcripts import get_call_transcripts, get_call_summary, upsert_call_transcript
from tools.aisearch_membership import search_membership_info
from prompts.greeting import greet_user

# ---- MCP server ----
mcp = FastMCP("SalesAgent")

@mcp.tool()
def add(a: int, b: int) -> int:
    return a + b

@mcp.tool()
def wikipedia_search(query: str) -> list[str]:
    """Search Wikipedia for articles matching the query."""
    return search_wikipedia(query)

# ── SQL Persona Tools ──────────────────────────────────────────────

@mcp.tool()
def query_customer_persona(customer_id: str) -> str:
    """查詢客戶 Persona 結構化資料（年齡、消費力、偏好標籤等）。

    Args:
        customer_id: 客戶的 customerid 識別碼
    """
    return get_customer_persona(customer_id)

@mcp.tool()
def search_customer_by_field(field: str, value: str, limit: int = 10) -> str:
    """依特定欄位搜尋客戶。可用欄位：性別, 縣市, OB等級, 星座。

    Args:
        field: 搜尋欄位名稱
        value: 搜尋值
        limit: 回傳最大筆數（預設 10，最多 50）
    """
    return search_customers(field, value, limit)

# ── Cosmos Call Transcript Tools ───────────────────────────────────

@mcp.tool()
def query_call_transcripts(customer_id: str) -> str:
    """查詢客戶的歷史通話逐字稿（含完整文本）。

    Args:
        customer_id: 客戶的客代識別碼
    """
    return get_call_transcripts(customer_id)

@mcp.tool()
def query_call_summary(customer_id: str) -> str:
    """查詢客戶的通話歷史摘要（不含完整文本，僅含日期、結果、預覽）。

    Args:
        customer_id: 客戶的客代識別碼
    """
    return get_call_summary(customer_id)
@mcp.tool()
def upsert_transcript(
    customer_id: str,
    call_id: str,
    call_date: str,
    status: str,
    transcript: str,
    source: str = "",
    ingested_at: str = "",
) -> str:
    """新增或更新客戶的通話逐字稿至 Cosmos DB。

    Args:
        customer_id: 客戶的客代識別碼 (Partition Key)
        call_id: 通話唯一識別碼
        call_date: 通話日期 (YYYY-MM-DD)
        status: 推銷結果 (成功/失敗)
        transcript: 完整逐字稿文本
        source: 來源描述 (e.g. 'stt_blob_ingest')
        ingested_at: 擷取時間 ISO 格式
    """
    return upsert_call_transcript(
        customer_id=customer_id,
        call_id=call_id,
        call_date=call_date,
        status=status,
        transcript=transcript,
        source=source,
        ingested_at=ingested_at,
    )
# ── AI Search Membership Card Tool ─────────────────────────────────

@mcp.tool()
async def search_membership_card(query: str, top_k: int = 5) -> str:
    """搜尋會員卡相關知識（權益、收費、競業比較等）。

    Args:
        query: 關於會員卡的自然語言查詢
        top_k: 回傳最大筆數（預設 5）
    """
    return await search_membership_info(query, top_k)

# ── Persona Update Tracking Tools ──────────────────────────────────

@mcp.tool()
def query_persona_update_info(customer_id: str) -> str:
    """查詢客戶人物側寫與標籤的最後更新時間及來源。

    Args:
        customer_id: 客戶的 customerid 識別碼
    """
    return get_persona_update_info(customer_id)

@mcp.tool()
def update_persona(customer_id: str, persona_text: str, source: str) -> str:
    """更新客戶的人物側寫文字及追蹤資訊（更新時間與來源）。

    Args:
        customer_id: 客戶的 customerid 識別碼
        persona_text: 新的人物側寫文字
        source: 更新來源描述（例如 'transcript_ingest:<call_id>'）
    """
    return update_customer_persona(customer_id, persona_text, source)

@mcp.tool()
def update_customer_tags_tracking(customer_id: str, source: str) -> str:
    """更新客戶標籤的追蹤資訊（更新時間與來源）。供標籤處理程式呼叫。

    Args:
        customer_id: 客戶的 customerid 識別碼
        source: 更新來源描述（例如 'tag_program_v2'）
    """
    return update_tags_tracking(customer_id, source)

@mcp.prompt()
def greet_user_prompt(name: str, style: str = "friendly") -> str:
    """Generate a greeting prompt for someone."""
    return greet_user(name, style)

# ---- Lifespan: start/stop MCP session manager ----
@asynccontextmanager
async def mcp_lifespan(_app):
    async with contextlib.AsyncExitStack() as stack:
        # This is the key bit you were missing:
        await stack.enter_async_context(mcp.session_manager.run())
        yield  # app is live
        # exit stack will shut it down cleanly

# Optional: health endpoint for probes
async def healthz(_req):
    return JSONResponse({"status": "ok"})

# ---- Parent Starlette app with MCP mounted ----
app = Starlette(
    lifespan=mcp_lifespan,  # << wire in the MCP lifespan
    routes=[
        Route("/healthz", endpoint=healthz),
        # Mount at "/" if you want MCP at root; otherwise use "/mcp"
        Mount("/", app=mcp.streamable_http_app()),
        Mount("/mcp", app=mcp.streamable_http_app()),  # alt path
    ],
)

# Add CORS middleware - must be added AFTER app creation but order matters
app = CORSMiddleware(
    app=app,
    allow_origins=["*"],  # In production, specify the Inspector's origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["mcp-session-id", "content-type"],
)