"""
將舊 CSV persona_random_pick.1K.csv 的資料追加回 Azure SQL，
只追加 customerid 不重複的筆數。
"""

import pandas as pd
import pyodbc

CSV_PATH = r"SampleData\會員卡推銷名單與通話文本_成功失敗各500人_去敏\persona_random_pick.1K.csv"
SERVER = "ehs-sales-sqlserver.database.windows.net"
DATABASE = "salesagent"
USERNAME = "sqladmin"
PASSWORD = "EhsSales2026!Secure#"
TABLE = "customer_persona_raw"


def main():
    # 讀舊 CSV
    df = pd.read_csv(CSV_PATH)
    df.columns = [str(c).replace("\r", " ").replace("\n", " ").strip() for c in df.columns]
    df = df.fillna("")

    # unikey3 -> customerid，移除新表格沒有的欄位
    df = df.rename(columns={"unikey3": "customerid"})
    df = df.drop(columns=["rr", "會員年資_天數"], errors="ignore")
    df["customerid"] = df["customerid"].astype(str)

    print(f"舊 CSV: {len(df)} 筆, 欄位: {len(df.columns)}")

    # 連線 SQL
    conn = pyodbc.connect(
        "DRIVER={SQL Server};"
        f"SERVER={SERVER};DATABASE={DATABASE};UID={USERNAME};PWD={PASSWORD};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    cur = conn.cursor()

    # 取得目前已存在的 customerid
    cur.execute(f"SELECT customerid FROM [{TABLE}]")
    existing_ids = {str(r[0]) for r in cur.fetchall()}
    print(f"目前 SQL 已有 {len(existing_ids)} 筆 customerid")

    # 過濾已存在的
    df_new = df[~df["customerid"].isin(existing_ids)]
    print(f"需追加 {len(df_new)} 筆 (排除重複)")

    if len(df_new) == 0:
        print("沒有需要追加的資料")
        cur.close()
        conn.close()
        return

    # 取得目前 SQL 表格的欄位（排除 row_id）
    cur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME='customer_persona_raw' AND COLUMN_NAME != 'row_id' "
        "ORDER BY ORDINAL_POSITION"
    )
    sql_cols = [r[0] for r in cur.fetchall()]

    cols_sql = ", ".join(f"[{c}]" for c in sql_cols)
    placeholders = ", ".join("?" for _ in sql_cols)
    insert_sql = f"INSERT INTO [{TABLE}] ({cols_sql}) VALUES ({placeholders})"

    csv_cols_set = set(df_new.columns)
    count = 0
    for _, row in df_new.iterrows():
        values = []
        for c in sql_cols:
            if c in csv_cols_set:
                values.append(str(row[c]))
            else:
                values.append("")
        cur.execute(insert_sql, values)
        count += 1
        if count % 200 == 0:
            conn.commit()
            print(f"  已追加: {count}/{len(df_new)}")
    conn.commit()
    print(f"  已追加: {count}/{len(df_new)}")

    # 驗證
    cur.execute(f"SELECT COUNT(1) FROM [{TABLE}]")
    total = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(DISTINCT customerid) FROM [{TABLE}]")
    distinct = cur.fetchone()[0]
    print(f"完成！SQL 總筆數: {total}, 不重複 customerid: {distinct}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
