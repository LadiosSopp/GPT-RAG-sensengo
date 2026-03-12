import pandas as pd
import pyodbc

CSV_PATH = r"c:\SynologyDrive\LTIMindtree\Projects\東森\sensengo\SampleData\會員卡推銷名單與通話文本_成功失敗各500人_去敏\persona_random_pick.1K.csv"
SERVER = "ehs-sales-sqlserver.database.windows.net"
DATABASE = "salesagent"
USERNAME = "sqladmin"
PASSWORD = "EhsSales2026!Secure#"
TABLE = "customer_persona_raw"
CHUNK_SIZE = 200


def normalize_col(col: str) -> str:
    col = str(col).replace("\r", " ").replace("\n", " ").strip()
    return col


def main() -> None:
    df = pd.read_csv(CSV_PATH)
    df.columns = [normalize_col(c) for c in df.columns]
    df = df.fillna("")

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

    col_defs = ",\n    ".join(f"[{c}] NVARCHAR(4000) NULL" for c in df.columns)
    ddl = f"""
IF OBJECT_ID('{TABLE}', 'U') IS NOT NULL
    DROP TABLE [{TABLE}];
CREATE TABLE [{TABLE}] (
    [row_id] INT IDENTITY(1,1) PRIMARY KEY,
    {col_defs}
);
"""
    cur.execute(ddl)
    conn.commit()

    cols_sql = ", ".join(f"[{c}]" for c in df.columns)
    placeholders = ", ".join("?" for _ in df.columns)
    insert_sql = f"INSERT INTO [{TABLE}] ({cols_sql}) VALUES ({placeholders})"

    cur.fast_executemany = False
    total = len(df)
    for start in range(0, total, CHUNK_SIZE):
        end = min(start + CHUNK_SIZE, total)
        chunk = df.iloc[start:end]
        rows = [tuple(str(v) for v in row) for row in chunk.itertuples(index=False, name=None)]
        cur.executemany(insert_sql, rows)
        conn.commit()
        print(f"Inserted rows: {end}/{total}")

    count = cur.execute(f"SELECT COUNT(1) FROM [{TABLE}]").fetchone()[0]
    print(f"Imported rows: {count}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
