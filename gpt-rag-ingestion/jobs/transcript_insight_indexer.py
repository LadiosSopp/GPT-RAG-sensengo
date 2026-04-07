"""
Transcript Insight Indexer
==========================

Scheduled job that:
1. Monitors Blob Storage ``documents/transcripts_merged`` for new call transcript
   ``.txt`` files (merged STT output).
2. Uses GPT-5.4 (or configured deployment) to extract key success/failure factors,
   effective sales strategies, and recommended scripts.
3. Aggregates analyses into two insight files (成功 / 失敗) in
   ``documents/sales_insights/``.
4. Moves processed transcripts to ``documents/transcripts_processed/``.

Env / App Config keys:
    CRON_RUN_TRANSCRIPT_INSIGHT  – cron expression for scheduling
    TRANSCRIPT_INSIGHT_DEPLOYMENT – LLM deployment (default: CHAT_DEPLOYMENT_NAME)
    TRANSCRIPT_INSIGHT_SOURCE     – source blob folder (default: transcripts_merged)
    TRANSCRIPT_INSIGHT_PROCESSED  – processed folder (default: transcripts_processed)
    TRANSCRIPT_INSIGHT_OUTPUT     – output folder (default: sales_insights)
"""

import asyncio
import dataclasses
import inspect
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from azure.identity.aio import (
    AzureCliCredential,
    ChainedTokenCredential,
    ManagedIdentityCredential,
)
from azure.storage.blob.aio import BlobServiceClient

from dependencies import get_config
from utils.tools import is_azure_environment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Analysis prompt
# ---------------------------------------------------------------------------
ANALYSIS_SYSTEM_PROMPT = """\
你是東森購物的電話行銷分析專家。你的任務是分析客服與客戶之間的電話通話紀錄，判斷推銷結果，並擷取關鍵資訊。

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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class TranscriptInsightConfig:
    # Blob Storage
    storage_account_name: str = ""
    container_name: str = "documents"
    source_folder: str = "transcripts_merged"
    processed_folder: str = "transcripts_processed"
    output_folder: str = "sales_insights"
    jobs_log_container: str = "jobs"

    # LLM
    insight_deployment: str = ""  # override; falls back to CHAT_DEPLOYMENT_NAME

    # Behaviour
    max_concurrency: int = 4
    indexer_name: str = "transcript-insight-indexer"

    @staticmethod
    def from_app_config() -> "TranscriptInsightConfig":
        app = get_config()
        return TranscriptInsightConfig(
            storage_account_name=app.get("STORAGE_ACCOUNT_NAME", ""),
            container_name=app.get("DOCUMENTS_STORAGE_CONTAINER", "documents"),
            source_folder=app.get("TRANSCRIPT_INSIGHT_SOURCE", "transcripts_merged"),
            processed_folder=app.get("TRANSCRIPT_INSIGHT_PROCESSED", "transcripts_processed"),
            output_folder=app.get("TRANSCRIPT_INSIGHT_OUTPUT", "sales_insights"),
            jobs_log_container=app.get("JOBS_LOG_CONTAINER", "jobs"),
            insight_deployment=app.get("TRANSCRIPT_INSIGHT_DEPLOYMENT", ""),
            max_concurrency=int(app.get("TRANSCRIPT_INSIGHT_MAX_CONCURRENCY", "4")),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Markdown report generator
# ---------------------------------------------------------------------------
def _generate_markdown_report(data: dict, category: str) -> str:
    lines: List[str] = []
    emoji = "✅" if category == "成功" else "❌"
    lines.append(f"# {emoji} {category}話術分析報告")
    lines.append("")
    lines.append(f"> 最後更新：{data.get('last_updated', 'N/A')}")
    lines.append(f"> 分析通話數：{data.get('total_calls', 0)}")
    lines.append("")

    all_scripts: List[dict] = []
    all_improvements: List[str] = []

    for analysis in data.get("analyses", []):
        call_id = analysis.get("call_id", "unknown")
        lines.append("---")
        lines.append(f"## 📞 通話 {call_id}")
        lines.append("")
        lines.append(f"**摘要**：{analysis.get('summary', 'N/A')}")
        lines.append(f"**判斷依據**：{analysis.get('result_reason', 'N/A')}")
        lines.append(f"**信心分數**：{analysis.get('result_confidence', 'N/A')}")
        lines.append("")

        profile = analysis.get("customer_profile", {})
        if profile:
            lines.append("### 客戶概況")
            lines.append(f"- **態度**：{profile.get('attitude', 'N/A')}")
            concerns = profile.get("concerns", [])
            if concerns:
                lines.append(f"- **顧慮**：{', '.join(concerns)}")
            interests = profile.get("interests", [])
            if interests:
                lines.append(f"- **興趣**：{', '.join(interests)}")
            lines.append("")

        factors = analysis.get("key_factors", [])
        if factors:
            lines.append("### 關鍵因素")
            for f in factors:
                icon = "🟢" if f.get("type") == "正面" else "🔴"
                lines.append(f"- {icon} **{f.get('factor', '')}**：{f.get('description', '')}")
            lines.append("")

        strategies = analysis.get("effective_strategies", [])
        if strategies:
            lines.append("### 話術策略")
            for s in strategies:
                lines.append(f"- **{s.get('strategy', '')}**")
                if s.get("example_quote"):
                    lines.append(f"  > 「{s['example_quote']}」")
                lines.append(f"  - 分析：{s.get('why_effective', '')}")
            lines.append("")

        scripts = analysis.get("recommended_scripts", [])
        if scripts:
            lines.append("### 推薦話術")
            for sc in scripts:
                lines.append(f"- **場景：{sc.get('scenario', '')}**")
                lines.append(f"  > 「{sc.get('script', '')}」")
                lines.append(f"  - 原因：{sc.get('rationale', '')}")
            lines.append("")
            all_scripts.extend(scripts)

        improvements = analysis.get("improvement_suggestions", [])
        if improvements:
            lines.append("### 改善建議")
            for imp in improvements:
                lines.append(f"- {imp}")
            lines.append("")
            all_improvements.extend(improvements)

    # Aggregated summary
    if all_scripts:
        lines.append("---")
        lines.append(f"## 📋 {category}案例 — 彙整推薦話術")
        lines.append("")
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
        seen: set = set()
        for imp in all_improvements:
            if imp not in seen:
                lines.append(f"- {imp}")
                seen.add(imp)
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------
class TranscriptInsightIndexer:
    """
    Flow per run:
        1. List .txt files in source_folder inside documents container
        2. Determine which call_ids haven't been processed yet
        3. For each transcript:
           a. Read .txt content
           b. Call GPT to analyse
           c. Store analysis result
           d. Move .txt + .json to processed_folder
        4. Update aggregated insight files (成功/失敗)
        5. Write run summary to jobs container
    """

    def __init__(self, cfg: Optional[TranscriptInsightConfig] = None):
        self.cfg = cfg or TranscriptInsightConfig.from_app_config()
        self._credential: Optional[ChainedTokenCredential] = None
        self._blob_service: Optional[BlobServiceClient] = None

    # ── Clients ───────────────────────────────────────────────────
    async def _ensure_clients(self):
        if not self._credential:
            client_id = os.environ.get("AZURE_CLIENT_ID")
            self._credential = ChainedTokenCredential(
                AzureCliCredential(),
                ManagedIdentityCredential(client_id=client_id),
            )
        if not self._blob_service:
            acc = self.cfg.storage_account_name
            self._blob_service = BlobServiceClient(
                f"https://{acc}.blob.core.windows.net",
                credential=self._credential,
            )

    async def _close_clients(self):
        if self._blob_service:
            try:
                await self._blob_service.close()
            except Exception:
                pass
        if self._credential and hasattr(self._credential, "close"):
            try:
                res = self._credential.close()
                if inspect.isawaitable(res):
                    await res
            except Exception:
                pass

    # ── Blob helpers ──────────────────────────────────────────────
    async def _list_source_txt(self) -> List[str]:
        """Return call IDs for .txt files in source_folder."""
        container = self._blob_service.get_container_client(self.cfg.container_name)
        prefix = f"{self.cfg.source_folder}/"
        ids: List[str] = []
        async for blob in container.list_blobs(name_starts_with=prefix):
            name = blob.name
            if name.endswith(".txt") and name.count("/") == 1:
                call_id = name.split("/")[-1].replace(".txt", "")
                ids.append(call_id)
        return sorted(ids)

    async def _list_processed_ids(self) -> set:
        """Return set of already-processed call IDs."""
        container = self._blob_service.get_container_client(self.cfg.container_name)
        prefix = f"{self.cfg.processed_folder}/"
        ids: set = set()
        async for blob in container.list_blobs(name_starts_with=prefix):
            name = blob.name.split("/")[-1]
            if name.endswith(".txt"):
                ids.add(name.replace(".txt", ""))
        return ids

    async def _read_blob_text(self, blob_path: str) -> str:
        container = self._blob_service.get_container_client(self.cfg.container_name)
        blob = container.get_blob_client(blob_path)
        download = await blob.download_blob()
        raw = await download.readall()
        return raw.decode("utf-8")

    async def _upload_blob_text(self, blob_path: str, content: str):
        container = self._blob_service.get_container_client(self.cfg.container_name)
        blob = container.get_blob_client(blob_path)
        await blob.upload_blob(content.encode("utf-8"), overwrite=True)
        logger.info(f"[{self.cfg.indexer_name}] Uploaded {blob_path}")

    async def _read_blob_json(self, blob_path: str) -> Optional[dict]:
        try:
            text = await self._read_blob_text(blob_path)
            return json.loads(text)
        except Exception:
            return None

    async def _move_blob(self, src_path: str, dst_path: str):
        """Copy blob from src to dst inside the same container, then delete src."""
        container = self._blob_service.get_container_client(self.cfg.container_name)
        src_blob = container.get_blob_client(src_path)
        dst_blob = container.get_blob_client(dst_path)
        await dst_blob.start_copy_from_url(src_blob.url)
        # Wait for copy
        props = await dst_blob.get_blob_properties()
        while props.copy.status == "pending":
            await asyncio.sleep(0.5)
            props = await dst_blob.get_blob_properties()
        if props.copy.status != "success":
            raise RuntimeError(f"Copy failed for {src_path}: {props.copy.status}")
        await src_blob.delete_blob()
        logger.info(f"[{self.cfg.indexer_name}] Moved {src_path} → {dst_path}")

    async def _move_to_processed(self, call_id: str):
        """Move .txt and .json from source to processed folder."""
        for ext in (".txt", ".json"):
            src = f"{self.cfg.source_folder}/{call_id}{ext}"
            dst = f"{self.cfg.processed_folder}/{call_id}{ext}"
            try:
                await self._move_blob(src, dst)
            except Exception as e:
                logger.warning(f"[{self.cfg.indexer_name}] Could not move {src}: {e}")

    # ── LLM analysis ─────────────────────────────────────────────
    def _analyse_transcript(self, call_id: str, transcript_text: str) -> dict:
        """Use LLM to analyse a single transcript. Runs synchronously."""
        from tools import AzureOpenAIClient

        aoai = AzureOpenAIClient(document_filename="transcript-insight")
        if self.cfg.insight_deployment:
            aoai.chat_deployment = self.cfg.insight_deployment

        user_prompt = (
            f'請分析以下通話紀錄，call_id 為 "{call_id}"：\n\n'
            f"---\n{transcript_text[:12000]}\n---\n\n"
            "請輸出 JSON 格式的分析結果。"
        )

        messages = [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        resp = aoai.client.chat.completions.create(
            model=aoai.chat_deployment,
            messages=messages,
            temperature=0.3,
            max_completion_tokens=4096,
            response_format={"type": "json_object"},
        )

        usage = resp.usage
        logger.info(
            f"[{self.cfg.indexer_name}] GPT usage: prompt={usage.prompt_tokens}, "
            f"completion={usage.completion_tokens}, total={usage.total_tokens}"
        )

        result = json.loads(resp.choices[0].message.content)
        result["call_id"] = call_id
        return result

    # ── Insight aggregation ───────────────────────────────────────
    async def _load_insights(self, filename: str) -> dict:
        blob_path = f"{self.cfg.output_folder}/{filename}"
        data = await self._read_blob_json(blob_path)
        return data or {"last_updated": None, "total_calls": 0, "analyses": []}

    async def _save_insights(self, new_analyses: List[dict]):
        """Merge new analyses into existing insight files and save."""
        success_data = await self._load_insights("成功話術分析.json")
        failure_data = await self._load_insights("失敗話術分析.json")

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

        success_data["last_updated"] = now
        success_data["total_calls"] = len(success_data.get("analyses", []))
        failure_data["last_updated"] = now
        failure_data["total_calls"] = len(failure_data.get("analyses", []))

        # Save JSON
        out = self.cfg.output_folder
        await self._upload_blob_text(
            f"{out}/成功話術分析.json",
            json.dumps(success_data, ensure_ascii=False, indent=2),
        )
        await self._upload_blob_text(
            f"{out}/失敗話術分析.json",
            json.dumps(failure_data, ensure_ascii=False, indent=2),
        )

        # Save readable markdown reports
        await self._upload_blob_text(
            f"{out}/成功話術分析.md",
            _generate_markdown_report(success_data, "成功"),
        )
        await self._upload_blob_text(
            f"{out}/失敗話術分析.md",
            _generate_markdown_report(failure_data, "失敗"),
        )

        logger.info(
            f"[{self.cfg.indexer_name}] Insights updated: "
            f"{success_data['total_calls']} success, {failure_data['total_calls']} failure"
        )

    # ── Per-call processing ───────────────────────────────────────
    async def _process_one(self, call_id: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {"call_id": call_id, "status": "success"}
        try:
            # Read transcript
            txt_path = f"{self.cfg.source_folder}/{call_id}.txt"
            transcript_text = await self._read_blob_text(txt_path)

            # Skip empty / near-empty transcripts
            non_empty = [
                line for line in transcript_text.strip().split("\n")
                if line.strip()
                and not line.strip().endswith("客戶：")
                and not line.strip().endswith("客服：")
            ]
            if len(non_empty) < 3:
                logger.warning(
                    f"[{self.cfg.indexer_name}] {call_id} too short "
                    f"({len(non_empty)} lines), skipping analysis"
                )
                await self._move_to_processed(call_id)
                result["status"] = "skipped"
                result["reason"] = "too_short"
                return result

            # Analyse with LLM (sync → thread to avoid blocking event loop)
            analysis = await asyncio.to_thread(
                self._analyse_transcript, call_id, transcript_text
            )

            result["analysis"] = analysis
            result["result_label"] = analysis.get("result", "unknown")
            logger.info(
                f"[{self.cfg.indexer_name}] {call_id}: "
                f"{analysis.get('result')} (confidence={analysis.get('result_confidence')})"
            )

            # Move to processed
            await self._move_to_processed(call_id)

        except Exception as exc:
            logger.exception(f"[{self.cfg.indexer_name}] Error processing {call_id}")
            result["status"] = "error"
            result["error"] = str(exc)

        return result

    # ── Run summary ───────────────────────────────────────────────
    async def _write_summary(self, summary: dict, run_id: str):
        try:
            jobs = self._blob_service.get_container_client(self.cfg.jobs_log_container)
            try:
                await jobs.create_container()
            except Exception:
                pass
            blob = jobs.get_blob_client(
                f"{self.cfg.indexer_name}/{run_id}/summary.json"
            )
            await blob.upload_blob(
                json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"),
                overwrite=True,
            )
        except Exception:
            logger.exception(f"[{self.cfg.indexer_name}] Failed to write run summary")

    # ── Public entry point ────────────────────────────────────────
    async def run(self) -> None:
        await self._ensure_clients()
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        logger.info(f"[{self.cfg.indexer_name}] Starting run {run_id}")

        summary = {
            "indexerType": self.cfg.indexer_name,
            "runId": run_id,
            "runStartedAt": _utc_now_iso(),
            "runFinishedAt": None,
            "sourceFolder": f"{self.cfg.container_name}/{self.cfg.source_folder}",
            "blobsFound": 0,
            "pending": 0,
            "analysed": 0,
            "skipped": 0,
            "failed": 0,
            "successCalls": 0,
            "failureCalls": 0,
            "status": "running",
        }

        try:
            # 1. Discover source files
            all_ids = await self._list_source_txt()
            processed_ids = await self._list_processed_ids()
            pending_ids = [cid for cid in all_ids if cid not in processed_ids]

            summary["blobsFound"] = len(all_ids)
            summary["pending"] = len(pending_ids)
            logger.info(
                f"[{self.cfg.indexer_name}] Found {len(all_ids)} transcripts, "
                f"{len(pending_ids)} pending"
            )

            if not pending_ids:
                summary["status"] = "completed"
                summary["runFinishedAt"] = _utc_now_iso()
                await self._write_summary(summary, run_id)
                await self._close_clients()
                return

            # 2. Process each transcript (limited concurrency)
            sem = asyncio.Semaphore(self.cfg.max_concurrency)

            async def _limited(call_id: str):
                async with sem:
                    return await self._process_one(call_id)

            results = await asyncio.gather(
                *(_limited(cid) for cid in pending_ids),
                return_exceptions=True,
            )

            # 3. Collect analyses and update insight files
            new_analyses: List[dict] = []
            for r in results:
                if isinstance(r, Exception):
                    summary["failed"] += 1
                    continue
                if r.get("status") == "error":
                    summary["failed"] += 1
                elif r.get("status") == "skipped":
                    summary["skipped"] += 1
                else:
                    summary["analysed"] += 1
                    analysis = r.get("analysis")
                    if analysis:
                        new_analyses.append(analysis)
                        if analysis.get("result") == "成功":
                            summary["successCalls"] += 1
                        else:
                            summary["failureCalls"] += 1

            if new_analyses:
                await self._save_insights(new_analyses)

            summary["status"] = "completed"

        except Exception:
            logger.exception(f"[{self.cfg.indexer_name}] Unexpected error in run")
            summary["status"] = "error"

        finally:
            summary["runFinishedAt"] = _utc_now_iso()
            await self._write_summary(summary, run_id)
            await self._close_clients()

        logger.info(
            f"[{self.cfg.indexer_name}] Finished: "
            f"analysed={summary['analysed']}, skipped={summary['skipped']}, "
            f"failed={summary['failed']}, "
            f"success={summary['successCalls']}, failure={summary['failureCalls']}"
        )
