"""
Sales recommendation connector — 3-step sequential workflow.

  Step 1  Fetch client Persona + Call Summary via MCP
  Step 2  LLM (QUERY_GEN_DEPLOYMENT) analyzes Persona + Call Log → generates targeted RAG query → search membership card via MCP
  Step 3  LLM (RECOMMENDATION_DEPLOYMENT) generates personalised 推薦話術
"""

import json
import logging
from typing import Optional

import httpx
from semantic_kernel import Kernel
from semantic_kernel.connectors.mcp import MCPStreamableHttpPlugin
from openai import AsyncAzureOpenAI
from util.tools import is_azure_environment
from dependencies import get_config

logger = logging.getLogger(__name__)

# ── System prompt: 電銷推薦話術專家 ─────────────────────────────
SYSTEM_PROMPT = """你是東森購物的資深電銷策略顧問與話術專家。

## 你的任務
根據以下三份資料，**先判斷此客戶是否適合推銷會員卡**，再根據判斷結果產出對應的推薦話術。

### 輸入資料
1. **客戶 Persona**：結構化標籤（年齡、消費力、偏好等）與文字側寫
2. **歷史通話摘要**：包含痛點、禁忌、過去推銷結果
3. **會員卡權益 RAG 檢索**：現行卡種的權益、收費、競業優勢

## 適合推銷會員卡的判斷依據
綜合以下面向進行評估：
- **消費力與頻率**：消費力等級是否足以負擔會員卡費用？消費頻率是否高到能充分利用權益？
- **興趣與權益匹配度**：客戶的偏好、生活型態是否與現有會員卡權益有明確交集？
- **歷史態度**：通話紀錄中客戶對會員卡/加值服務是否有明確的拒絕、反感或負面經驗？
- **現有會員狀態**：客戶是否已持有同類型卡片？是否有升級空間？
- **風險因素**：是否有明確的地雷（如曾投訴推銷、明確表示不需要等）？

## 輸出格式（嚴格 JSON）
{
  "customer_profile_summary": "2-3 句話的客戶描述（含消費力等級與核心偏好）",
  "membership_suitability": {
    "is_suitable": true或false,
    "confidence": "高/中/低",
    "positive_factors": ["支持推銷的正面因素1", "正面因素2"],
    "negative_factors": ["不利推銷的負面因素1", "負面因素2"],
    "verdict": "一句話總結判斷結論與核心理由"
  },
  "recommended_membership_plan": {
    "plan_name": "建議的會員卡方案名稱（若不適合推銷則為 null）",
    "reason": "為什麼這個方案最適合此客戶（引用 Persona 數據）",
    "monthly_cost": "月費或年費資訊",
    "key_benefits": ["此方案切合客戶需求的重點權益1", "權益2", "權益3"],
    "competitor_advantage": "比起競業的優勢點（若 RAG 有相關資料）"
  },
  "sales_script": {
    "opening": "開場白（自然、有溫度、引起興趣）",
    "needs_discovery": "探詢需求的問法（基於 Persona 已知偏好設計）",
    "product_pitch": "核心推薦話術（結合會員卡權益與客戶偏好）",
    "benefit_highlight": "利益點強調（用客戶聽得懂的語言）",
    "objection_handling": [
      {"objection": "可能的拒絕理由", "response": "應對話術"}
    ],
    "closing": "促成購買的收尾話術",
    "follow_up": "若未成交的後續追蹤話術"
  },
  "alternative_strategy": "當 is_suitable 為 false 時，建議的替代互動策略（例如：先建立關係、推薦單品、等待更好時機等）；若 is_suitable 為 true 則為 null",
  "taboos": ["絕對不能提的地雷1", "地雷2"],
  "recommended_products": [
    {"name": "產品名", "reason": "推薦理由", "suggested_script": "推薦時的話術片段"}
  ],
  "communication_style": "與此客戶溝通的整體風格建議",
  "success_probability": "預估成交機率描述與依據"
}

## 原則
- **先判斷再行動**：務必先完成 membership_suitability 評估，再決定後續話術方向
- 若 is_suitable 為 **true**：正常產出完整的會員卡推薦話術
- 若 is_suitable 為 **false**：recommended_membership_plan 設為 null，sales_script 改為以關係維護或產品推薦為主的話術，並在 alternative_strategy 提供替代策略
- **話術必須自然、口語化**，像是資深電銷人員會講的話，不要書面語
- 所有建議必須有資料依據（標注來自 Persona / 通話紀錄 / 會員卡資訊）
- 根據客戶消費力等級匹配最適會員卡方案
- 若客戶已有會員卡，改為升級或續約策略
- 如果某項資料不足，明確指出並給出保守建議
- 用繁體中文
"""


class SalesRecommendationClient:
    """3-step workflow: Persona → Membership RAG → LLM 推薦話術."""

    def __init__(self):
        cfg = get_config()
        self.cfg = cfg
        self._plugin: Optional[MCPStreamableHttpPlugin] = None

    # ── MCP connection ─────────────────────────────────────────────

    async def _get_mcp_plugin(self) -> MCPStreamableHttpPlugin:
        if self._plugin is not None:
            return self._plugin

        cfg = self.cfg

        if not is_azure_environment():
            mcp_url = cfg.get("MCP_APP_ENDPOINT", default="http://localhost:5000") + "/mcp"
        else:
            mcp_url = cfg.get("MCP_APP_ENDPOINT", default="http://localhost:80") + "/mcp"

        mcp_timeout = cfg.get("MCP_CLIENT_TIMEOUT", default=600, type=int)
        try:
            mcp_api_key = cfg.get("MCP_APP_APIKEY")
        except Exception:
            mcp_api_key = None

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if mcp_api_key:
            headers["X-API-KEY"] = mcp_api_key

        kernel = Kernel()
        plugin = MCPStreamableHttpPlugin(
            name="SalesAgentMCP",
            url=mcp_url,
            headers=headers,
            timeout=mcp_timeout,
            kernel=kernel,
        )
        await plugin.connect()
        self._plugin = plugin
        logger.info(f"[SalesRec] MCP plugin connected at {mcp_url}")
        return plugin

    async def _call_tool(self, tool_name: str, **kwargs) -> str:
        plugin = await self._get_mcp_plugin()
        logger.info(f"[SalesRec] Calling MCP tool: {tool_name}({kwargs})")
        results = await plugin.call_tool(tool_name, **kwargs)
        texts = [c.text for c in results if hasattr(c, "text")]
        return "\n".join(texts)

    # ── Step 1: Fetch Persona & Call Summary ──────────────────────

    async def fetch_persona(self, customer_id: str) -> str:
        return await self._call_tool("query_customer_persona", customer_id=customer_id)

    async def fetch_call_summary(self, customer_id: str) -> str:
        return await self._call_tool("query_call_summary", customer_id=customer_id)

    # ── Step 2: LLM-driven dynamic query → Membership Card RAG ────

    QUERY_GEN_PROMPT = """你是東森購物的會員卡推薦分析師。根據以下客戶資料，產生一段精準的搜尋查詢，用於從知識庫中檢索最適合此客戶的會員卡權益資訊。

## 分析重點
1. 客戶的消費力等級與消費頻率 → 決定適合的卡別等級
2. 客戶的興趣偏好與生活型態 → 匹配相關權益（餐飲、旅遊、健身、展演等）
3. 客戶的家庭狀況 → 是否適合家庭共享型權益
4. 通話紀錄中的痛點或需求 → 針對性地搜尋解決方案
5. 客戶曾拒絕或抱怨的點 → 避開相關內容，搜尋替代方案

## 輸出要求
- 只輸出一段搜尋查詢文字（50-150字），不要任何前綴、說明或格式標記
- 查詢應包含：會員卡相關關鍵字 + 此客戶最可能感興趣的權益面向
- 用繁體中文"""

    async def fetch_membership_info(self, query: str) -> str:
        return await self._call_tool("search_membership_card", query=query)

    async def _build_membership_query_with_llm(
        self, persona_json: str, call_summary_json: str, *, query_gen_deployment: Optional[str] = None
    ) -> str:
        """Use LLM (QUERY_GEN_DEPLOYMENT) to analyze Persona + Call Log and generate a targeted RAG query."""
        query_gen_deployment = query_gen_deployment or self.cfg.get("QUERY_GEN_DEPLOYMENT", "gpt-5-mini")
        user_content = f"""## 客戶 Persona
{persona_json}

## 通話歷史摘要
{call_summary_json}

請根據以上資料，產生一段搜尋查詢來找出最適合此客戶的東森會員卡權益。"""

        try:
            client = await self._get_openai_client()
            response = await client.chat.completions.create(
                model=query_gen_deployment,
                messages=[
                    {"role": "system", "content": self.QUERY_GEN_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_completion_tokens=200,
            )
            query = (response.choices[0].message.content or "").strip()
            await client.close()
            if query:
                return query
        except Exception as exc:
            logger.warning(f"[SalesRec] LLM query generation failed: {exc}, falling back")

        # Fallback: basic keywords
        return "東森會員卡 權益 收費方案 服務內容 消費等級"

    # ── OpenAI client ──────────────────────────────────────────────

    async def _get_openai_client(self) -> AsyncAzureOpenAI:
        cfg = self.cfg
        endpoint = cfg.get("AZURE_OPENAI_ENDPOINT", "")
        api_version = cfg.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

        # 600s timeout — reasoning models (gpt-5.4) can take minutes
        timeout = httpx.Timeout(600.0, connect=30.0)
        logger.info(f"[SalesRec] OpenAI endpoint={endpoint}, api_version={api_version}")

        api_key = cfg.get("AZURE_OPENAI_API_KEY", "")
        if api_key:
            logger.info("[SalesRec] Using API key auth for OpenAI")
            return AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_version=api_version,
                api_key=api_key,
                timeout=timeout,
            )
        else:
            from azure.identity.aio import (
                ManagedIdentityCredential,
                AzureCliCredential,
                ChainedTokenCredential,
            )

            logger.info("[SalesRec] Using AAD credential for OpenAI")
            credential = ChainedTokenCredential(
                ManagedIdentityCredential(),
                AzureCliCredential(),
            )
            token = await credential.get_token("https://cognitiveservices.azure.com/.default")
            logger.info(f"[SalesRec] AAD token acquired (length={len(token.token)})")
            return AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_version=api_version,
                azure_ad_token=token.token,
                timeout=timeout,
            )

    async def close(self):
        if self._plugin:
            await self._plugin.close()
            self._plugin = None

    # ── Main workflow ──────────────────────────────────────────────

    async def generate_recommendation(
        self,
        customer_id: str,
        call_customer_id: Optional[str] = None,
        model_deployment: Optional[str] = None,
        query_gen_deployment: Optional[str] = None,
    ) -> dict:
        """
        3-step sequential workflow with debug timing & I/O capture.

          Step 1  Fetch complete Persona + Call Summary via MCP
          Step 2  LLM (QUERY_GEN_DEPLOYMENT) analyzes Persona+CallLog → generates targeted RAG query → search membership card via MCP
          Step 3  LLM (RECOMMENDATION_DEPLOYMENT) generates 推薦話術

        Returns:
            {"recommendation": {...}, "debug": {"steps": [...], "total_seconds": ...}}
        """
        call_cid = call_customer_id or customer_id
        import sys, time as _time
        _workflow_start = _time.time()
        debug_steps = []

        def _log(msg):
            elapsed = _time.time() - _workflow_start
            line = f"[SalesRec {elapsed:6.1f}s] {msg}"
            logger.info(line)
            print(line, file=sys.stderr, flush=True)

        def _step_record(name, duration, input_data, output_data):
            debug_steps.append({
                "name": name,
                "duration_seconds": round(duration, 2),
                "input": input_data,
                "output": output_data if len(str(output_data)) <= 5000 else str(output_data)[:5000] + "...(truncated)",
            })

        # ━━ Step 1a: 取得客戶 Persona ━━━━━━━━━━━━━━━━━━━━━━━━━━
        _log("Step 1/3 — Fetching customer Persona & Call Summary")

        t0 = _time.time()
        persona_json = await self.fetch_persona(customer_id)
        _step_record("fetch_persona", _time.time() - t0,
                      {"customer_id": customer_id}, persona_json)
        _log(f"  Persona fetched ({len(persona_json)} chars)")
        _log(f"  Persona content preview: {persona_json[:300]}")

        # ━━ Step 1b: 取得通話摘要 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        t0 = _time.time()
        call_summary_json = await self.fetch_call_summary(call_cid)
        _step_record("fetch_call_summary", _time.time() - t0,
                      {"customer_id": call_cid}, call_summary_json)
        _log(f"  Call Summary fetched ({len(call_summary_json)} chars)")

        # ━━ Step 2: LLM 分析 Persona + Call Log → 動態生成 RAG 查詢 ━━
        _log("Step 2/3 — LLM analyzing customer data → generating targeted RAG query")

        t0 = _time.time()
        membership_query = await self._build_membership_query_with_llm(persona_json, call_summary_json, query_gen_deployment=query_gen_deployment)
        query_gen_duration = _time.time() - t0
        _step_record("llm_query_generation", query_gen_duration,
                      {"persona_length": len(persona_json), "call_summary_length": len(call_summary_json)},
                      {"query": membership_query})
        _log(f"  LLM-generated RAG query ({query_gen_duration:.1f}s): {membership_query[:120]}...")

        t0 = _time.time()
        membership_json = await self.fetch_membership_info(membership_query)
        _step_record("search_membership_card", _time.time() - t0,
                      {"query": membership_query}, membership_json)
        _log(f"  Membership RAG results ({len(membership_json)} chars)")

        # ━━ Step 3: LLM reasoning → 生成推薦話術 ━━━━━━━━━━━━━━━
        cfg = self.cfg
        deployment = model_deployment or cfg.get("RECOMMENDATION_DEPLOYMENT", cfg.get("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-5.4"))
        _log(f"Step 3/3 — LLM calling deployment={deployment}")

        user_content = f"""以下是此客戶的三份資料，請據此生成完整的電銷推薦話術。

## 1. 客戶 Persona 資料
{persona_json}

## 2. 通話歷史摘要
{call_summary_json}

## 3. 會員卡權益資訊（RAG 檢索結果）
{membership_json}

請根據客戶的消費力、偏好和痛點，推薦最適合的會員卡方案，並產出一套電銷人員可以直接使用的話術。"""

        client = await self._get_openai_client()
        _log(f"  OpenAI client ready, calling {deployment}...")

        # GPT-5 family uses max_completion_tokens and does not support custom temperature
        t0 = _time.time()
        usage_info = None
        try:
            response = await client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_completion_tokens=16384,
            )
            gpt_duration = _time.time() - t0
            result_text = response.choices[0].message.content or ""
            usage_info = {
                "completion_tokens": response.usage.completion_tokens,
                "prompt_tokens": response.usage.prompt_tokens,
                "total_tokens": response.usage.total_tokens,
            } if response.usage else None
            _log(f"Step 3 complete — usage={response.usage}")
            _log(f"  response length={len(result_text)} chars")

            _step_record("gpt_recommendation", gpt_duration,
                          {"model": deployment, "system_prompt_length": len(SYSTEM_PROMPT),
                           "user_content_length": len(user_content)},
                          {"response_length": len(result_text), "usage": usage_info})

            total_seconds = round(_time.time() - _workflow_start, 2)
            debug_info = {"steps": debug_steps, "total_seconds": total_seconds}

            if not result_text.strip():
                return {
                    "recommendation": {"error": "模型回應為空（可能 reasoning tokens 耗盡了 max_completion_tokens 額度）",
                                       "usage": usage_info},
                    "debug": debug_info,
                }

            # Try parsing JSON; reasoning models may wrap it in markdown fences
            cleaned = result_text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines).strip()

            try:
                recommendation = json.loads(cleaned)
            except json.JSONDecodeError:
                _log("Warning: response is not valid JSON, returning raw text")
                recommendation = {"raw_response": result_text, "usage": usage_info}

            return {"recommendation": recommendation, "debug": debug_info}
        except Exception as exc:
            gpt_duration = _time.time() - t0
            _log(f"GPT call FAILED: {type(exc).__name__}: {exc}")
            logger.exception("[SalesRec] GPT call failed")
            _step_record("gpt_recommendation", gpt_duration,
                          {"model": deployment}, {"error": str(exc)})
            total_seconds = round(_time.time() - _workflow_start, 2)
            return {
                "recommendation": {"error": str(exc)},
                "debug": {"steps": debug_steps, "total_seconds": total_seconds},
            }
        finally:
            await client.close()
            await self.close()
