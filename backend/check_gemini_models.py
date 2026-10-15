
import os
import httpx
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

response = httpx.get(
    "https://generativelanguage.googleapis.com/v1beta/models",
    headers={"x-goog-api-key": api_key},
    timeout=30,
)
response.raise_for_status()

for model in response.json().get("models", []):
    if "generateContent" in model.get(
        "supportedGenerationMethods", []
    ):
        print(model["name"])
