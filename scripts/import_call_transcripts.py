"""
Import call transcripts from xlsx into Cosmos DB.

Usage:
    python scripts/import_call_transcripts.py

Requires:
    - azure-cosmos
    - azure-identity
    - openpyxl
"""
import asyncio
import logging
import sys
import os
import subprocess
import time
from azure.cosmos.aio import CosmosClient
from azure.core.credentials import AccessToken

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
# Suppress Azure SDK verbose noise
for _name in ["azure", "azure.cosmos", "azure.identity", "azure.core"]:
    logging.getLogger(_name).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────
COSMOS_ENDPOINT = "https://cosmos-2v3lfktkn4xam-gprag.documents.azure.com:443/"
DATABASE_NAME = "cosmos-db2v3lfktkn4xam-gprag"
CONTAINER_NAME = "call-transcripts"
XLSX_PATH = os.getenv(
    "CALL_TRANSCRIPTS_XLSX_PATH",
    r"C:\SynologyDrive\LTIMindtree\Projects\東森\sensengo\SampleData\會員卡推銷名單與通話文本_成功失敗各500人_去敏\會員卡推廣名單通話文本_成功失敗各500人_去敏.xlsx",
)
BATCH_SIZE = 50


class StaticTokenCredential:
    """A minimal async token credential backed by one CLI token fetch."""

    def __init__(self, token: str, expires_on: int):
        self._token = token
        self._expires_on = expires_on

    async def get_token(self, *scopes, **kwargs):
        return AccessToken(self._token, self._expires_on)


def get_cosmos_aad_token() -> str:
    result = subprocess.run(
        "az account get-access-token --resource https://cosmos.azure.com/ --query accessToken -o tsv",
        shell=True,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get Cosmos AAD token: {result.stderr.strip()}")
    return result.stdout.strip()


def parse_call_date(raw_date) -> str:
    """Parse date like '2026010912' → '2026-01-09'"""
    s = str(raw_date).strip()
    if len(s) >= 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def load_xlsx(path: str) -> list[dict]:
    """Load xlsx and return list of document dicts."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]

    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]  # ('客代', '通話ID', '通話日期', '推銷狀態', '通話文本')
    logger.info(f"Headers: {headers}")
    logger.info(f"Data rows: {len(rows) - 1}")

    documents = []
    for row in rows[1:]:
        customer_id = str(row[0]).strip() if row[0] else ""
        call_id = str(row[1]).strip() if row[1] else ""
        call_date = parse_call_date(row[2]) if row[2] else ""
        status = str(row[3]).strip() if row[3] else ""
        transcript = str(row[4]) if row[4] else ""

        doc = {
            "id": call_id,                     # unique document ID
            "customer_id": customer_id,         # partition key
            "call_id": call_id,
            "call_date": call_date,
            "status": status,                   # 成功 / 失敗
            "transcript": transcript,
            "source_file": "會員卡推廣名單通話文本_成功失敗各500人_去敏.xlsx",
        }
        documents.append(doc)

    wb.close()
    return documents


async def import_to_cosmos(documents: list[dict]):
    """Upsert documents into Cosmos DB."""
    cosmos_key = os.getenv("COSMOS_KEY")
    if cosmos_key:
        credential = cosmos_key
    else:
        token = get_cosmos_aad_token()
        credential = StaticTokenCredential(token, int(time.time()) + 3600)

    async with CosmosClient(COSMOS_ENDPOINT, credential=credential) as client:
        db = client.get_database_client(DATABASE_NAME)
        container = db.get_container_client(CONTAINER_NAME)

        success = 0
        failed = 0

        for i in range(0, len(documents), BATCH_SIZE):
            batch = documents[i:i + BATCH_SIZE]
            for doc in batch:
                try:
                    await container.upsert_item(doc)
                    success += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"Failed to upsert {doc['id']}: {e}")

            logger.info(f"Progress: {min(i + BATCH_SIZE, len(documents))}/{len(documents)} "
                        f"(success={success}, failed={failed})")

    logger.info(f"✅ Import complete: {success} succeeded, {failed} failed")


async def main():
    logger.info(f"Loading xlsx from: {XLSX_PATH}")
    documents = load_xlsx(XLSX_PATH)

    logger.info(f"Importing {len(documents)} documents to Cosmos DB...")
    logger.info(f"  Endpoint: {COSMOS_ENDPOINT}")
    logger.info(f"  Database: {DATABASE_NAME}")
    logger.info(f"  Container: {CONTAINER_NAME}")

    await import_to_cosmos(documents)


if __name__ == "__main__":
    asyncio.run(main())
