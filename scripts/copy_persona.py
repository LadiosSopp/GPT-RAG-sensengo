"""Copy persona text from call log 10303606 (CSV) to SQL persona for customer 24702892."""
import csv
import pyodbc
import sys

CSV_PATH = "SampleData/會員卡推銷名單與通話文本_成功失敗各500人_去敏/persona_對應通話文本.csv"
SOURCE_ID = "10303606"
TARGET_ID = "24702892"

# ── Step 1: Read persona text from CSV ─────────────────────────────
persona_text = None
with open(CSV_PATH, "r", encoding="utf-8") as f:
    reader = csv.reader(f)
    headers = next(reader)
    for row in reader:
        if row[0] == SOURCE_ID:
            persona_text = row[1]  # re_summary_text
            break

if not persona_text:
    print(f"ERROR: {SOURCE_ID} not found in CSV")
    sys.exit(1)

print(f"Source persona from {SOURCE_ID} ({len(persona_text)} chars):")
print(persona_text[:200] + "...")

# ── Step 2: Update SQL persona for target customer ─────────────────
conn = pyodbc.connect(
    "DRIVER={SQL Server};"
    "SERVER=ehs-sales-sqlserver.database.windows.net;"
    "DATABASE=salesagent;"
    "UID=sqladmin;"
    "PWD=EhsSales2026!Secure#;"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)
cur = conn.cursor()

# Check target exists
cur.execute("SELECT persona FROM customer_persona_raw WHERE unikey3 = ?", TARGET_ID)
row = cur.fetchone()
if not row:
    print(f"ERROR: Target customer {TARGET_ID} not found in SQL")
    conn.close()
    sys.exit(1)

old_persona = row[0] or ""
print(f"\nTarget {TARGET_ID} old persona ({len(old_persona)} chars):")
print(old_persona[:200] + "..." if len(old_persona) > 200 else old_persona)

# Update
cur.execute(
    "UPDATE customer_persona_raw SET persona = ? WHERE unikey3 = ?",
    persona_text, TARGET_ID,
)
conn.commit()

# Verify
cur.execute("SELECT persona FROM customer_persona_raw WHERE unikey3 = ?", TARGET_ID)
new_row = cur.fetchone()
new_persona = new_row[0] or ""
print(f"\n✅ Updated! New persona ({len(new_persona)} chars):")
print(new_persona[:300] + "...")

conn.close()
print("\nDone.")

