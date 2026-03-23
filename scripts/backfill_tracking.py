"""補上 persona_updated_at / persona_update_source 的正確時間及來源。"""
import pyodbc

conn = pyodbc.connect(
    "DRIVER={SQL Server};SERVER=ehs-sales-sqlserver.database.windows.net;"
    "DATABASE=salesagent;UID=sqladmin;PWD=EhsSales2026!Secure#;"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)
cur = conn.cursor()

# 檢查現況
cur.execute("SELECT COUNT(*) FROM customer_persona_raw WHERE persona_updated_at IS NOT NULL")
print("已有 persona_updated_at:", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM customer_persona_raw WHERE persona IS NOT NULL AND persona <> ''")
has_persona = cur.fetchone()[0]
print("有 persona 文字:", has_persona)

cur.execute("SELECT COUNT(*) FROM customer_persona_raw WHERE row_id <= 817 AND persona IS NOT NULL AND persona <> ''")
print("新 Excel 有 persona:", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM customer_persona_raw WHERE row_id > 817 AND persona IS NOT NULL AND persona <> ''")
print("舊 CSV 有 persona:", cur.fetchone()[0])

# 新 Excel (row_id 1-817): 來自 Blob 20260209，匯入時間 2026-03-18
cur.execute("""
    UPDATE customer_persona_raw
    SET persona_updated_at = '2026-03-18T00:00:00+08:00',
        persona_update_source = 'blob_import:20260209/500_customer_persona_sanitized.xlsx'
    WHERE row_id <= 817
      AND persona IS NOT NULL AND persona <> ''
      AND persona_updated_at IS NULL
""")
n1 = cur.rowcount
conn.commit()
print(f"更新新 Excel persona tracking: {n1} 筆")

# 舊 CSV (row_id > 817): 來自 persona_random_pick.1K.csv，追加時間 2026-03-18
cur.execute("""
    UPDATE customer_persona_raw
    SET persona_updated_at = '2026-03-18T00:00:00+08:00',
        persona_update_source = 'csv_import:persona_random_pick.1K.csv'
    WHERE row_id > 817
      AND persona IS NOT NULL AND persona <> ''
      AND persona_updated_at IS NULL
""")
n2 = cur.rowcount
conn.commit()
print(f"更新舊 CSV persona tracking: {n2} 筆")

# 驗證
cur.execute("SELECT persona_update_source, COUNT(*) FROM customer_persona_raw WHERE persona_updated_at IS NOT NULL GROUP BY persona_update_source")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]} 筆")

cur.close()
conn.close()
print("完成！")
