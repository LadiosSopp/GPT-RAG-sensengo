"""Analyze GPRAG cost data from Cost Management API result."""
import json
from pathlib import Path

result_path = Path("scripts/cost_result.json")
data = json.loads(result_path.read_text(encoding="utf-8"))

columns = [c["name"] for c in data["properties"]["columns"]]
rows = data["properties"]["rows"]

print(f"Columns: {columns}")
print(f"Rows: {len(rows)}\n")

# Parse rows: [PreTaxCost, UsageDate, MeterCategory, MeterSubcategory, Meter, Currency]
daily_costs = {}
category_costs = {}
stt_rows = []
all_rows_parsed = []

for row in rows:
    cost = row[0]
    date_raw = str(row[1])
    meter_cat = row[2]
    meter_sub = row[3]
    meter = row[4]
    currency = row[5] if len(row) > 5 else "USD"

    if cost == 0:
        continue

    date_str = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}" if len(date_raw) >= 8 else date_raw

    daily_costs.setdefault(date_str, 0)
    daily_costs[date_str] += cost

    category_costs.setdefault(meter_cat, 0)
    category_costs[meter_cat] += cost

    combined = f"{meter_cat} {meter_sub} {meter}".lower()
    if any(kw in combined for kw in ["speech", "cognitive", "ai service", "azure ai"]):
        stt_rows.append({
            "date": date_str, "cost": cost, "category": meter_cat,
            "subcategory": meter_sub, "meter": meter, "currency": currency,
        })

    all_rows_parsed.append({
        "date": date_str, "cost": cost, "category": meter_cat,
        "subcategory": meter_sub, "meter": meter,
    })

total = sum(daily_costs.values())

# === 1. Daily totals ===
print("=" * 70)
print("1. GPRAG 每日總成本 (USD)")
print("=" * 70)
for d in sorted(daily_costs):
    print(f"  {d}: ${daily_costs[d]:>10.4f}")
print(f"  {'7日合計':>10}: ${total:>10.4f}")

# === 2. By service category ===
print()
print("=" * 70)
print("2. 按服務分類成本 (7 日合計)")
print("=" * 70)
for cat, cost in sorted(category_costs.items(), key=lambda x: -x[1]):
    pct = cost / total * 100 if total > 0 else 0
    print(f"  {cat:40s} ${cost:>10.4f}  ({pct:5.1f}%)")

# === 3. STT / Speech / AI Services detail ===
print()
print("=" * 70)
print("3. Speech / AI Services 相關成本明細")
print("=" * 70)
if stt_rows:
    stt_by_date = {}
    stt_total = 0
    for r in stt_rows:
        stt_by_date.setdefault(r["date"], [])
        stt_by_date[r["date"]].append(r)
        stt_total += r["cost"]

    for d in sorted(stt_by_date):
        day_sum = sum(r["cost"] for r in stt_by_date[d])
        print(f"\n  [{d}] 小計: ${day_sum:.4f}")
        for r in sorted(stt_by_date[d], key=lambda x: -x["cost"]):
            print(f"    {r['subcategory']:30s} / {r['meter']}")
            print(f"      ${r['cost']:.6f}")

    print(f"\n  STT/AI 相關總成本: ${stt_total:.4f}")
    if total > 0:
        print(f"  佔 GPRAG 7日總成本: {stt_total/total*100:.1f}%")
else:
    print("  未找到 Speech/AI Services 相關計費項目。")

# === 4. 3/23 (STT 執行日) 成本 spike analysis ===
print()
print("=" * 70)
print("4. 3/23 成本分析（STT 批次執行日）")
print("=" * 70)
target_date = "2026-03-23"
day_rows = [r for r in all_rows_parsed if r["date"] == target_date and r["cost"] > 0]
if day_rows:
    day_rows.sort(key=lambda x: -x["cost"])
    day_total = sum(r["cost"] for r in day_rows)
    print(f"  {target_date} 總成本: ${day_total:.4f}")
    print()
    for r in day_rows[:15]:
        pct = r["cost"] / day_total * 100
        print(f"  ${r['cost']:>8.4f} ({pct:5.1f}%) | {r['category']} / {r['subcategory']} / {r['meter']}")
else:
    print(f"  {target_date} 無成本資料。")

# Compare with prev day
prev_date = "2026-03-22"
if prev_date in daily_costs and target_date in daily_costs:
    diff = daily_costs[target_date] - daily_costs[prev_date]
    pct_change = diff / daily_costs[prev_date] * 100 if daily_costs[prev_date] > 0 else 0
    print(f"\n  vs {prev_date}: ${daily_costs[prev_date]:.4f} → ${daily_costs[target_date]:.4f} (差: ${diff:+.4f}, {pct_change:+.1f}%)")
