"""Fetch Persona + Call Log and merge them with LLM to produce enriched profile."""
import os
import subprocess
import time
import json
import pyodbc
from azure.cosmos import CosmosClient
from azure.core.credentials import AccessToken


class StaticCred:
    def __init__(self, token):
        self.token = token

    def get_token(self, *a, **k):
        return AccessToken(self.token, int(time.time()) + 3600)


PERSONA_ID = "25045965"        # unikey3 in SQL persona table
CALL_LOG_CUSTOMER_ID = "26568707"  # customer_id in Cosmos call-transcripts
# NOTE: These are different customers in the sample data (0 overlap between sets).
# Using cross-customer merge for workflow validation only.

# ── 1. Fetch Persona from SQL ──
print("=" * 60)
print(f"1. Fetching Persona for unikey3={PERSONA_ID}")
print("=" * 60)

conn = pyodbc.connect(
    "DRIVER={SQL Server};"
    "SERVER=ehs-sales-sqlserver.database.windows.net;"
    "DATABASE=salesagent;"
    "UID=sqladmin;"
    "PWD=EhsSales2026!Secure#;"
    "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
)
cur = conn.cursor()
cur.execute("SELECT * FROM customer_persona_raw WHERE unikey3 = ?", PERSONA_ID)
cols = [d[0] for d in cur.description]
row = cur.fetchone()
persona_dict = {}
if row:
    persona_dict = {c: v for c, v in zip(cols, row) if v and str(v).strip()}
    print(f"  Found: {len(persona_dict)} non-empty fields")
else:
    print("  NOT FOUND")
conn.close()

# ── 2. Fetch Call Log from Cosmos ──
print(f"\n{'=' * 60}")
print(f"2. Fetching Call Log for customer_id={CALL_LOG_CUSTOMER_ID}")
print("=" * 60)

res = subprocess.run(
    "az account get-access-token --resource https://cosmos.azure.com/ --query accessToken -o tsv",
    shell=True, capture_output=True, text=True,
)
tok = res.stdout.strip()
client = CosmosClient(
    "https://cosmos-2v3lfktkn4xam-gprag.documents.azure.com:443/",
    credential=StaticCred(tok),
)
container = (
    client.get_database_client("cosmos-db2v3lfktkn4xam-gprag")
    .get_container_client("call-transcripts")
)

items = list(container.query_items(
    f"SELECT * FROM c WHERE c.customer_id = '{CALL_LOG_CUSTOMER_ID}'",
    enable_cross_partition_query=True,
))

call_log = None
if items:
    call_log = items[0]
    print(f"  Customer: {call_log.get('customer_id')}")
    print(f"  Date: {call_log.get('call_date')}")
    print(f"  Status: {call_log.get('status')}")
    transcript = call_log.get("transcript", "")
    print(f"  Transcript length: {len(transcript)} chars")
    print(f"  Preview: {transcript[:300]}...")
else:
    print("  NOT FOUND")

# ── 3. Build LLM prompt and call Azure OpenAI ──
if persona_dict and call_log:
    print(f"\n{'=' * 60}")
    print("3. Generating enriched profile with LLM")
    print("=" * 60)

    # Build persona summary (exclude row_id and rr)
    persona_lines = []
    for k, v in persona_dict.items():
        if k in ("row_id", "rr"):
            continue
        persona_lines.append(f"- {k}: {v}")
    persona_text = "\n".join(persona_lines)

    transcript_text = call_log.get("transcript", "")
    call_status = call_log.get("status", "")
    call_date = call_log.get("call_date", "")

    system_prompt = """你是東森購物的客戶分析師。

## 任務
根據客戶的 Persona 結構化標籤和通話逐字稿，生成一份精煉的客戶人物側寫。
這份側寫將用於銷售人員在下次通話前快速了解客戶，並據此制定銷售策略。

## 輸出格式（JSON）
{
  "profile_summary": "一句話描述此客戶（年齡/消費力/核心特徵）",
  "key_demographics": "性別/年齡/地區/會員等級/會員年資",
  "consumption_power": "消費力描述（金額區間、偏好通路、品類）",
  "pain_points": ["健康痛點1", "健康痛點2"],
  "taboos": ["禁忌1: 原因", "禁忌2: 原因"],
  "product_preferences": ["偏好品類1", "偏好品類2"],
  "communication_style": "此客戶的溝通風格與應對建議",
  "price_sensitivity": "價格敏感度描述",
  "objection_history": ["歷史拒絕原因1", "歷史拒絕原因2"],
  "success_factors": ["成交促進因子1", "成交促進因子2"],
  "family_context": "家庭背景（影響購買決策的因素）",
  "last_call_summary": "最近一次通話摘要（日期/結果/關鍵事件）",
  "recommended_approach": "下次通話建議策略",
  "call_count": 1,
  "last_updated": "日期"
}

## 原則
- 只記錄有銷售價值的資訊，忽略閒聊/客套/口語贅詞
- pain_points 和 taboos 是最關鍵的安全欄位，務必完整
- recommended_approach 要具體到可執行的行動建議
- 用繁體中文"""

    user_prompt = f"""## 客戶 Persona 結構化標籤
{persona_text}

## 通話紀錄
- 通話日期：{call_date}
- 推銷結果：{call_status}
- 逐字稿：
{transcript_text}

請根據以上資訊生成客戶人物側寫。"""

    # Call Azure OpenAI
    from openai import AzureOpenAI

    # Get OpenAI endpoint from app config or use known endpoint
    aoai_res = subprocess.run(
        "az cognitiveservices account list -g GPRAG --query \"[?kind=='OpenAI'].{name:name, endpoint:properties.endpoint}\" -o json",
        shell=True, capture_output=True, text=True,
    )
    aoai_accounts = json.loads(aoai_res.stdout)
    if aoai_accounts:
        endpoint = aoai_accounts[0]["endpoint"]
        aoai_name = aoai_accounts[0]["name"]
        print(f"  Using OpenAI: {aoai_name}")
        print(f"  Endpoint: {endpoint}")
    else:
        print("  No Azure OpenAI found in GPRAG, checking other RGs...")
        aoai_res = subprocess.run(
            "az cognitiveservices account list --query \"[?kind=='OpenAI'].{name:name, endpoint:properties.endpoint, rg:resourceGroup}\" -o json",
            shell=True, capture_output=True, text=True,
        )
        aoai_accounts = json.loads(aoai_res.stdout)
        endpoint = aoai_accounts[0]["endpoint"]
        aoai_name = aoai_accounts[0]["name"]
        print(f"  Using OpenAI: {aoai_name} (RG: {aoai_accounts[0]['rg']})")
        print(f"  Endpoint: {endpoint}")

    # Use API key if available, else fall back to AAD token
    aoai_api_key = os.environ.get("AOAI_KEY")
    if aoai_api_key:
        oai_client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_version="2024-12-01-preview",
            api_key=aoai_api_key,
        )
        print("  Auth: API Key")
    else:
        token_res = subprocess.run(
            "az account get-access-token --resource https://cognitiveservices.azure.com/ --query accessToken -o tsv",
            shell=True, capture_output=True, text=True,
        )
        aoai_token = token_res.stdout.strip()
        oai_client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_version="2024-12-01-preview",
            azure_ad_token=aoai_token,
        )
        print("  Auth: AAD Token")

    # List deployments to find a GPT-4 model
    deploy_res = subprocess.run(
        f'az cognitiveservices account deployment list -n {aoai_name} -g GPRAG --query "[].{{name:name, model:properties.model.name}}" -o json',
        shell=True, capture_output=True, text=True,
    )
    if deploy_res.returncode != 0:
        # Try without RG filter
        deploy_res = subprocess.run(
            f'az cognitiveservices account deployment list -n {aoai_name} -g {aoai_accounts[0].get("rg","GPRAG")} --query "[].{{name:name, model:properties.model.name}}" -o json',
            shell=True, capture_output=True, text=True,
        )
    deployments = json.loads(deploy_res.stdout)
    print(f"  Available deployments: {json.dumps(deployments, ensure_ascii=False)}")

    # Pick a GPT-4 deployment
    deploy_name = None
    for d in deployments:
        if "gpt-4" in d.get("model", "").lower() or "gpt-4" in d.get("name", "").lower():
            deploy_name = d["name"]
            break
    if not deploy_name and deployments:
        deploy_name = deployments[0]["name"]
    print(f"  Using deployment: {deploy_name}")

    response = oai_client.chat.completions.create(
        model=deploy_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )

    result = response.choices[0].message.content
    print(f"\n{'=' * 60}")
    print("4. ENRICHED PROFILE RESULT")
    print("=" * 60)
    
    parsed = json.loads(result)
    print(json.dumps(parsed, ensure_ascii=False, indent=2))

    # Save to file for review
    output_path = f"scripts/enriched_profile_{PERSONA_ID}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to: {output_path}")
