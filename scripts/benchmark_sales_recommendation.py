#!/usr/bin/env python3
"""
benchmark_sales_recommendation.py — 比較兩種模型組合的銷售推薦效能
==================================================================

組合 1: RAG Query GPT-5-nano + 推薦話術 GPT-5.2
組合 2: RAG Query GPT-5-nano + 推薦話術 GPT-5-nano

每組執行 10 次，記錄回應時間、token 用量、成本，並輸出 markdown 報告。

使用方法：
  python scripts/benchmark_sales_recommendation.py
"""

import asyncio
import json
import time
import sys
from datetime import datetime
from pathlib import Path

import httpx

# ============================================================================
# Configuration
# ============================================================================
BASE_URL = "https://ca-2v3lfktkn4xam-orch-gprag.nicepond-9d5552be.eastus2.azurecontainerapps.io"
SALES_REC_URL = f"{BASE_URL}/sales/recommendation"
API_KEY = "X1B4Zz5gehH0iuoS6EROyDwdVAP3FJYb"
CUSTOMER_ID = "26568707"
RUNS_PER_COMBO = 10

# Token pricing (USD per 1K tokens)
PRICING = {
    "gpt-52":      {"input": 0.025, "output": 0.100},
    "gpt-5-nano":  {"input": 0.001, "output": 0.004},
    "gpt-5-mini":  {"input": 0.005, "output": 0.020},
}

# Two combinations to test
COMBOS = [
    {
        "name": "組合1: RAG Query GPT-5-nano + 推薦話術 GPT-5.2",
        "short": "nano+5.2",
        "query_gen_deployment": "gpt-5-nano",
        "model_deployment": "gpt-52",
    },
    {
        "name": "組合2: RAG Query GPT-5-nano + 推薦話術 GPT-5-nano",
        "short": "nano+nano",
        "query_gen_deployment": "gpt-5-nano",
        "model_deployment": "gpt-5-nano",
    },
]


def calc_cost(usage: dict, model: str) -> float:
    """Calculate USD cost from token usage and model name."""
    if not usage or model not in PRICING:
        return 0.0
    p = PRICING[model]
    input_cost = (usage.get("prompt_tokens", 0) / 1000) * p["input"]
    output_cost = (usage.get("completion_tokens", 0) / 1000) * p["output"]
    return input_cost + output_cost


def extract_step_info(debug: dict) -> dict:
    """Extract query_gen and recommendation step info from debug."""
    info = {
        "total_seconds": debug.get("total_seconds", 0),
        "query_gen": {},
        "recommendation": {},
    }
    for step in debug.get("steps", []):
        name = step.get("name", "")
        if name == "llm_query_generation":
            info["query_gen"] = {
                "duration_seconds": step.get("duration_seconds", 0),
                "query": step.get("output", {}).get("query", "") if isinstance(step.get("output"), dict) else "",
            }
        elif name == "gpt_recommendation":
            output = step.get("output", {})
            info["recommendation"] = {
                "duration_seconds": step.get("duration_seconds", 0),
                "usage": output.get("usage", {}) if isinstance(output, dict) else {},
            }
    return info


async def run_single(client: httpx.AsyncClient, combo: dict, run_idx: int) -> dict:
    """Execute one sales recommendation API call."""
    payload = {
        "customer_id": CUSTOMER_ID,
        "call_customer_id": CUSTOMER_ID,
        "query_gen_deployment": combo["query_gen_deployment"],
        "model_deployment": combo["model_deployment"],
    }
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": API_KEY,
    }

    print(f"  [{combo['short']}] Run {run_idx+1}/{RUNS_PER_COMBO} ...", end="", flush=True)
    wall_start = time.time()

    try:
        resp = await client.post(SALES_REC_URL, json=payload, headers=headers)
        wall_seconds = time.time() - wall_start
        resp.raise_for_status()
        data = resp.json()

        debug = data.get("debug", {})
        step_info = extract_step_info(debug)
        rec = data.get("recommendation", {})

        # Calculate costs
        rec_usage = step_info["recommendation"].get("usage", {})
        rec_cost = calc_cost(rec_usage, combo["model_deployment"])

        # For query_gen step, usage is not captured in debug, estimate from known small token count
        # query_gen max_tokens=200, prompt ~3000 tokens typically
        # We'll note this as estimated
        qg_estimated_input = rec_usage.get("prompt_tokens", 3000) * 0.3  # rough ratio
        qg_estimated_output = 100  # typical query length
        qg_estimated_cost = calc_cost(
            {"prompt_tokens": qg_estimated_input, "completion_tokens": qg_estimated_output},
            combo["query_gen_deployment"]
        )

        total_cost = rec_cost + qg_estimated_cost

        result = {
            "run": run_idx + 1,
            "wall_seconds": round(wall_seconds, 2),
            "total_seconds": step_info["total_seconds"],
            "query_gen_seconds": step_info["query_gen"].get("duration_seconds", 0),
            "recommendation_seconds": step_info["recommendation"].get("duration_seconds", 0),
            "prompt_tokens": rec_usage.get("prompt_tokens", 0),
            "completion_tokens": rec_usage.get("completion_tokens", 0),
            "total_tokens": rec_usage.get("total_tokens", 0),
            "rec_cost_usd": round(rec_cost, 6),
            "qg_estimated_cost_usd": round(qg_estimated_cost, 6),
            "total_cost_usd": round(total_cost, 6),
            "recommendation_summary": "",
            "success": True,
            "error": None,
        }

        # Extract a short summary from recommendation
        if isinstance(rec, dict):
            summary = rec.get("customer_profile_summary", "")
            if not summary:
                summary = rec.get("raw_response", "")[:200] if rec.get("raw_response") else ""
            result["recommendation_summary"] = summary[:300]
            result["recommendation_full"] = rec

        print(f" {wall_seconds:.1f}s, tokens={rec_usage.get('total_tokens', '?')}, cost=${total_cost:.4f}")
        return result

    except Exception as exc:
        wall_seconds = time.time() - wall_start
        print(f" FAILED ({wall_seconds:.1f}s): {exc}")
        return {
            "run": run_idx + 1,
            "wall_seconds": round(wall_seconds, 2),
            "total_seconds": 0,
            "query_gen_seconds": 0,
            "recommendation_seconds": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "rec_cost_usd": 0,
            "qg_estimated_cost_usd": 0,
            "total_cost_usd": 0,
            "recommendation_summary": "",
            "recommendation_full": {},
            "success": False,
            "error": str(exc),
        }


def generate_markdown(all_results: dict, start_time: str) -> str:
    """Generate the complete markdown report."""
    lines = []
    lines.append("# 銷售推薦效能基準測試報告")
    lines.append("")
    lines.append(f"> 測試日期：{start_time}")
    lines.append(f"> 客戶編號：{CUSTOMER_ID}")
    lines.append(f"> 每組執行次數：{RUNS_PER_COMBO}")
    lines.append("")
    lines.append("## 模型定價參考")
    lines.append("")
    lines.append("| 模型 | Input ($/1K tokens) | Output ($/1K tokens) |")
    lines.append("|------|-------------------|---------------------|")
    lines.append("| GPT-5.2 | $0.025 | $0.100 |")
    lines.append("| GPT-5-nano | $0.001 | $0.004 |")
    lines.append("")

    for combo_key, combo_data in all_results.items():
        combo_info = combo_data["combo"]
        results = combo_data["results"]
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]

        lines.append(f"---")
        lines.append("")
        lines.append(f"## {combo_info['name']}")
        lines.append("")
        lines.append(f"- **RAG Query 模型**：`{combo_info['query_gen_deployment']}`")
        lines.append(f"- **推薦話術模型**：`{combo_info['model_deployment']}`")
        lines.append(f"- **成功次數**：{len(successful)}/{len(results)}")
        lines.append("")

        # Summary table
        lines.append("### 每次執行結果")
        lines.append("")
        lines.append("| # | 總時間(s) | 推薦LLM時間(s) | Prompt Tokens | Completion Tokens | Total Tokens | 推薦成本($) | 總成本($) | 狀態 |")
        lines.append("|---|----------|---------------|---------------|-------------------|--------------|------------|----------|------|")

        for r in results:
            status = "OK" if r["success"] else f"FAIL {r.get('error', '')[:30]}"
            lines.append(
                f"| {r['run']} "
                f"| {r['total_seconds']:.2f} "
                f"| {r['recommendation_seconds']:.2f} "
                f"| {r['prompt_tokens']:,} "
                f"| {r['completion_tokens']:,} "
                f"| {r['total_tokens']:,} "
                f"| ${r['rec_cost_usd']:.4f} "
                f"| ${r['total_cost_usd']:.4f} "
                f"| {status} |"
            )

        # Averages
        if successful:
            avg_total_time = sum(r["total_seconds"] for r in successful) / len(successful)
            avg_rec_time = sum(r["recommendation_seconds"] for r in successful) / len(successful)
            avg_prompt = sum(r["prompt_tokens"] for r in successful) / len(successful)
            avg_completion = sum(r["completion_tokens"] for r in successful) / len(successful)
            avg_total_tokens = sum(r["total_tokens"] for r in successful) / len(successful)
            avg_rec_cost = sum(r["rec_cost_usd"] for r in successful) / len(successful)
            avg_total_cost = sum(r["total_cost_usd"] for r in successful) / len(successful)
            total_cost_sum = sum(r["total_cost_usd"] for r in successful)

            min_time = min(r["total_seconds"] for r in successful)
            max_time = max(r["total_seconds"] for r in successful)
            min_cost = min(r["total_cost_usd"] for r in successful)
            max_cost = max(r["total_cost_usd"] for r in successful)

            lines.append(
                f"| **平均** "
                f"| **{avg_total_time:.2f}** "
                f"| **{avg_rec_time:.2f}** "
                f"| **{avg_prompt:,.0f}** "
                f"| **{avg_completion:,.0f}** "
                f"| **{avg_total_tokens:,.0f}** "
                f"| **${avg_rec_cost:.4f}** "
                f"| **${avg_total_cost:.4f}** "
                f"| - |"
            )

            lines.append("")
            lines.append("### 統計摘要")
            lines.append("")
            lines.append(f"| 指標 | 值 |")
            lines.append(f"|------|-----|")
            lines.append(f"| 平均總時間 | **{avg_total_time:.2f} 秒** |")
            lines.append(f"| 最快 / 最慢 | {min_time:.2f}s / {max_time:.2f}s |")
            lines.append(f"| 平均推薦 LLM 時間 | {avg_rec_time:.2f} 秒 |")
            lines.append(f"| 平均 Prompt Tokens | {avg_prompt:,.0f} |")
            lines.append(f"| 平均 Completion Tokens | {avg_completion:,.0f} |")
            lines.append(f"| 平均每次成本 | **${avg_total_cost:.4f}** |")
            lines.append(f"| 最低 / 最高單次成本 | ${min_cost:.4f} / ${max_cost:.4f} |")
            lines.append(f"| {len(successful)} 次成功總成本 | **${total_cost_sum:.4f}** |")

        # Response content for each run
        lines.append("")
        lines.append("### 每次回應內容摘要")
        lines.append("")
        for r in results:
            lines.append(f"#### 第 {r['run']} 次")
            lines.append("")
            if not r["success"]:
                lines.append(f"**失敗**：{r.get('error', 'Unknown error')}")
                lines.append("")
                continue

            rec = r.get("recommendation_full", {})
            if isinstance(rec, dict):
                # Customer summary
                summary = rec.get("customer_profile_summary", "N/A")
                lines.append(f"**客戶摘要**：{summary}")
                lines.append("")

                # Suitability
                suit = rec.get("membership_suitability", {})
                if suit:
                    lines.append(f"**適合度判斷**：{'適合' if suit.get('is_suitable') else '不適合'} (信心: {suit.get('confidence', 'N/A')})")
                    verdict = suit.get("verdict", "")
                    if verdict:
                        lines.append(f"  - {verdict}")
                    lines.append("")

                # Recommended plan
                plan = rec.get("recommended_membership_plan", {})
                if plan and plan.get("plan_name"):
                    lines.append(f"**推薦方案**：{plan.get('plan_name', 'N/A')}")
                    lines.append(f"  - 理由：{plan.get('reason', 'N/A')}")
                    lines.append("")

                # Success probability
                prob = rec.get("success_probability", "")
                if prob:
                    lines.append(f"**成功機率**：{prob}")
                    lines.append("")

                # Opening script (brief)
                script = rec.get("sales_script", {})
                if script:
                    opening = script.get("opening", "")
                    if opening:
                        lines.append(f"**開場白**：{opening[:200]}{'...' if len(opening) > 200 else ''}")
                        lines.append("")

                # Taboos
                taboos = rec.get("taboos", [])
                if taboos:
                    lines.append(f"**禁忌**：{', '.join(str(t) for t in taboos[:3])}")
                    lines.append("")
            else:
                lines.append(f"回應：{str(rec)[:500]}")
                lines.append("")

    # Cross-combo comparison
    combo_keys = list(all_results.keys())
    if len(combo_keys) >= 2:
        lines.append("---")
        lines.append("")
        lines.append("## 兩組對比總結")
        lines.append("")
        lines.append("| 指標 | 組合1 (nano+5.2) | 組合2 (nano+nano) | 差異 |")
        lines.append("|------|-----------------|------------------|------|")

        for metric_name, metric_key, fmt, unit in [
            ("平均總時間", "avg_total_time", ".2f", "秒"),
            ("平均推薦LLM時間", "avg_rec_time", ".2f", "秒"),
            ("平均 Prompt Tokens", "avg_prompt", ",.0f", ""),
            ("平均 Completion Tokens", "avg_completion", ",.0f", ""),
            ("平均每次成本", "avg_total_cost", ".4f", "USD"),
            ("總成本", "total_cost_sum", ".4f", "USD"),
        ]:
            vals = []
            for ck in combo_keys:
                s = [r for r in all_results[ck]["results"] if r["success"]]
                if not s:
                    vals.append(0)
                    continue
                if metric_key == "avg_total_time":
                    vals.append(sum(r["total_seconds"] for r in s) / len(s))
                elif metric_key == "avg_rec_time":
                    vals.append(sum(r["recommendation_seconds"] for r in s) / len(s))
                elif metric_key == "avg_prompt":
                    vals.append(sum(r["prompt_tokens"] for r in s) / len(s))
                elif metric_key == "avg_completion":
                    vals.append(sum(r["completion_tokens"] for r in s) / len(s))
                elif metric_key == "avg_total_cost":
                    vals.append(sum(r["total_cost_usd"] for r in s) / len(s))
                elif metric_key == "total_cost_sum":
                    vals.append(sum(r["total_cost_usd"] for r in s))

            if vals[0] > 0:
                diff_pct = ((vals[1] - vals[0]) / vals[0]) * 100
                diff_str = f"{diff_pct:+.1f}%"
            else:
                diff_str = "N/A"

            lines.append(
                f"| {metric_name} | {format(vals[0], fmt)} {unit} | {format(vals[1], fmt)} {unit} | {diff_str} |"
            )

        lines.append("")
        lines.append("> **備註**：")
        lines.append("> - 推薦成本僅計算 Step 3 (推薦話術生成) 的 token 費用，Step 2 (RAG 查詢生成) 的成本因 max_tokens=200 而極低（已估算包含）")
        lines.append("> - 總時間包含 MCP 資料擷取（Step 1）、LLM 查詢生成（Step 2）、會員卡 RAG 搜尋、及 LLM 推薦生成（Step 3）")
        lines.append("> - 網路延遲和 MCP 服務狀態可能影響各次執行的時間差異")

    return "\n".join(lines)


async def run_benchmark():
    """Main benchmark runner."""
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 70)
    print("  銷售推薦效能基準測試")
    print(f"  客戶：{CUSTOMER_ID}")
    print(f"  開始時間：{start_time}")
    print(f"  API：{SALES_REC_URL}")
    print("=" * 70)

    all_results = {}
    timeout = httpx.Timeout(600.0, connect=30.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for combo in COMBOS:
            print(f"\n{'─' * 60}")
            print(f"  {combo['name']}")
            print(f"  query_gen={combo['query_gen_deployment']}, model={combo['model_deployment']}")
            print(f"{'─' * 60}")

            results = []
            for i in range(RUNS_PER_COMBO):
                result = await run_single(client, combo, i)
                results.append(result)

                # Brief pause between runs to avoid overwhelming the service
                if i < RUNS_PER_COMBO - 1:
                    await asyncio.sleep(2)

            all_results[combo["short"]] = {
                "combo": combo,
                "results": results,
            }

            # Print combo summary
            successful = [r for r in results if r["success"]]
            if successful:
                avg_time = sum(r["total_seconds"] for r in successful) / len(successful)
                avg_cost = sum(r["total_cost_usd"] for r in successful) / len(successful)
                print(f"\n  [OK] 完成：{len(successful)}/{RUNS_PER_COMBO} 成功")
                print(f"    平均時間：{avg_time:.2f}s，平均成本：${avg_cost:.4f}")

    # Generate markdown report
    md_content = generate_markdown(all_results, start_time)
    output_path = Path(__file__).resolve().parent.parent / "doc" / "benchmark-sales-recommendation.md"
    output_path.write_text(md_content, encoding="utf-8")
    print(f"\n{'=' * 70}")
    print(f"  報告已儲存至：{output_path}")
    print(f"{'=' * 70}")

    # Also save raw JSON data
    json_path = output_path.with_suffix(".json")
    # Remove full recommendation from JSON to keep file size manageable
    slim_results = {}
    for k, v in all_results.items():
        slim_results[k] = {
            "combo": v["combo"],
            "results": [
                {key: val for key, val in r.items() if key != "recommendation_full"}
                for r in v["results"]
            ],
        }
    json_path.write_text(json.dumps(slim_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  原始資料：{json_path}")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
