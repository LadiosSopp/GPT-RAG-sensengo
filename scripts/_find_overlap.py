"""Find customers that have both Persona in SQL and Call Log in Cosmos."""
import subprocess, time, json
import pyodbc
from azure.cosmos import CosmosClient
from azure.core.credentials import AccessToken


class C:
    def __init__(self, t):
        self.t = t
    def get_token(self, *a, **k):
        return AccessToken(self.t, int(time.time()) + 3600)


# Get all customer_ids from Cosmos call-transcripts
res = subprocess.run(
    "az account get-access-token --resource https://cosmos.azure.com/ --query accessToken -o tsv",
    shell=True, capture_output=True, text=True,
)
client = CosmosClient(
    "https://cosmos-2v3lfktkn4xam-gprag.documents.azure.com:443/",
    credential=C(res.stdout.strip()),
)
ct = (
    client.get_database_client("cosmos-db2v3lfktkn4xam-gprag")
    .get_container_client("call-transcripts")
)

cosmos_ids = set()
items = list(ct.query_items(
    "SELECT DISTINCT VALUE c.customer_id FROM c",
    enable_cross_partition_query=True,
))
cosmos_ids = set(items)
print(f"Cosmos call-transcripts distinct customer_ids: {len(cosmos_ids)}")

# Get all unikey3 from SQL
conn = pyodbc.connect(
    "DRIVER={SQL Server};"
    "SERVER=ehs-sales-sqlserver.database.windows.net;"
    "DATABASE=salesagent;"
    "UID=sqladmin;"
    "PWD=EhsSales2026!Secure#;"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)
cur = conn.cursor()
cur.execute("SELECT unikey3 FROM customer_persona_raw")
sql_ids = set(str(r[0]) for r in cur.fetchall())
print(f"SQL persona distinct unikey3: {len(sql_ids)}")

# Find overlap
overlap = cosmos_ids & sql_ids
print(f"\nOverlapping customer IDs (both Persona + Call Log): {len(overlap)}")
if overlap:
    samples = list(overlap)[:10]
    print(f"Sample IDs: {samples}")

    # Show details for first match
    sample_id = samples[0]
    cur.execute("SELECT 性別, 年齡, OB等級, persona FROM customer_persona_raw WHERE unikey3 = ?", sample_id)
    row = cur.fetchone()
    print(f"\n--- Sample: {sample_id} ---")
    print(f"  Persona: 性別={row[0]}, 年齡={row[1]}, OB等級={row[2]}")
    print(f"  Persona text: {str(row[3])[:200]}...")

    call_items = list(ct.query_items(
        f"SELECT c.call_id, c.call_date, c.status FROM c WHERE c.customer_id = '{sample_id}'",
        enable_cross_partition_query=True,
    ))
    print(f"  Call logs: {len(call_items)}")
    for ci in call_items:
        print(f"    {ci['call_date']} | {ci['status']} | call_id={ci['call_id']}")

conn.close()
