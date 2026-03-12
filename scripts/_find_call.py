import subprocess, time, json
from azure.cosmos import CosmosClient
from azure.core.credentials import AccessToken

class C:
    def __init__(self, t):
        self.t = t
    def get_token(self, *a, **k):
        return AccessToken(self.t, int(time.time()) + 3600)

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

for q in ["26568707", "25045965"]:
    items = list(ct.query_items(
        f"SELECT c.id, c.call_id, c.customer_id, c.call_date, c.status FROM c WHERE c.customer_id = '{q}'",
        enable_cross_partition_query=True,
    ))
    print(f"customer_id={q}: {len(items)} docs")
    for i in items[:3]:
        print(f"  {json.dumps(i, ensure_ascii=False)}")

    items2 = list(ct.query_items(
        f"SELECT c.id, c.call_id, c.customer_id, c.call_date, c.status FROM c WHERE c.call_id = '{q}'",
        enable_cross_partition_query=True,
    ))
    print(f"call_id={q}: {len(items2)} docs")
    for i in items2[:3]:
        print(f"  {json.dumps(i, ensure_ascii=False)}")
