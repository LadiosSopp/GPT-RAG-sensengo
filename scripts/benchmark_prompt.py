#!/usr/bin/env python3
"""
benchmark_prompt.py — 比較 standard vs lite prompt 的回應時間
============================================================

用同樣的 10 個問題，分別用 standard 和 lite prompt mode 各問一次，
比較 LLM Thinking 時間和總回應時間。
"""

import asyncio
import time
from typing import Optional

import httpx

# ============================================================================
# Configuration
# ============================================================================
ORCHESTRATOR_URL = "https://ca-2v3lfktkn4xam-orch-gprag.nicepond-9d5552be.eastus2.azurecontainerapps.io/orchestrator"
API_KEY = "X1B4Zz5gehH0iuoS6EROyDwdVAP3FJYb"

PROMPT_MODES = {
    "standard": None,   # None = default prompt
    "lite": "lite",
}

QUESTIONS = [
    "38F 室內觀景台的完工日期是什麼時候？",
    "27F Regal Spa 的設計單位是誰？",
    "柏成設計負責哪些樓層？",
    "哪些樓層的使用項目有從舊版變更到新版？請列出變更內容。",
    "哪些樓層預計在 2026 年 8 月之前完工？",
    "30F 三燔本家的權狀坪數和淨坪數分別是多少？",
    "酒店區域（28F-36F）各樓層的設計圖定案日期和完工日期分別是什麼？",
    "哪些樓層的設計單位目前還是「未定」？",
    "維格設計負責的樓層中，裝潢時程最長的是哪一個？需要多久？",
    "請概述林口恩典大樓 A 棟各樓層的主要用途分布，從 1F 到 RF。",
]


async def ask_question(question: str, prompt_mode: Optional[str] = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": API_KEY,
    }
    payload = {
        "conversation_id": "",
        "question": question,
        "ask": question,
        "client_principal_id": "benchmark-prompt",
        "client_principal_name": "benchmark",
        "client_group_names": [],
        "access_token": None,
        "debug_mode": True,
    }
    if prompt_mode:
        payload["prompt_mode"] = prompt_mode

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
        "response_length": len(full_response),
        "answer_preview": answer_preview[:200].strip(),
        "error": None,
    }


async def run_benchmark():
    print("=" * 80)
    print("  GPT-RAG Prompt Mode Benchmark: standard vs lite")
    print("=" * 80)
    print(f"  Orchestrator: {ORCHESTRATOR_URL}")
    print(f"  Questions: {len(QUESTIONS)}")
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

    results = {"standard": [], "lite": []}

    for i, question in enumerate(QUESTIONS):
        print(f"\n{'─' * 70}")
        print(f"  Q{i+1}: {question}")
        print(f"{'─' * 70}")

        for mode_key, mode_val in [("standard", None), ("lite", "lite")]:
            print(f"\n  [{mode_key}] Asking...", end="", flush=True)
            result = await ask_question(question, prompt_mode=mode_val)

            if result.get("error"):
                print(f" ERROR: {result['error'][:80]}")
            else:
                print(f" {result['total_time']}s (TTFB: {result['ttfb']}s, Stream: {result['stream_time']}s)")
                preview = result.get("answer_preview", "")[:120]
                print(f"    Answer: {preview}...")

            results[mode_key].append(result)
            await asyncio.sleep(2)

    # ========================================================================
    # Summary
    # ========================================================================
    print("\n\n")
    print("=" * 80)
    print("  PROMPT MODE BENCHMARK RESULTS")
    print("=" * 80)

    print(f"\n{'Q#':<4} {'Question':<40} {'standard':<12} {'lite':<12} {'Δ (s)':<10} {'Faster':<12}")
    print("─" * 90)

    all_times = {"standard": [], "lite": []}

    for i in range(len(QUESTIONS)):
        q_short = QUESTIONS[i][:37] + ("..." if len(QUESTIONS[i]) > 37 else "")
        times = {}
        for k in results:
            r = results[k][i]
            times[k] = r.get("total_time", 0) if not r.get("error") else -1
            if times[k] > 0:
                all_times[k].append(times[k])

        if times["standard"] > 0 and times["lite"] > 0:
            delta = round(times["standard"] - times["lite"], 2)
            faster = "lite ✅" if delta > 0 else "standard" if delta < 0 else "tie"
            delta_str = f"{abs(delta):.1f}"
        else:
            delta_str = "N/A"
            faster = "N/A"

        s_str = f"{times['standard']:.1f}" if times["standard"] > 0 else "ERR"
        l_str = f"{times['lite']:.1f}" if times["lite"] > 0 else "ERR"
        print(f"Q{i+1:<3} {q_short:<40} {s_str:<12} {l_str:<12} {delta_str:<10} {faster:<12}")

    print("─" * 90)

    if all_times["standard"] and all_times["lite"]:
        avg_s = sum(all_times["standard"]) / len(all_times["standard"])
        avg_l = sum(all_times["lite"]) / len(all_times["lite"])
        imp = avg_s - avg_l
        pct = (imp / avg_s * 100) if avg_s > 0 else 0

        s_str = f"{avg_s:.1f}"
        l_str = f"{avg_l:.1f}"
        d_str = f"{abs(imp):.1f}"
        winner = "lite ✅" if imp > 0 else "standard"
        print(f"{'AVG':<4} {'Average':<40} {s_str:<12} {l_str:<12} {d_str:<10} {winner:<12}")

        print()
        print(f"  📊 standard avg: {avg_s:.1f}s")
        print(f"  📊 lite avg:     {avg_l:.1f}s")
        print(f"  📊 Difference:   {abs(imp):.1f}s ({abs(pct):.0f}%) {'faster with lite' if imp > 0 else 'faster with standard'}")

        # Win count
        lite_wins = sum(1 for i in range(len(QUESTIONS))
                       if results["standard"][i].get("total_time", 0) > 0
                       and results["lite"][i].get("total_time", 0) > 0
                       and results["lite"][i]["total_time"] < results["standard"][i]["total_time"])
        std_wins = sum(1 for i in range(len(QUESTIONS))
                      if results["standard"][i].get("total_time", 0) > 0
                      and results["lite"][i].get("total_time", 0) > 0
                      and results["standard"][i]["total_time"] < results["lite"][i]["total_time"])
        print(f"\n  🏆 lite wins: {lite_wins}/{len(QUESTIONS)}")
        print(f"  🏆 standard wins: {std_wins}/{len(QUESTIONS)}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
