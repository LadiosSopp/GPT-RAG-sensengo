"""Query Azure Cost Management for GPRAG resource group - STT cost analysis."""
import json
import subprocess
from datetime import datetime, timedelta

SUBSCRIPTION_ID = "2c9b3248-f263-4104-bd24-6446d4db84b9"
RESOURCE_GROUP = "GPRAG"
SCOPE = f"subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"

# Query daily cost by MeterCategory for last 7 days
end_date = datetime(2026, 3, 24)
start_date = end_date - timedelta(days=7)

body = {
    "type": "ActualCost",
    "timeframe": "Custom",
    "timePeriod": {
        "from": start_date.strftime("%Y-%m-%dT00:00:00Z"),
        "to": end_date.strftime("%Y-%m-%dT23:59:59Z"),
    },
    "dataset": {
        "granularity": "Daily",
        "aggregation": {
            "totalCost": {"name": "PreTaxCost", "function": "Sum"},
        },
        "grouping": [
            {"type": "Dimension", "name": "MeterCategory"},
            {"type": "Dimension", "name": "MeterSubCategory"},
            {"type": "Dimension", "name": "MeterName"},
        ],
    },
}

# Use az rest to call Cost Management API
url = f"https://management.azure.com/{SCOPE}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
body_str = json.dumps(body).replace('"', '\\"')
cmd = f'az rest --method post --url "{url}" --body "{body_str}"'

print(f"Querying costs for {RESOURCE_GROUP} from {start_date.date()} to {end_date.date()}...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, shell=True)

if result.returncode != 0:
    print(f"Error: {result.stderr}")
    exit(1)

data = json.loads(result.stdout)
columns = [c["name"] for c in data["properties"]["columns"]]
rows = data["properties"]["rows"]

print(f"\nReturned {len(rows)} cost rows.\n")

# Parse and group
daily_costs = {}
meter_costs = {}
stt_rows = []

for row in rows:
    cost = row[0]
    date_val = str(row[1])  # YYYYMMDD format
    meter_cat = row[2]
    meter_sub = row[3]
    meter_name = row[4]
    currency = row[5]

    if cost == 0:
        continue

    # Format date
    date_str = f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:8]}" if len(date_val) >= 8 else date_val

    # Daily totals
    daily_costs.setdefault(date_str, 0)
    daily_costs[date_str] += cost

    # By meter category
    meter_costs.setdefault(meter_cat, 0)
    meter_costs[meter_cat] += cost

    # Filter STT / Speech / Cognitive related
    combined = f"{meter_cat} {meter_sub} {meter_name}".lower()
    if any(kw in combined for kw in ["speech", "cognitive", "ai services", "azure ai"]):
        stt_rows.append({
            "date": date_str,
            "cost": cost,
            "category": meter_cat,
            "subcategory": meter_sub,
            "meter": meter_name,
            "currency": currency,
        })

# === Print Results ===
print("=" * 70)
print("1. GPRAG 每日總成本")
print("=" * 70)
for d in sorted(daily_costs):
    print(f"  {d}: ${daily_costs[d]:.4f}")
total = sum(daily_costs.values())
print(f"  {'TOTAL':>10}: ${total:.4f}")

print()
print("=" * 70)
print("2. 按服務分類成本")
print("=" * 70)
for cat, cost in sorted(meter_costs.items(), key=lambda x: -x[1]):
    pct = cost / total * 100 if total > 0 else 0
    print(f"  {cat:40s} ${cost:>10.4f}  ({pct:5.1f}%)")

print()
print("=" * 70)
print("3. Speech/AI Services 相關成本明細（STT）")
print("=" * 70)
if stt_rows:
    # Group by date
    stt_by_date = {}
    stt_total = 0
    for r in stt_rows:
        stt_by_date.setdefault(r["date"], [])
        stt_by_date[r["date"]].append(r)
        stt_total += r["cost"]

    for d in sorted(stt_by_date):
        print(f"\n  [{d}]")
        for r in stt_by_date[d]:
            print(f"    {r['category']} / {r['subcategory']} / {r['meter']}")
            print(f"      ${r['cost']:.6f} {r['currency']}")

    print(f"\n  STT 相關總成本: ${stt_total:.4f}")
    if total > 0:
        print(f"  佔 GPRAG 總成本比例: {stt_total/total*100:.1f}%")
else:
    print("  未找到 Speech/AI Services 相關計費項目。")
    print("  (可能尚未出帳，Azure 通常有 24-48 小時的計費延遲)")
