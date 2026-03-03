#!/usr/bin/env python3
"""
benchmark_filetypes.py — 比較不同檔案類型 (PDF / DOCX / XLSX) 的回應時間
=======================================================================

針對已 ingest 到預設 ragindex 中的 PDF、DOCX、Excel 檔案內容各產生問題，
測量回應時間，分析不同檔案類型的效能差異。
"""

import asyncio
import json
import time
import uuid
from typing import Optional

import httpx

# ============================================================================
# Configuration
# ============================================================================
ORCHESTRATOR_URL = "https://ca-2v3lfktkn4xam-orch-gprag.nicepond-9d5552be.eastus2.azurecontainerapps.io/orchestrator"
API_KEY = "X1B4Zz5gehH0iuoS6EROyDwdVAP3FJYb"

# Questions organized by source file type
QUESTIONS = {
    # ── DOCX: 東森林口會員權益手冊.docx (28KB) ──
    "DOCX": [
        ("東森林口會員卡的入會費和年費分別是多少？", "會員權益手冊"),
        ("會員的退費規定有哪些時間階段？各可退多少比例？", "會員權益手冊"),
        ("會員每年可以獲得幾張表演票券？每張面額多少？", "會員權益手冊"),
        ("會員的餐飲折扣優惠包含哪些餐廳？折扣是多少？", "會員權益手冊"),
        ("會員的住房優惠是什麼？有什麼限制條件？", "會員權益手冊"),
    ],

    # ── PDF: 富邦投資健檢中心SWOT分析-20250523-F.pdf (1.6MB, 26頁) ──
    "PDF-A": [
        ("哈佛健診和東森栢馥在客源基礎上各自的評分是多少？", "健檢SWOT"),
        ("東森栢馥相比哈佛健診的主要優勢有哪些？", "健檢SWOT"),
        ("富邦投資精準健康的投資架構是什麼？哈佛健診的資本額是多少？", "健檢SWOT"),
        ("哈佛健診富盈診所分為哪幾個樓層？各提供什麼服務？", "健檢SWOT"),
        ("在行銷能力方面，哈佛健診和東森栢馥的評分差異有多大？", "健檢SWOT"),
    ],

    # ── PDF: 蔡琴演唱會.pdf (410KB, 5頁) ──
    "PDF-B": [
        ("蔡琴2025年不要告別巡迴演唱會有哪些場次和日期？", "蔡琴演唱會"),
        ("蔡琴演唱會台北場的票價區間是多少？", "蔡琴演唱會"),
        ("蔡琴歷年演唱會中哪個場地的席位數最大？", "蔡琴演唱會"),
        ("蔡琴2025演唱會的主辦單位和售票系統分別是什麼？", "蔡琴演唱會"),
    ],

    # ── PDF: 迪士尼授權合作洽談.pdf (4.8MB, 41頁) ──
    "PDF-C": [
        ("韓國現代百貨2023年營收大約是多少？", "迪士尼授權"),
        ("現代百貨與迪士尼韓國公司的合作模式是什麼？", "迪士尼授權"),
        ("東森想要和迪士尼合作的主要訴求是什麼？", "迪士尼授權"),
    ],

    # ── XLSX: 林口恩典大樓時程表 (for reference/comparison) ──
    "XLSX": [
        ("38F室內觀景台的完工日期是什麼時候？", "時程表"),
        ("30F三燔本家的權狀坪數和淨坪數分別是多少？", "時程表"),
        ("哪些樓層的設計單位目前還是未定？", "時程表"),
    ],
}


# ============================================================================
# API Call (reuse from benchmark_index.py)
# ============================================================================
async def ask_question(question: str, search_index: Optional[str] = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": API_KEY,
    }
    payload = {
        "conversation_id": "",
        "question": question,
        "ask": question,
        "client_principal_id": "benchmark-filetype",
        "client_principal_name": "benchmark",
        "client_group_names": [],
        "access_token": None,
        "debug_mode": True,
    }
    if search_index:
        payload["search_index"] = search_index

    start_time = time.time()
    first_token_time = None
    full_response = ""
    chunk_count = 0

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream("POST", ORCHESTRATOR_URL, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    return {"error": f"HTTP {response.status_code}", "total_time": time.time() - start_time}
                async for chunk in response.aiter_text():
                    if chunk:
                        chunk_count += 1
                        if first_token_time is None:
                            first_token_time = time.time()
                        full_response += chunk
    except Exception as e:
        return {"error": str(e)[:200], "total_time": time.time() - start_time}

    end_time = time.time()
    total_time = end_time - start_time
    ttfb = (first_token_time - start_time) if first_token_time else total_time

    # Extract answer preview
    answer_preview = ""
    for line in full_response.split("\n"):
        line = line.strip()
        if line.startswith("event: error"):
            continue
        if line.startswith("data: ") and "error" in line.lower():
            answer_preview = f"[ERROR] {line[6:200]}"
            break
        if line.startswith("data: "):
            data_content = line[6:]
            if data_content.startswith("{") or data_content.startswith("["):
                continue
            answer_preview += data_content + " "
        elif line and not line.startswith("event:") and not line.startswith("{") and not line.startswith("["):
            answer_preview += line + " "
    if not answer_preview:
        answer_preview = full_response[:300]

    return {
        "total_time": round(total_time, 2),
        "ttfb": round(ttfb, 2),
        "stream_time": round(total_time - ttfb, 2),
        "chunks": chunk_count,
        "response_length": len(full_response),
        "answer_preview": answer_preview[:250].strip(),
        "error": None,
    }


# ============================================================================
# Main
# ============================================================================
async def run_benchmark():
    print("=" * 80)
    print("  GPT-RAG File Type Benchmark: DOCX vs PDF vs XLSX")
    print("=" * 80)
    print(f"  Orchestrator: {ORCHESTRATOR_URL}")
    total_q = sum(len(v) for v in QUESTIONS.values())
    print(f"  Total Questions: {total_q}")
    print()

    # Warmup
    print("  ⏳ Warming up orchestrator...")
    for attempt in range(3):
        print(f"    Warmup attempt {attempt+1}...", end="", flush=True)
        w = await ask_question("hello")
        ttfb = w.get("ttfb", 999)
        has_error = w.get("error") or ("event: error" in w.get("answer_preview", ""))
        print(f" {w.get('total_time', '?')}s (TTFB: {ttfb}s){' ⚠️' if has_error or ttfb > 5 else ' ✅'}")
        if not has_error and ttfb < 5:
            break
        await asyncio.sleep(5)
    print("  ✅ Warmup complete.\n")

    # Run questions by file type
    all_results = {}
    for file_type, questions in QUESTIONS.items():
        print(f"\n{'━' * 70}")
        print(f"  📁 {file_type}")
        print(f"{'━' * 70}")

        type_results = []
        for question, source_label in questions:
            print(f"\n  Q: {question}")
            result = await ask_question(question)

            if result.get("error"):
                print(f"     ❌ ERROR: {result['error'][:80]}")
            else:
                print(f"     ⏱️  {result['total_time']}s (TTFB: {result['ttfb']}s)")
                preview = result.get("answer_preview", "")[:130]
                print(f"     💬 {preview}...")

            type_results.append({**result, "question": question, "source": source_label})
            await asyncio.sleep(2)

        all_results[file_type] = type_results

    # ========================================================================
    # Summary
    # ========================================================================
    print("\n\n")
    print("=" * 80)
    print("  FILE TYPE BENCHMARK RESULTS")
    print("=" * 80)

    # Per-question detail
    print(f"\n{'Type':<8} {'Question':<50} {'Time(s)':<10} {'TTFB(s)':<10}")
    print("─" * 80)

    type_avgs = {}
    for file_type, results in all_results.items():
        times = []
        for r in results:
            t = r.get("total_time", 0) if not r.get("error") else -1
            q_short = r["question"][:47] + "..." if len(r["question"]) > 47 else r["question"]
            t_str = f"{t:.1f}" if t > 0 else "ERR"
            ttfb_str = f"{r.get('ttfb', 0):.1f}" if t > 0 else "ERR"
            print(f"{file_type:<8} {q_short:<50} {t_str:<10} {ttfb_str:<10}")
            if t > 0:
                times.append(t)
        if times:
            type_avgs[file_type] = {
                "avg": sum(times) / len(times),
                "min": min(times),
                "max": max(times),
                "count": len(times),
            }
        print()

    # Summary table by type
    print("─" * 80)
    print(f"\n{'Type':<10} {'Avg(s)':<10} {'Min(s)':<10} {'Max(s)':<10} {'Questions':<10}")
    print("─" * 50)
    for ft, stats in sorted(type_avgs.items(), key=lambda x: x[1]["avg"]):
        print(f"{ft:<10} {stats['avg']:<10.1f} {stats['min']:<10.1f} {stats['max']:<10.1f} {stats['count']:<10}")

    # Overall comparison
    print()
    if type_avgs:
        fastest = min(type_avgs, key=lambda k: type_avgs[k]["avg"])
        slowest = max(type_avgs, key=lambda k: type_avgs[k]["avg"])
        print(f"  🏆 Fastest file type: {fastest} (avg {type_avgs[fastest]['avg']:.1f}s)")
        print(f"  🐢 Slowest file type: {slowest} (avg {type_avgs[slowest]['avg']:.1f}s)")
        diff = type_avgs[slowest]["avg"] - type_avgs[fastest]["avg"]
        print(f"  📊 Difference: {diff:.1f}s ({diff/type_avgs[slowest]['avg']*100:.0f}%)")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
