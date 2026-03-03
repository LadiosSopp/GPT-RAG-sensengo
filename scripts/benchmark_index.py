#!/usr/bin/env python3
"""
benchmark_index.py — 比較 ragindex (by-sheet) 與 ragindex-byrow (by-row) 的回應時間
====================================================================================

基於「林口恩典大樓A棟時程表12.29_2026.01.13.13.08.xlsx」內容生成 10 個問題，
分別向兩個 index 發送相同問題，統計回應時間。

使用方法：
  python scripts/benchmark_index.py
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

# Index names to compare
INDEX_DEFAULT = None  # None = use default ragindex (by-sheet)
INDEX_BYROW = "ragindex-byrow"
INDEX_HYBRID = "ragindex-hybrid"

INDEX_LABELS = {
    "default": "by-sheet",
    "byrow": "by-row",
    "hybrid": "hybrid",
}

# 10 questions based on the Excel schedule content
QUESTIONS = [
    # 1. 單行精確查詢 — 特定樓層日期
    "38F 室內觀景台的完工日期是什麼時候？",
    # 2. 單行精確查詢 — 特定樓層設計單位
    "27F Regal Spa 的設計單位是誰？",
    # 3. 跨行聚合 — 設計師負責範圍
    "柏成設計負責哪些樓層？",
    # 4. 跨行聚合 — 用途變更
    "哪些樓層的使用項目有從舊版變更到新版？請列出變更內容。",
    # 5. 日期範圍查詢
    "哪些樓層預計在 2026 年 8 月之前完工？",
    # 6. 數值查詢
    "30F 三燔本家的權狀坪數和淨坪數分別是多少？",
    # 7. 綜合查詢 — 多欄位
    "酒店區域（28F-36F）各樓層的設計圖定案日期和完工日期分別是什麼？",
    # 8. 特定條件篩選
    "哪些樓層的設計單位目前還是「未定」？",
    # 9. 時程分析
    "維格設計負責的樓層中，裝潢時程最長的是哪一個？需要多久？",
    # 10. 整體摘要
    "請概述林口恩典大樓 A 棟各樓層的主要用途分布，從 1F 到 RF。",
]


# ============================================================================
# API Call
# ============================================================================
async def ask_question(
    question: str,
    search_index: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> dict:
    """
    Send a question to the orchestrator and measure response time.
    Returns dict with timing info and response text.
    """
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": API_KEY,
    }

    payload = {
        "conversation_id": "",  # Empty string = auto-create new conversation
        "question": question,
        "ask": question,
        "client_principal_id": "benchmark-test",
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
                    return {
                        "error": f"HTTP {response.status_code}: {body.decode(errors='ignore')[:500]}",
                        "total_time": time.time() - start_time,
                    }

                async for chunk in response.aiter_text():
                    if chunk:
                        chunk_count += 1
                        if first_token_time is None:
                            first_token_time = time.time()
                        full_response += chunk

    except Exception as e:
        return {
            "error": str(e)[:500],
            "total_time": time.time() - start_time,
        }

    end_time = time.time()
    total_time = end_time - start_time
    ttfb = (first_token_time - start_time) if first_token_time else total_time

    # Try to extract answer text (strip debug info)
    answer_text = full_response
    # The SSE response may contain debug JSON blocks - extract main text
    answer_preview = ""
    for line in full_response.split("\n"):
        line = line.strip()
        if line.startswith("event: error"):
            # Extract error details from following data line
            continue
        if line.startswith("data: ") and "error" in line.lower():
            answer_preview = f"[ERROR] {line[6:200]}"
            break
        if line.startswith("data: "):
            data_content = line[6:]
            # Skip JSON debug blocks
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
        "answer_preview": answer_preview[:200].strip(),
        "error": None,
    }


# ============================================================================
# Main Benchmark
# ============================================================================
async def run_benchmark():
    print("=" * 80)
    print("  GPT-RAG Index Benchmark: by-sheet vs by-row vs hybrid")
    print("=" * 80)
    print(f"  Orchestrator: {ORCHESTRATOR_URL}")
    print(f"  Questions: {len(QUESTIONS)}")
    print()

    # Warmup: send throwaway requests to eliminate cold start bias
    # Retry until TTFB < 5s to confirm the service is truly warm
    print("  ⏳ Warming up orchestrator (cold start elimination)...")
    for idx_key, idx_val in [("default", INDEX_DEFAULT), ("byrow", INDEX_BYROW), ("hybrid", INDEX_HYBRID)]:
        label = INDEX_LABELS[idx_key]
        for attempt in range(3):
            print(f"    Warmup [{label}] attempt {attempt+1}...", end="", flush=True)
            warmup = await ask_question("hello", search_index=idx_val)
            t = warmup.get("total_time", 999)
            ttfb = warmup.get("ttfb", 999)
            has_error = warmup.get("error") or ("event: error" in warmup.get("answer_preview", ""))
            print(f" {t}s (TTFB: {ttfb}s){' ⚠️ error/slow' if has_error or ttfb > 5 else ' ✅'}")
            if not has_error and ttfb < 5:
                break
            print(f"      Retrying in 5s (service may still be starting)...")
            await asyncio.sleep(5)
        await asyncio.sleep(1)
    print("  ✅ Warmup complete. Starting benchmark...\n")

    results = {"default": [], "byrow": [], "hybrid": []}

    for i, question in enumerate(QUESTIONS):
        print(f"\n{'─' * 70}")
        print(f"  Q{i+1}: {question}")
        print(f"{'─' * 70}")

        for index_key, search_index in [("default", INDEX_DEFAULT), ("byrow", INDEX_BYROW), ("hybrid", INDEX_HYBRID)]:
            label = INDEX_LABELS[index_key]
            print(f"\n  [{label}] Asking...", end="", flush=True)

            result = await ask_question(question, search_index=search_index)

            if result.get("error"):
                print(f" ERROR: {result['error'][:100]}")
            else:
                print(f" {result['total_time']}s (TTFB: {result['ttfb']}s, Stream: {result['stream_time']}s)")
                if result.get("answer_preview"):
                    preview = result["answer_preview"][:120]
                    print(f"    Answer: {preview}...")

            results[index_key].append(result)

            # Brief pause between requests to avoid rate limiting
            await asyncio.sleep(2)

    # ========================================================================
    # Summary Statistics
    # ========================================================================
    print("\n\n")
    print("=" * 80)
    print("  BENCHMARK RESULTS SUMMARY")
    print("=" * 80)

    # Header
    print(f"\n{'Q#':<4} {'Question':<35} {'by-sheet':<12} {'by-row':<12} {'hybrid':<12} {'Winner':<12}")
    print("─" * 90)

    all_times = {k: [] for k in results}

    for i in range(len(QUESTIONS)):
        q_short = QUESTIONS[i][:32] + ("..." if len(QUESTIONS[i]) > 32 else "")
        times = {}
        for k in results:
            r = results[k][i]
            times[k] = r.get("total_time", 0) if not r.get("error") else -1
            if times[k] > 0:
                all_times[k].append(times[k])

        valid = {k: v for k, v in times.items() if v > 0}
        if valid:
            winner = min(valid, key=valid.get)
            winner_label = INDEX_LABELS.get(winner, winner) + " ✅"
        else:
            winner_label = "N/A"

        cols = {k: f"{times[k]:.1f}" if times[k] > 0 else "ERR" for k in results}
        print(f"Q{i+1:<3} {q_short:<35} {cols['default']:<12} {cols['byrow']:<12} {cols['hybrid']:<12} {winner_label:<12}")

    # Averages
    print("─" * 90)
    avgs = {}
    for k in all_times:
        if all_times[k]:
            avgs[k] = sum(all_times[k]) / len(all_times[k])

    if avgs:
        avg_cols = {k: f"{avgs.get(k, 0):.1f}" for k in results}
        best = min(avgs, key=avgs.get)
        print(f"{'AVG':<4} {'Average':<35} {avg_cols['default']:<12} {avg_cols['byrow']:<12} {avg_cols['hybrid']:<12} {INDEX_LABELS[best]} ✅")

        print()
        for k in results:
            if k in avgs:
                print(f"  📊 {INDEX_LABELS[k]:<12} avg: {avgs[k]:.1f}s")

        if 'hybrid' in avgs and 'default' in avgs:
            imp = avgs['default'] - avgs['hybrid']
            pct = (imp / avgs['default'] * 100) if avgs['default'] > 0 else 0
            print(f"\n  🏆 hybrid vs by-sheet: {abs(imp):.1f}s ({abs(pct):.0f}%) {'faster' if imp > 0 else 'slower'}")
        if 'hybrid' in avgs and 'byrow' in avgs:
            imp = avgs['byrow'] - avgs['hybrid']
            pct = (imp / avgs['byrow'] * 100) if avgs['byrow'] > 0 else 0
            print(f"  🏆 hybrid vs by-row:   {abs(imp):.1f}s ({abs(pct):.0f}%) {'faster' if imp > 0 else 'slower'}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
