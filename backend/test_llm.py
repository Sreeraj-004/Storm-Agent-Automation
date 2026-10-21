import os
import json
from pathlib import Path
import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv()

api_key = (
    os.getenv("GENAILAB_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
    or os.getenv("API_KEY")
)
base_url = os.getenv("GENAILAB_BASE_URL", "https://genailab.tcs.in")
model = os.getenv("GENAILAB_MODEL", "azure/genailab-maas-gpt-4o-mini")

print(f"Connecting to base_url: {base_url}")
print(f"Using model: {model}")
print(f"API key present: {bool(api_key)}")

client = httpx.Client(verify=False)
llm = ChatOpenAI(
    base_url=base_url,
    model=model,
    api_key=api_key,
    http_client=client,
    temperature=0.1,
)

# Test simple invocation
print("\n--- TEST SIMPLE INVOCATION ---")
simple_resp = llm.invoke("Hi")
print("Simple invoke response:", simple_resp.content)

sample_change = {
    "number": "CHG0030001",
    "short_description": "Emergency patch for core database",
    "description": "Applying security patch for zero-day vulnerability in payment gateway database",
    "type": "Emergency",
    "start_date": "2026-10-21 12:00:00",
    "end_date": "2026-10-21 14:00:00",
    "justification": "Critical security risk",
    "implementation_plan": "Apply patch, verify integrity",
    "risk_impact_analysis": "High impact if delayed due to potential exploit",
    "backout_plan": "Rollback snapshot",
    "test_plan": "Run regression suite"
}

prompt = f"""
You are assessing IT change requests during an unexpected change freeze.

All changes are frozen by default.

Determine the BUSINESS IMPACT OF POSTPONING implementation until
the freeze is lifted. Do not use the ServiceNow state or change type
as a substitute for risk analysis.

HIGH:
Postponement could cause significant business impact, such as an
ongoing critical service outage, an urgent security exposure, or
a serious risk to recovery of critical data. The supplied evidence
must support this conclusion.

LOW:
The change can reasonably be postponed without significant immediate
business impact.

UNCERTAIN:
The record lacks enough evidence to make a reliable decision.

Do not invent facts. A high-risk classification is a recommendation
for human approval, NOT permission to implement the change.

Return only JSON:
{{
  "risk_classification": "high" or "low" or "uncertain",
  "flag_summary": "One sentence explaining why this change needs review",
  "business_impact_if_delayed": "explanation",
  "reason": "evidence-based explanation",
  "missing_information": []
}}

Change record:
{json.dumps(sample_change, ensure_ascii=False)}
"""

response = llm.invoke(prompt)
print("\n--- LLM RAW RESPONSE ---")
print(response.content)

def extract_json(text: str) -> dict:
    text = text.strip()
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>")[-1].strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace : last_brace + 1]
    return json.loads(text)

parsed = extract_json(response.content)
print("\n--- PARSED JSON ---")
print(json.dumps(parsed, indent=2))
