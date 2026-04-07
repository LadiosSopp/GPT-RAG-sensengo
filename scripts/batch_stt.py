"""Batch STT: transcribe all WAV files in audio.sanitized/ using Azure AI Speech Fast Transcription API."""
import io
import json
import sys
import time
from pathlib import Path

import requests
from azure.identity import AzureCliCredential

# === Config ===
ENDPOINT = "https://aif-2v3lfktkn4xam-gprag.cognitiveservices.azure.com"
TENANT_ID = "45f5172d-7608-4bd1-a52a-c3a7de0423d3"
API_VERSION = "2024-11-15"

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIO_DIR = BASE_DIR / "SampleData" / "audio.sanitized"
OUTPUT_DIR = BASE_DIR / "SampleData" / "transcripts"


def get_token() -> str:
    credential = AzureCliCredential(tenant_id=TENANT_ID)
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    return token.token


def transcribe(audio_path: Path, token: str) -> dict | None:
    """Call Fast Transcription API and return the JSON result."""
    url = f"{ENDPOINT}/speechtotext/transcriptions:transcribe?api-version={API_VERSION}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    with open(audio_path, "rb") as f:
        audio_data = f.read()

    files = {
        "audio": (audio_path.name, io.BytesIO(audio_data), "audio/wav"),
        "definition": (
            None,
            json.dumps({"locales": ["zh-TW"], "profanityFilterMode": "None"}),
            "application/json",
        ),
    }
    resp = requests.post(url, headers=headers, files=files, timeout=300)
    if resp.status_code == 200:
        return resp.json()
    else:
        print(f"  ERROR {resp.status_code}: {resp.text[:200]}")
        return None


def save_transcript(result: dict, output_path: Path):
    """Save transcript as JSON (full) + TXT (text only with timestamps)."""
    # Save full JSON — use str concat to preserve double-dotted stems like "xxx.agent"
    json_path = output_path.parent / f"{output_path.name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Save readable TXT with timestamps
    txt_path = output_path.parent / f"{output_path.name}.txt"
    lines = []
    for phrase in result.get("combinedPhrases", []):
        lines.append(phrase.get("text", ""))
        lines.append("")
        lines.append("--- 逐句時間戳 ---")
        lines.append("")

    for phrase in result.get("phrases", []):
        offset_s = phrase.get("offsetMilliseconds", 0) / 1000
        duration_s = phrase.get("durationMilliseconds", 0) / 1000
        text = phrase.get("text", "")
        lines.append(f"[{offset_s:.1f}s - {offset_s + duration_s:.1f}s] {text}")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    wav_files = sorted(AUDIO_DIR.glob("*.wav"))
    # Skip files already transcribed (match by removing only .json/.txt suffix)
    existing = {p.name.removesuffix(".json") for p in OUTPUT_DIR.glob("*.json")}
    todo = [f for f in wav_files if f.stem not in existing]

    print(f"Audio dir:  {AUDIO_DIR}")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Total WAV files: {len(wav_files)}")
    print(f"Already done:    {len(existing)}")
    print(f"To process:      {len(todo)}")
    print()

    if not todo:
        print("All files already transcribed. Done.")
        return

    token = get_token()
    print(f"Token obtained.\n")

    success = 0
    fail = 0
    for i, wav in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {wav.name} ({wav.stat().st_size / 1024 / 1024:.1f} MB)...", end=" ", flush=True)
        t0 = time.time()
        result = transcribe(wav, token)
        elapsed = time.time() - t0

        if result:
            output_path = OUTPUT_DIR / wav.stem
            save_transcript(result, output_path)
            n_phrases = len(result.get("phrases", []))
            combined = result.get("combinedPhrases", [])
            text_len = len(combined[0].get("text", "")) if combined else 0
            print(f"OK ({elapsed:.1f}s, {n_phrases} phrases, {text_len} chars)")
            success += 1
        else:
            fail += 1

        # Token refresh every 50 files (tokens expire in ~60 min)
        if i % 50 == 0:
            print("  Refreshing token...")
            token = get_token()

    print(f"\nDone. Success: {success}, Failed: {fail}")
    print(f"Transcripts saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
