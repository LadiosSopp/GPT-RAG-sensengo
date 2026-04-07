#!/usr/bin/env python3
"""
transcript_insight_pipeline.py — 通話逐字稿分析 Pipeline
========================================================

從 Blob Storage 的 documents/transcripts_merged 資料夾讀取新的通話紀錄，
使用 GPT-5.4 擷取影響推銷成功或失敗的關鍵資訊，更新推薦話術檔案，
並將處理完的檔案移動到已處理資料夾。

Blob 結構：
  documents/
    transcripts_merged/          ← 待處理的通話紀錄 (.txt + .json)
    transcripts_processed/       ← 處理完成的通話紀錄
    sales_insights/
      成功話術分析.json          ← 成功案例的分析結果
      失敗話術分析.json          ← 失敗案例的分析結果
      成功話術分析.md            ← 成功案例的可讀報告
      失敗話術分析.md            ← 失敗案例的可讀報告

使用方法：
  1. 確保已用 `az login` 登入 Azure
  2. 執行：
     python scripts/transcript_insight_pipeline.py

  可選參數：
    --dry-run         只列出待處理檔案，不實際執行
    --force           忽略已處理記錄，強制重新分析所有檔案
    --max N           最多處理 N 個通話 (預設: 全部)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from azure.identity import AzureCliCredential
from azure.storage.blob import BlobServiceClient
from openai import AzureOpenAI

# ============================================================================
# Configuration
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

STORAGE_ACCOUNT = os.environ.get("STORAGE_ACCOUNT_NAME", "st2v3lfktkn4xam")
CONTAINER_NAME = os.environ.get("DOCUMENTS_CONTAINER", "documents")
SOURCE_FOLDER = "transcripts_merged"
PROCESSED_FOLDER = "transcripts_processed"
INSIGHTS_FOLDER = "sales_insights"

# Azure OpenAI (GPT-5.4)
AOAI_DEPLOYMENT = os.environ.get("AOAI_DEPLOYMENT", "gpt-5.4")
AOAI_API_VERSION = os.environ.get("AOAI_API_VERSION", "2024-12-01-preview")
TENANT_ID = os.environ.get("AZURE_TENANT_ID", "45f5172d-7608-4bd1-a52a-c3a7de0423d3")

# ============================================================================
# Azure Clients
# ============================================================================

def get_credential():
    return AzureCliCredential()


def get_blob_service(credential) -> BlobServiceClient:
    return BlobServiceClient(
        f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=credential,
    )


def get_openai_client(credential) -> AzureOpenAI:
    """Build Azure OpenAI client, discovering endpoint via az CLI."""
    # Try to get endpoint from az CLI
    result = subprocess.run(
        'az cognitiveservices account list -g GPRAG '
        '--query "[?kind==\'AIServices\'].properties.endpoint" -o tsv',
        shell=True, capture_output=True, text=True,
    )
    endpoint = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""

    if not endpoint:
        # Fallback: known endpoint
        endpoint = "https://aif-2v3lfktkn4xam-gprag.cognitiveservices.azure.com"
        logger.warning(f"Could not discover endpoint via az CLI, using fallback: {endpoint}")

    # Get AAD token (with correct tenant)
    token_result = subprocess.run(
        f"az account get-access-token --resource https://cognitiveservices.azure.com/ "
        f"--tenant {TENANT_ID} --query accessToken -o tsv",
        shell=True, capture_output=True, text=True,
    )
    token = token_result.stdout.strip()
    if not token:
        raise RuntimeError("Failed to get AAD token. Run 'az login' first.")

    logger.info(f"OpenAI endpoint: {endpoint}")
    logger.info(f"Deployment: {AOAI_DEPLOYMENT}")

    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_version=AOAI_API_VERSION,
        azure_ad_token=token,
    )


# ============================================================================
# Blob Operations
# ============================================================================

def list_source_transcripts(blob_service: BlobServiceClient) -> List[str]:
    """List all .txt files in the source folder (each represents a call)."""
    container = blob_service.get_container_client(CONTAINER_NAME)
    blobs = container.list_blobs(name_starts_with=f"{SOURCE_FOLDER}/")
    return sorted(
        b.name for b in blobs
        if b.name.endswith(".txt") and b.name.count("/") == 1
    )


def list_processed_ids(blob_service: BlobServiceClient) -> set:
    """Get set of call IDs already processed."""
    container = blob_service.get_container_client(CONTAINER_NAME)
    blobs = container.list_blobs(name_starts_with=f"{PROCESSED_FOLDER}/")
    ids = set()
    for b in blobs:
        filename = b.name.split("/")[-1]
        if filename.endswith(".txt"):
            ids.add(filename.replace(".txt", ""))
    return ids


def read_blob_text(blob_service: BlobServiceClient, blob_path: str) -> str:
    container = blob_service.get_container_client(CONTAINER_NAME)
    blob_client = container.get_blob_client(blob_path)
    return blob_client.download_blob().readall().decode("utf-8")


def read_blob_json(blob_service: BlobServiceClient, blob_path: str) -> Optional[dict]:
    try:
        text = read_blob_text(blob_service, blob_path)
        return json.loads(text)
    except Exception:
        return None


def upload_blob_text(blob_service: BlobServiceClient, blob_path: str, content: str):
    container = blob_service.get_container_client(CONTAINER_NAME)
    blob_client = container.get_blob_client(blob_path)
    blob_client.upload_blob(content.encode("utf-8"), overwrite=True)
    logger.info(f"  Uploaded: {blob_path}")


def copy_and_delete_blob(blob_service: BlobServiceClient, src_path: str, dst_path: str):
    """Copy blob from src to dst, then delete src."""
    container = blob_service.get_container_client(CONTAINER_NAME)
    src_blob = container.get_blob_client(src_path)
    dst_blob = container.get_blob_client(dst_path)

    # Copy
    src_url = src_blob.url
    dst_blob.start_copy_from_url(src_url)

    # Wait for copy to complete
    props = dst_blob.get_blob_properties()
    while props.copy.status == "pending":
        time.sleep(0.5)
        props = dst_blob.get_blob_properties()

    if props.copy.status != "success":
        raise RuntimeError(f"Copy failed for {src_path}: {props.copy.status}")

    # Delete source
    src_blob.delete_blob()


def move_to_processed(blob_service: BlobServiceClient, call_id: str):
    """Move both .txt and .json files to the processed folder."""
    for ext in [".txt", ".json"]:
        src = f"{SOURCE_FOLDER}/{call_id}{ext}"
        dst = f"{PROCESSED_FOLDER}/{call_id}{ext}"
        try:
            copy_and_delete_blob(blob_service, src, dst)
            logger.info(f"  Moved: {src} → {dst}")
        except Exception as e:
            logger.warning(f"  Could not move {src}: {e}")


# ============================================================================
# GPT-5.4 Analysis
# ============================================================================

ANALYSIS_SYSTEM_PROMPT = """你是東森購物的電話行銷分析專家。你的任務是分析客服與客戶之間的電話通話紀錄，判斷推銷結果，並擷取關鍵資訊。

分析輸出必須是嚴格的 JSON 格式，包含以下欄位：

{
  "call_id": "通話ID",
  "result": "成功" 或 "失敗",
  "result_confidence": 0.0-1.0 之間的信心分數,
  "result_reason": "判斷成功/失敗的具體依據（1-2句話）",
  "customer_profile": {
    "attitude": "客戶態度描述（例如：感興趣、猶豫、拒絕、冷淡）",
    "concerns": ["客戶的疑慮或顧慮清單"],
    "interests": ["客戶感興趣的點"]
  },
  "key_factors": [
    {
      "factor": "影響結果的關鍵因素",
      "type": "正面" 或 "負面",
      "description": "詳細描述"
    }
  ],
  "effective_strategies": [
    {
      "strategy": "策略名稱",
      "example_quote": "客服的原話或近似引用",
      "why_effective": "為什麼這個策略有效/無效"
    }
  ],
  "recommended_scripts": [
    {
      "scenario": "適用場景（例如：開場白、處理價格疑慮、促成下單）",
      "script": "建議的話術",
      "rationale": "為什麼建議這段話術"
    }
  ],
  "improvement_suggestions": ["改善建議（僅當結果=失敗時填寫）"],
  "summary": "整通電話的簡短摘要（2-3句話）"
}

分析時請注意：
1. 從對話的上下文判斷推銷是否成功（例如：客戶是否同意辦卡、是否提供信用卡資訊、是否同意卡位）
2. 識別客服使用的銷售技巧（例如：建立關係、創造急迫感、處理異議、提供價值主張）
3. 識別導致成功或失敗的轉折點
4. 提取可復用的推銷話術，並說明適用場景
5. 只輸出 JSON，不要有其他文字"""


def analyze_transcript(oai_client: AzureOpenAI, call_id: str, transcript_text: str) -> dict:
    """Use GPT-5.4 to analyze a single transcript."""
    user_prompt = f"""請分析以下通話紀錄，call_id 為 "{call_id}"：

---
{transcript_text}
---

請輸出 JSON 格式的分析結果。"""

    response = oai_client.chat.completions.create(
        model=AOAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_completion_tokens=4096,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    usage = response.usage

    logger.info(
        f"  GPT-5.4 usage: prompt={usage.prompt_tokens}, "
        f"completion={usage.completion_tokens}, total={usage.total_tokens}"
    )

    return json.loads(content)


# ============================================================================
# Insight Aggregation
# ============================================================================

def load_existing_insights(blob_service: BlobServiceClient, filename: str) -> dict:
    """Load existing insights JSON from blob, or return empty structure."""
    blob_path = f"{INSIGHTS_FOLDER}/{filename}"
    try:
        text = read_blob_text(blob_service, blob_path)
        return json.loads(text)
    except Exception:
        return {"last_updated": None, "total_calls": 0, "analyses": []}


def save_insights(blob_service: BlobServiceClient, filename: str, data: dict):
    """Save insights JSON to blob."""
    blob_path = f"{INSIGHTS_FOLDER}/{filename}"
    content = json.dumps(data, ensure_ascii=False, indent=2)
    upload_blob_text(blob_service, blob_path, content)


def generate_markdown_report(data: dict, category: str) -> str:
    """Generate a human-readable markdown report from insight data."""
    lines = []
    emoji = "✅" if category == "成功" else "❌"
    lines.append(f"# {emoji} {category}話術分析報告")
    lines.append("")
    lines.append(f"> 最後更新：{data.get('last_updated', 'N/A')}")
    lines.append(f"> 分析通話數：{data.get('total_calls', 0)}")
    lines.append("")

    # Aggregate strategies across all calls
    all_strategies = []
    all_scripts = []
    all_improvements = []

    for analysis in data.get("analyses", []):
        call_id = analysis.get("call_id", "unknown")

        lines.append(f"---")
        lines.append(f"## 📞 通話 {call_id}")
        lines.append("")
        lines.append(f"**摘要**：{analysis.get('summary', 'N/A')}")
        lines.append(f"**判斷依據**：{analysis.get('result_reason', 'N/A')}")
        lines.append(f"**信心分數**：{analysis.get('result_confidence', 'N/A')}")
        lines.append("")

        # Customer profile
        profile = analysis.get("customer_profile", {})
        if profile:
            lines.append(f"### 客戶概況")
            lines.append(f"- **態度**：{profile.get('attitude', 'N/A')}")
            concerns = profile.get("concerns", [])
            if concerns:
                lines.append(f"- **顧慮**：{', '.join(concerns)}")
            interests = profile.get("interests", [])
            if interests:
                lines.append(f"- **興趣**：{', '.join(interests)}")
            lines.append("")

        # Key factors
        factors = analysis.get("key_factors", [])
        if factors:
            lines.append("### 關鍵因素")
            for f in factors:
                icon = "🟢" if f.get("type") == "正面" else "🔴"
                lines.append(f"- {icon} **{f.get('factor', '')}**：{f.get('description', '')}")
            lines.append("")

        # Effective strategies
        strategies = analysis.get("effective_strategies", [])
        if strategies:
            lines.append("### 話術策略")
            for s in strategies:
                lines.append(f"- **{s.get('strategy', '')}**")
                if s.get("example_quote"):
                    lines.append(f"  > 「{s['example_quote']}」")
                lines.append(f"  - 分析：{s.get('why_effective', '')}")
            lines.append("")
            all_strategies.extend(strategies)

        # Recommended scripts
        scripts = analysis.get("recommended_scripts", [])
        if scripts:
            lines.append("### 推薦話術")
            for sc in scripts:
                lines.append(f"- **場景：{sc.get('scenario', '')}**")
                lines.append(f"  > 「{sc.get('script', '')}」")
                lines.append(f"  - 原因：{sc.get('rationale', '')}")
            lines.append("")
            all_scripts.extend(scripts)

        # Improvement suggestions (failure only)
        improvements = analysis.get("improvement_suggestions", [])
        if improvements:
            lines.append("### 改善建議")
            for imp in improvements:
                lines.append(f"- {imp}")
            lines.append("")
            all_improvements.extend(improvements)

    # Aggregated summary section
    if all_scripts:
        lines.append("---")
        lines.append(f"## 📋 {category}案例 — 彙整推薦話術")
        lines.append("")

        # Group by scenario
        scenario_map: Dict[str, list] = {}
        for sc in all_scripts:
            scenario = sc.get("scenario", "其他")
            scenario_map.setdefault(scenario, []).append(sc)

        for scenario, items in scenario_map.items():
            lines.append(f"### {scenario}")
            for item in items:
                lines.append(f"- 「{item.get('script', '')}」")
                lines.append(f"  - _{item.get('rationale', '')}_")
            lines.append("")

    if all_improvements:
        lines.append("---")
        lines.append("## ⚠️ 彙整改善建議")
        lines.append("")
        seen = set()
        for imp in all_improvements:
            if imp not in seen:
                lines.append(f"- {imp}")
                seen.add(imp)
        lines.append("")

    return "\n".join(lines)


def update_insights(
    blob_service: BlobServiceClient,
    new_analyses: List[dict],
):
    """Update the success/failure insight files with new analyses."""
    success_data = load_existing_insights(blob_service, "成功話術分析.json")
    failure_data = load_existing_insights(blob_service, "失敗話術分析.json")

    # Collect existing call IDs to avoid duplicates
    success_ids = {a["call_id"] for a in success_data.get("analyses", [])}
    failure_ids = {a["call_id"] for a in failure_data.get("analyses", [])}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    for analysis in new_analyses:
        call_id = analysis.get("call_id", "")
        result = analysis.get("result", "").strip()

        if result == "成功":
            if call_id not in success_ids:
                success_data.setdefault("analyses", []).append(analysis)
                success_ids.add(call_id)
        else:
            if call_id not in failure_ids:
                failure_data.setdefault("analyses", []).append(analysis)
                failure_ids.add(call_id)

    # Update metadata
    success_data["last_updated"] = now
    success_data["total_calls"] = len(success_data.get("analyses", []))
    failure_data["last_updated"] = now
    failure_data["total_calls"] = len(failure_data.get("analyses", []))

    # Save JSON
    save_insights(blob_service, "成功話術分析.json", success_data)
    save_insights(blob_service, "失敗話術分析.json", failure_data)

    # Generate and save markdown reports
    success_md = generate_markdown_report(success_data, "成功")
    failure_md = generate_markdown_report(failure_data, "失敗")
    upload_blob_text(blob_service, f"{INSIGHTS_FOLDER}/成功話術分析.md", success_md)
    upload_blob_text(blob_service, f"{INSIGHTS_FOLDER}/失敗話術分析.md", failure_md)

    logger.info(
        f"Insights updated: {success_data['total_calls']} success, "
        f"{failure_data['total_calls']} failure"
    )


# ============================================================================
# Main Pipeline
# ============================================================================

def run_pipeline(dry_run: bool = False, force: bool = False, max_calls: int = 0):
    logger.info("=" * 60)
    logger.info("通話逐字稿分析 Pipeline")
    logger.info("=" * 60)

    credential = get_credential()
    blob_service = get_blob_service(credential)

    # Step 1: Discover new transcripts
    logger.info("\n[Step 1] 掃描待處理的通話紀錄...")
    source_files = list_source_transcripts(blob_service)
    call_ids = [f.split("/")[-1].replace(".txt", "") for f in source_files]
    logger.info(f"  找到 {len(call_ids)} 個通話紀錄")

    if not force:
        processed_ids = list_processed_ids(blob_service)
        logger.info(f"  已處理: {len(processed_ids)} 個")
        pending_ids = [cid for cid in call_ids if cid not in processed_ids]
    else:
        pending_ids = call_ids

    if max_calls > 0:
        pending_ids = pending_ids[:max_calls]

    logger.info(f"  待處理: {len(pending_ids)} 個")

    if not pending_ids:
        logger.info("沒有新的通話紀錄需要處理。")
        return

    if dry_run:
        logger.info("\n[Dry Run] 列出待處理的通話:")
        for cid in pending_ids:
            logger.info(f"  - {cid}")
        return

    # Step 2: Initialize OpenAI client
    logger.info("\n[Step 2] 初始化 GPT-5.4 客戶端...")
    oai_client = get_openai_client(credential)

    # Step 3: Analyze each transcript
    logger.info(f"\n[Step 3] 開始分析 {len(pending_ids)} 個通話...")
    new_analyses = []
    failed_calls = []

    for i, call_id in enumerate(pending_ids, 1):
        logger.info(f"\n--- [{i}/{len(pending_ids)}] 分析通話 {call_id} ---")

        try:
            # Read transcript text
            txt_path = f"{SOURCE_FOLDER}/{call_id}.txt"
            transcript_text = read_blob_text(blob_service, txt_path)

            # Skip empty transcripts
            non_empty_lines = [
                line for line in transcript_text.strip().split("\n")
                if line.strip() and not line.strip().endswith("客戶：") and not line.strip().endswith("客服：")
            ]
            if len(non_empty_lines) < 3:
                logger.warning(f"  通話 {call_id} 內容過短（{len(non_empty_lines)} 行有效對話），跳過")
                # Still move to processed
                move_to_processed(blob_service, call_id)
                continue

            # Analyze with GPT-5.4
            analysis = analyze_transcript(oai_client, call_id, transcript_text)
            analysis["call_id"] = call_id  # ensure call_id is set
            new_analyses.append(analysis)

            result_label = analysis.get("result", "unknown")
            logger.info(f"  結果: {result_label} (信心: {analysis.get('result_confidence', '?')})")
            logger.info(f"  摘要: {analysis.get('summary', 'N/A')[:80]}")

            # Move to processed
            move_to_processed(blob_service, call_id)

        except Exception as e:
            logger.error(f"  分析失敗: {e}", exc_info=True)
            failed_calls.append((call_id, str(e)))

    # Step 4: Update insight files
    if new_analyses:
        logger.info(f"\n[Step 4] 更新推薦話術檔案 ({len(new_analyses)} 個新分析)...")
        update_insights(blob_service, new_analyses)
    else:
        logger.info("\n[Step 4] 無新分析結果，跳過更新。")

    # Summary
    success_count = sum(1 for a in new_analyses if a.get("result") == "成功")
    failure_count = sum(1 for a in new_analyses if a.get("result") != "成功")

    logger.info("\n" + "=" * 60)
    logger.info("Pipeline 完成")
    logger.info(f"  成功分析: {len(new_analyses)} 個通話")
    logger.info(f"    - 推銷成功: {success_count}")
    logger.info(f"    - 推銷失敗: {failure_count}")
    if failed_calls:
        logger.info(f"  分析失敗: {len(failed_calls)} 個")
        for cid, err in failed_calls:
            logger.info(f"    - {cid}: {err}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="通話逐字稿分析 Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="只列出待處理檔案，不實際執行")
    parser.add_argument("--force", action="store_true", help="忽略已處理記錄，強制重新分析")
    parser.add_argument("--max", type=int, default=0, help="最多處理 N 個通話 (0=全部)")
    args = parser.parse_args()

    run_pipeline(dry_run=args.dry_run, force=args.force, max_calls=args.max)


if __name__ == "__main__":
    main()
