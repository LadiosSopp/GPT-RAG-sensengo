"""
Read sales insight analyses from Blob Storage and filter by customer call IDs.
"""
import json
import logging
from typing import List, Optional

from azure.identity.aio import ChainedTokenCredential, ManagedIdentityCredential, AzureCliCredential
from azure.storage.blob.aio import BlobServiceClient

from dependencies import get_config

logger = logging.getLogger(__name__)

CONTAINER_NAME = "documents"
INSIGHTS_FOLDER = "sales_insights"
SUCCESS_FILE = f"{INSIGHTS_FOLDER}/成功話術分析.json"
FAILURE_FILE = f"{INSIGHTS_FOLDER}/失敗話術分析.json"


class SalesInsightsClient:

    def __init__(self):
        cfg = get_config()
        account = cfg.get("STORAGE_ACCOUNT_NAME", "")
        self.blob_url = f"https://{account}.blob.core.windows.net"
        self.credential = ChainedTokenCredential(
            ManagedIdentityCredential(),
            AzureCliCredential(),
        )

    async def _read_blob_json(self, blob_path: str) -> Optional[dict]:
        try:
            async with BlobServiceClient(self.blob_url, credential=self.credential) as bsc:
                blob = bsc.get_blob_client(CONTAINER_NAME, blob_path)
                data = await blob.download_blob()
                content = await data.readall()
                return json.loads(content)
        except Exception as exc:
            logger.warning("Failed to read blob %s: %s", blob_path, exc)
            return None

    async def get_insights_for_customer(self, customer_id: str, call_ids: List[str]) -> dict:
        """Return success/failure analyses matching the given call_ids."""
        call_id_set = set(call_ids)

        success_data = await self._read_blob_json(SUCCESS_FILE)
        failure_data = await self._read_blob_json(FAILURE_FILE)

        result = {"customer_id": customer_id, "success": [], "failure": []}

        if success_data:
            for a in success_data.get("analyses", []):
                if a.get("call_id") in call_id_set:
                    result["success"].append(a)

        if failure_data:
            for a in failure_data.get("analyses", []):
                if a.get("call_id") in call_id_set:
                    result["failure"].append(a)

        result["total_matched"] = len(result["success"]) + len(result["failure"])
        return result

    async def get_all_insights(self) -> dict:
        """Return all analyses from both files."""
        success_data = await self._read_blob_json(SUCCESS_FILE)
        failure_data = await self._read_blob_json(FAILURE_FILE)
        return {
            "success": success_data or {},
            "failure": failure_data or {},
        }
