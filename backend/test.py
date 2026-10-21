import httpx
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv()

base_url = os.getenv("SNOW_INSTANCE_URL", "").rstrip("/")
username = os.getenv("SNOW_USERNAME")
password = os.getenv("SNOW_PASSWORD")

sys_id = "e7d7ac1847441710fd30497f316d431f"

response = httpx.patch(
    f"{base_url}/api/now/table/change_request/{sys_id}",
    auth=(username, password),
    headers={
        "Accept": "application/json",
        "Content-Type": "application/json",
    },
    json={
        "work_notes": "Testing REST API write access."
    },
    timeout=30,
    verify=False,
)

print("Status:", response.status_code)
print("Response:", response.text[:2000])
