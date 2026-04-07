"""Calculate total audio duration and STT cost."""
import json
from pathlib import Path

transcript_dir = Path(r"SampleData\transcripts")
total_duration_ms = 0
total_files = 0
per_file = []

for f in sorted(transcript_dir.glob("*.json")):
    with open(f, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    phrases = data.get("phrases", [])
    if phrases:
        last = phrases[-1]
        file_duration = last["offsetMilliseconds"] + last["durationMilliseconds"]
        total_duration_ms += file_duration
        total_files += 1
        per_file.append((f.name, file_duration / 1000))

total_seconds = total_duration_ms / 1000
total_minutes = total_seconds / 60
total_hours = total_minutes / 60

print(f"Files processed: {total_files}")
print(f"Total duration:  {total_hours:.2f} hours ({total_minutes:.1f} min)")
print()
print("=== Cost Estimate (Azure AI Speech - Fast Transcription) ===")
print("Pricing tier: Pay-as-you-go (Standard)")
print("Rate: $1.00 / audio hour")
print(f"Estimated cost: ${total_hours:.2f} USD")
print()

# Raw WAV sizes
audio_dir = Path(r"SampleData\audio.sanitized")
total_size = sum(f.stat().st_size for f in audio_dir.glob("*.wav"))
print(f"Total WAV size: {total_size / 1024 / 1024 / 1024:.2f} GB")

# Top 5 longest files
per_file.sort(key=lambda x: -x[1])
print("\nTop 5 longest files:")
for name, dur in per_file[:5]:
    print(f"  {name}: {dur/60:.1f} min")
