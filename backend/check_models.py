import os
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv()

api_key = (
    os.getenv("GENAILAB_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
    or os.getenv("API_KEY")
)
base_url = os.getenv("GENAILAB_BASE_URL", "https://genailab.tcs.in").rstrip("/")

print(f"Checking available models from {base_url} ...")
client = httpx.Client(verify=False)

try:
    response = client.get(
        f"{base_url}/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    models = response.json().get("data", [])
    print(f"\nFound {len(models)} models available for your key:")
    for m in models:
        print(f" - {m.get('id')}")

except Exception as exc:
    print(f"Error fetching models: {exc}")
