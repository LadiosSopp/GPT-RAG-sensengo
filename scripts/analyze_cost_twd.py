"""Re-analyze GPRAG cost with correct currency (TWD)."""
import json

data = json.loads(open("scripts/cost_result.json", "r", encoding="utf-8").read())
rows = data["properties"]["rows"]

TWD_TO_USD = 1 / 32.5  # approx rate

daily = {}
cats = {}
stt_rows = []
all_rows = []

for row in rows:
    cost_twd = row[0]
    date_raw = str(row[1])
    cat, sub, meter = row[2], row[3], row[4]
    if cost_twd == 0:
        continue
    d = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
    daily[d] = daily.get(d, 0) + cost_twd
    cats[cat] = cats.get(cat, 0) + cost_twd
    combined = f"{cat} {sub} {meter}".lower()
    if any(kw in combined for kw in ["speech", "cognitive", "ai service", "azure ai"]):
        stt_rows.append({"date": d, "twd": cost_twd, "cat": cat, "sub": sub, "meter": meter})
    all_rows.append({"date": d, "twd": cost_twd, "cat": cat, "sub": sub, "meter": meter})

total_twd = sum(daily.values())
total_usd = total_twd * TWD_TO_USD

print("=" * 65)
print("GPRAG 每日成本 — 幣別: TWD (新台幣)")
print("=" * 65)
for d in sorted(daily):
    usd = daily[d] * TWD_TO_USD
    print(f"  {d}: NT${daily[d]:>10,.1f}  (~ US${usd:>8,.2f})")
print(f"  {'7日合計':>10}: NT${total_twd:>10,.1f}  (~ US${total_usd:>8,.2f})")

print()
print("=" * 65)
print("按服務分類 (7日合計)")
print("=" * 65)
for cat, cost in sorted(cats.items(), key=lambda x: -x[1]):
    pct = cost / total_twd * 100
    usd = cost * TWD_TO_USD
    print(f"  {cat:35s} NT${cost:>10,.1f} (~US${usd:>7,.2f}) {pct:5.1f}%")

print()
print("=" * 65)
print("STT / Speech / AI Search 成本明細")
print("=" * 65)
stt_total = 0
by_date = {}
for r in stt_rows:
    by_date.setdefault(r["date"], [])
    by_date[r["date"]].append(r)
    stt_total += r["twd"]

for d in sorted(by_date):
    day_sum = sum(r["twd"] for r in by_date[d])
    print(f"\n  [{d}] NT${day_sum:,.1f} (~US${day_sum * TWD_TO_USD:,.2f})")
    for r in sorted(by_date[d], key=lambda x: -x["twd"]):
        usd = r["twd"] * TWD_TO_USD
        print(f"    {r['sub']:25s} / {r['meter']}")
        print(f"      NT${r['twd']:,.2f} (~US${usd:,.2f})")

print(f"\n  STT/AI相關總成本: NT${stt_total:,.1f} (~US${stt_total * TWD_TO_USD:,.2f})")
print(f"  佔 GPRAG 7日總成本: {stt_total / total_twd * 100:.1f}%")

print()
print("=" * 65)
print("3/23 STT 批次執行日分析")
print("=" * 65)
d23 = daily.get("2026-03-23", 0)
d22 = daily.get("2026-03-22", 0)
diff = d23 - d22
print(f"  3/22: NT${d22:>10,.1f} (~US${d22 * TWD_TO_USD:>8,.2f})")
print(f"  3/23: NT${d23:>10,.1f} (~US${d23 * TWD_TO_USD:>8,.2f})")
print(f"  差額: NT${diff:>+10,.1f} (~US${diff * TWD_TO_USD:>+8,.2f}) ({diff / d22 * 100:+.1f}%)")

# Speech STT only on 3/23
stt_323 = [r for r in stt_rows if r["date"] == "2026-03-23" and "speech" in f"{r['sub']} {r['meter']}".lower()]
stt_323_total = sum(r["twd"] for r in stt_323)
print(f"\n  3/23 Speech Fast Transcription:")
print(f"    NT${stt_323_total:,.1f} (~US${stt_323_total * TWD_TO_USD:,.2f})")

# Top costs on 3/23
print(f"\n  3/23 前 10 大費用項目:")
day23_rows = [r for r in all_rows if r["date"] == "2026-03-23"]
day23_rows.sort(key=lambda x: -x["twd"])
for r in day23_rows[:10]:
    usd = r["twd"] * TWD_TO_USD
    pct = r["twd"] / d23 * 100
    print(f"    NT${r['twd']:>8,.1f} (~US${usd:>6,.2f}) {pct:5.1f}% | {r['cat']} / {r['sub']} / {r['meter']}")
