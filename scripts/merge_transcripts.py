"""Merge agent + customer transcripts into a single conversation file, ordered by timestamp."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TRANSCRIPT_DIR = BASE_DIR / "SampleData" / "transcripts"
MERGED_DIR = BASE_DIR / "SampleData" / "transcripts_merged"


def get_call_ids() -> list[str]:
    """Extract unique call IDs from transcript files."""
    ids = set()
    for p in TRANSCRIPT_DIR.glob("*.agent.json"):
        call_id = p.name.removesuffix(".agent.json")
        ids.add(call_id)
    return sorted(ids)


def load_phrases(call_id: str, role: str) -> list[dict]:
    """Load phrases from a transcript JSON, tagging each with speaker role."""
    path = TRANSCRIPT_DIR / f"{call_id}.{role}.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    phrases = data.get("phrases", [])
    for p in phrases:
        p["speaker"] = role
    return phrases


def merge_and_save(call_id: str):
    """Merge agent + customer phrases by time, save as JSON + TXT."""
    agent_phrases = load_phrases(call_id, "agent")
    customer_phrases = load_phrases(call_id, "customer")

    # Merge and sort by offset
    all_phrases = agent_phrases + customer_phrases
    all_phrases.sort(key=lambda p: p["offsetMilliseconds"])

    # Save merged JSON
    json_path = MERGED_DIR / f"{call_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"callId": call_id, "phrases": all_phrases}, f, ensure_ascii=False, indent=2)

    # Save readable TXT
    txt_path = MERGED_DIR / f"{call_id}.txt"
    lines = []
    for p in all_phrases:
        offset_s = p["offsetMilliseconds"] / 1000
        end_s = offset_s + p["durationMilliseconds"] / 1000
        speaker = "客服" if p["speaker"] == "agent" else "客戶"
        lines.append(f"[{offset_s:.1f}s - {end_s:.1f}s] {speaker}：{p['text']}")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return len(all_phrases)


def main():
    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    call_ids = get_call_ids()
    print(f"Found {len(call_ids)} call IDs to merge.")
    print(f"Output: {MERGED_DIR}\n")

    for i, cid in enumerate(call_ids, 1):
        n = merge_and_save(cid)
        print(f"[{i}/{len(call_ids)}] {cid} — {n} phrases merged")

    print(f"\nDone. {len(call_ids)} conversations merged.")


if __name__ == "__main__":
    main()
