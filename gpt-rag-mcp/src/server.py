# server.py
import contextlib
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.middleware.cors import CORSMiddleware

from mcp.server.fastmcp import FastMCP
from tools.wikipedia import search_wikipedia
from tools.sql_persona import get_customer_persona, search_customers
from tools.cosmos_transcripts import get_call_transcripts, get_call_summary
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
        customer_id: 客戶的 unikey3 識別碼
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

# ── AI Search Membership Card Tool ─────────────────────────────────

@mcp.tool()
async def search_membership_card(query: str, top_k: int = 5) -> str:
    """搜尋會員卡相關知識（權益、收費、競業比較等）。

    Args:
        query: 關於會員卡的自然語言查詢
        top_k: 回傳最大筆數（預設 5）
    """
    return await search_membership_info(query, top_k)

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