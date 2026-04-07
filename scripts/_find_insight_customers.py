import json
from azure.identity import AzureCliCredential
from azure.cosmos import CosmosClient

def main():
    cred = AzureCliCredential(tenant_id="45f5172d-7608-4bd1-a52a-c3a7de0423d3")
    uri = "https://cosmos-2v3lfktkn4xam-gprag.documents.azure.com:443/"
    db_name = "cosmos-db2v3lfktkn4xam-gprag"
    
    # All insight call_ids (both success and failure)
    insight_ids = [
        "010a03a3caa92c7f","010a03a3caa933c5","010a03a3caa93975",
        "010a03a3caa95d80","010a03a3caa9b2b5","010a03a3caa9ba47",
        "010a03a3caa92949","010a03a3caa933da","010a03a3caa9356f",
    ]
    
    client = CosmosClient(uri, credential=cred)
    db = client.get_database_client(db_name)
    container = db.get_container_client("call-transcripts")
    
    for cid in insight_ids:
        q = "SELECT c.customer_id, c.call_id, c.status FROM c WHERE c.call_id = @cid"
        params = [{"name": "@cid", "value": cid}]
        items = list(container.query_items(q, parameters=params, enable_cross_partition_query=True))
        for item in items:
            print(f"call_id={cid} -> customer_id={item['customer_id']} status={item.get('status','?')}")

main()
