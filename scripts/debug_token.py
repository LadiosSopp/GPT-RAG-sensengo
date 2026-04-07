"""Debug: check token tenant."""
from azure.identity import AzureCliCredential
import json, base64

credential = AzureCliCredential(tenant_id="45f5172d-7608-4bd1-a52a-c3a7de0423d3")
token = credential.get_token("https://cognitiveservices.azure.com/.default")
parts = token.token.split(".")
# Add padding
payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
payload = json.loads(base64.b64decode(payload_b64))
print(f"tid: {payload.get('tid')}")
print(f"aud: {payload.get('aud')}")
print(f"upn: {payload.get('upn', 'N/A')}")
