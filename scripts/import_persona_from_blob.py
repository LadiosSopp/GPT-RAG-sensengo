"""
從 Azure Blob Storage 下載 500_customer_persona_sanitized.xlsx，
匯入至 Azure SQL customer_persona_raw 資料表。

用法:
    python scripts/import_persona_from_blob.py
"""

import io
import pandas as pd
import pyodbc
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

# ── Blob Storage 設定 ──
STORAGE_ACCOUNT = "st2v3lfktkn4xam"
CONTAINER_NAME = "documents"
BLOB_PATH = "20260209/500_customer_persona_sanitized.xlsx"

# ── Azure SQL 設定 ──
SERVER = "ehs-sales-sqlserver.database.windows.net"
DATABASE = "salesagent"
USERNAME = "sqladmin"
PASSWORD = "EhsSales2026!Secure#"
TABLE = "customer_persona_raw"
CHUNK_SIZE = 200


def normalize_col(col: str) -> str:
    return str(col).replace("\r", " ").replace("\n", " ").strip()


def download_blob_to_dataframe() -> pd.DataFrame:
    """從 Blob Storage 下載 Excel 並轉為 DataFrame。"""
    credential = DefaultAzureCredential()
    blob_service = BlobServiceClient(
        f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=credential,
    )
    blob_client = blob_service.get_blob_client(CONTAINER_NAME, BLOB_PATH)

    print(f"Downloading: {BLOB_PATH} ...")
    data = blob_client.download_blob().readall()
    print(f"Downloaded {len(data):,} bytes")

    df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    df.columns = [normalize_col(c) for c in df.columns]
    df = df.fillna("")
    print(f"Excel rows: {len(df)}, columns: {list(df.columns)}")
    return df


def import_to_sql(df: pd.DataFrame) -> None:
    """將 DataFrame 匯入 Azure SQL customer_persona_raw。"""
    conn_str = (
        "DRIVER={SQL Server};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"UID={USERNAME};"
        f"PWD={PASSWORD};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    conn = pyodbc.connect(conn_str)
    cur = conn.cursor()

    # 重建資料表（persona 欄位用 NVARCHAR(MAX)）
    print("Dropping old table ...")
    cur.execute(f"IF OBJECT_ID('{TABLE}', 'U') IS NOT NULL DROP TABLE [{TABLE}]")
    conn.commit()

    col_defs_list = []
    for c in df.columns:
        if c == "persona":
            col_defs_list.append(f"[{c}] NVARCHAR(MAX) NULL")
        else:
            col_defs_list.append(f"[{c}] NVARCHAR(4000) NULL")
    col_defs = ",\n    ".join(col_defs_list)
    create_sql = f"""CREATE TABLE [{TABLE}] (
    [row_id] INT IDENTITY(1,1) PRIMARY KEY,
    {col_defs}
)"""
    print("Creating table ...")
    cur.execute(create_sql)
    conn.commit()

    # 逐筆插入
    cols_sql = ", ".join(f"[{c}]" for c in df.columns)
    placeholders = ", ".join("?" for _ in df.columns)
    insert_sql = f"INSERT INTO [{TABLE}] ({cols_sql}) VALUES ({placeholders})"

    total = len(df)
    for i, row in enumerate(df.itertuples(index=False, name=None), 1):
        values = [str(v) for v in row]
        cur.execute(insert_sql, values)
        if i % CHUNK_SIZE == 0 or i == total:
            conn.commit()
            print(f"Inserted rows: {i}/{total}")

    count = cur.execute(f"SELECT COUNT(1) FROM [{TABLE}]").fetchone()[0]
    print(f"Done. Verified rows in SQL: {count}")

    cur.close()
    conn.close()


def main() -> None:
    df = download_blob_to_dataframe()
    import_to_sql(df)


if __name__ == "__main__":
    main()
