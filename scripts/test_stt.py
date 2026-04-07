"""Quick test: Azure AI Speech STT with zh-TW on sample WAV file."""
import azure.cognitiveservices.speech as speechsdk
from azure.identity import AzureCliCredential

ENDPOINT = "https://aif-2v3lfktkn4xam-gprag.cognitiveservices.azure.com"
RESOURCE_ID = "/subscriptions/2c9b3248-f263-4104-bd24-6446d4db84b9/resourceGroups/GPRAG/providers/Microsoft.CognitiveServices/accounts/aif-2v3lfktkn4xam-gprag"
TENANT_ID = "45f5172d-7608-4bd1-a52a-c3a7de0423d3"
REGION = "eastus2"
AUDIO_FILE = r"c:\SynologyDrive\LTIMindtree\Projects\東森\sensengo\SampleData\audio.sanitized\010a03a3caa92949.agent.wav"

# Get AAD token with explicit tenant
credential = AzureCliCredential(tenant_id=TENANT_ID)
token = credential.get_token("https://cognitiveservices.azure.com/.default")
print(f"Token obtained, length: {len(token.token)}")

# Use endpoint config for custom domain AI Services
speech_config = speechsdk.SpeechConfig(host=ENDPOINT)
speech_config.speech_recognition_language = "zh-TW"
speech_config.output_format = speechsdk.OutputFormat.Detailed
# AAD auth with resource ID format: aad#resourceId#token
speech_config.authorization_token = f"aad#{RESOURCE_ID}#{token.token}"

# Use REST API directly instead of SDK websocket
import requests

print(f"\nRecognizing speech from: {AUDIO_FILE}")
print("Language: zh-TW\n")

# Read WAV file
with open(AUDIO_FILE, "rb") as f:
    audio_data = f.read()

print(f"Audio file size: {len(audio_data)} bytes")

# Try REST API approach
url = f"{ENDPOINT}/speechtotext/transcriptions:transcribe?api-version=2024-11-15"
headers = {
    "Authorization": f"Bearer {token.token}",
    "Accept": "application/json",
}

# Multipart form data
import io
files = {
    "audio": ("audio.wav", io.BytesIO(audio_data), "audio/wav"),
    "definition": (None, '{"locales": ["zh-TW"], "profanityFilterMode": "None"}', "application/json"),
}

response = requests.post(url, headers=headers, files=files)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    result = response.json()
    print("=== Recognized ===")
    for phrase in result.get("combinedPhrases", []):
        print(f"Text: {phrase.get('text', '')}")
    for phrase in result.get("phrases", []):
        print(f"  [{phrase.get('offsetMilliseconds',0)/1000:.1f}s - {(phrase.get('offsetMilliseconds',0)+phrase.get('durationMilliseconds',0))/1000:.1f}s] {phrase.get('text','')}")
else:
    print(f"Error: {response.text}")
