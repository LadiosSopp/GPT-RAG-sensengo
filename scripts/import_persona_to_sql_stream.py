import csv
import pyodbc

CSV_PATH = r"c:\SynologyDrive\LTIMindtree\Projects\東森\sensengo\SampleData\會員卡推銷名單與通話文本_成功失敗各500人_去敏\persona_random_pick.1K.csv"
SERVER = "ehs-sales-sqlserver.database.windows.net"
DATABASE = "salesagent"
USERNAME = "sqladmin"
PASSWORD = "EhsSales2026!Secure#"
TABLE = "customer_persona_raw"
COMMIT_EVERY = 100


def normalize_col(col: str) -> str:
    return str(col).replace("\r", " ").replace("\n", " ").strip()


def main() -> None:
    conn = pyodbc.connect(
        "DRIVER={SQL Server};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"UID={USERNAME};"
        f"PWD={PASSWORD};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    cur = conn.cursor()

    with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        columns = [normalize_col(c) for c in reader.fieldnames or []]

        col_defs = ",\n    ".join(f"[{c}] NVARCHAR(4000) NULL" for c in columns)
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

        cols_sql = ", ".join(f"[{c}]" for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        insert_sql = f"INSERT INTO [{TABLE}] ({cols_sql}) VALUES ({placeholders})"

        count = 0
        for raw in reader:
            values = [str(raw.get(c, "")) for c in reader.fieldnames or []]
            cur.execute(insert_sql, values)
            count += 1
            if count % COMMIT_EVERY == 0:
                conn.commit()
                print(f"Inserted rows: {count}")

        conn.commit()
        print(f"Imported rows: {count}")

    result = cur.execute(f"SELECT COUNT(1) FROM [{TABLE}]").fetchone()[0]
    print(f"Verified rows in SQL: {result}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
