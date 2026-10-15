
import json
import logging
import os
from datetime import datetime, timezone
import asyncio

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException
from database import (
    get_assessment,
    save_assessment,
    update_work_note_status,
)
from database import (
    get_assessment,
    save_assessment,
    update_work_note_status,
    set_exception_pending,
)

load_dotenv()
logger = logging.getLogger(__name__)

SNOW_INSTANCE_URL = os.getenv(
    "SNOW_INSTANCE_URL", ""
).rstrip("/")
SNOW_USERNAME = os.getenv("SNOW_USERNAME")
SNOW_PASSWORD = os.getenv("SNOW_PASSWORD")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

FREEZE_NOTE = "Change freeze applied until further notice."
HIGH_RISK_NOTE = (
    "Analyzed the risk of the change, requested for approval "
    "to continue the change as per the schedule."
)


async def fetch_changes(start: datetime, end: datetime):
    """Fetch ServiceNow changes overlapping a storm window."""

    if not all([SNOW_INSTANCE_URL, SNOW_USERNAME, SNOW_PASSWORD]):
        raise HTTPException(
            status_code=500,
            detail="ServiceNow configuration is incomplete.",
        )

    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise HTTPException(
            status_code=400,
            detail="A valid timezone-aware storm period is required.",
        )

    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)

    url = f"{SNOW_INSTANCE_URL}/api/now/table/change_request"
    params = {
        "sysparm_query": (
            f"start_date<={end.strftime('%Y-%m-%d %H:%M:%S')}"
            f"^end_date>={start.strftime('%Y-%m-%d %H:%M:%S')}"
            "^ORDERBYstart_date"
        ),
        "sysparm_fields": (
            "sys_id,number,short_description,description,type,state,"
            "approval,start_date,end_date,justification,"
            "implementation_plan,risk_impact_analysis,"
            "backout_plan,test_plan"
        ),
        "sysparm_display_value": "true",
        "sysparm_limit": "100",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await snow_request_with_retry(
                client,
                "GET",
                url,
                params=params,
                auth=(SNOW_USERNAME, SNOW_PASSWORD),
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json().get("result", [])

    except httpx.HTTPStatusError as exc:
        logger.error(
            "ServiceNow lookup failed: HTTP %s, body=%s",
            exc.response.status_code,
            exc.response.text[:1000],
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve ServiceNow changes.",
        ) from exc

    except httpx.RequestError as exc:
        logger.exception("ServiceNow request failed")
        raise HTTPException(
            status_code=502,
            detail="ServiceNow is temporarily unreachable.",
        ) from exc



async def analyze_change(change: dict):
    """Classify the business impact of postponing a change."""

    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is not configured.",
        )

    fields = [
        "number",
        "short_description",
        "description",
        "type",
        "start_date",
        "end_date",
        "justification",
        "implementation_plan",
        "risk_impact_analysis",
        "backout_plan",
        "test_plan",
    ]

    evidence = {key: change.get(key) for key in fields}

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
{json.dumps(evidence, ensure_ascii=False)}
"""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-3.5-flash:generateContent"
    )

    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await gemini_request_with_retry(
                client,
                url,
                params={"key": GEMINI_API_KEY},
                json={
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.1,
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()

        content = payload["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(content)

        if result.get("risk_classification") not in (
            "high", "low", "uncertain"
        ):
            raise ValueError("Invalid risk classification.")

        # Add a fallback if Gemini doesn't provide a summary.
        if not result.get("flag_summary"):
            result["flag_summary"] = (
                "The change requires manual review because "
                "the business impact needs clarification."
            )

        return result

    except Exception:
        logger.exception(
            "Risk analysis failed for change %s",
            change.get("number"),
        )
        return {
            "risk_classification": "uncertain",
            "flag_summary": (
                "Automated analysis failed; manual review is required."
            ),
            "business_impact_if_delayed": "Unknown",
            "reason": (
                "Automated analysis failed. Manual review is required."
            ),
            "missing_information": [],
        }


async def update_exception_decision_work_note(
    sys_id: str,
    decision: str,
):
    if decision not in ("approve", "reject"):
        raise ValueError("Invalid exception decision.")

    if not all([
        SNOW_INSTANCE_URL,
        SNOW_USERNAME,
        SNOW_PASSWORD,
    ]):
        raise HTTPException(
            status_code=500,
            detail="ServiceNow configuration is incomplete.",
        )

    if decision == "approve":
        note = (
            "Exception approved by Change Manager. "
            "Approved to proceed as per the scheduled "
            "implementation window."
        )
    else:
        note = (
            "Exception rejected by Change Manager. "
            "Not approved to proceed; keep the change "
            "frozen until further notice."
        )

    url = (
        f"{SNOW_INSTANCE_URL}/api/now/table/"
        f"change_request/{sys_id}"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        response = await snow_request_with_retry(
            client,
            "PATCH",
            url,
            auth=(SNOW_USERNAME, SNOW_PASSWORD),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={"work_notes": note},
        )
        response.raise_for_status()

    return {"status": "updated", "decision": decision}
    



async def update_change_work_notes(
    sys_id: str,
    classification: str,
):
    """Add the appropriate freeze work note in ServiceNow."""

    if classification not in {"high", "low", "uncertain"}:
        raise ValueError(
            f"Invalid risk classification: {classification}"
        )

    if not all([SNOW_INSTANCE_URL, SNOW_USERNAME, SNOW_PASSWORD]):
        raise RuntimeError("ServiceNow configuration is incomplete.")

    if classification == "high":
        work_note = f"{FREEZE_NOTE} {HIGH_RISK_NOTE}"
    else:
        work_note = FREEZE_NOTE

    url = (
        f"{SNOW_INSTANCE_URL}/api/now/table/"
        f"change_request/{sys_id}"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        response = await snow_request_with_retry(
            client,
            "PATCH",
            url,
            auth=(SNOW_USERNAME, SNOW_PASSWORD),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={"work_notes": work_note},
        )

    return {
        "sys_id": sys_id,
        "classification": classification,
        "work_note": work_note,
        "status": "updated",
    }

async def process_storm_changes(
    start: datetime,
    end: datetime,
    alert_id: str,
):
    """Reuse saved AI assessments and avoid duplicate work notes."""

    from database import get_assessment

    changes = await fetch_changes(start, end)

    high_risk_changes = []
    low_risk_changes = []
    review_required = []
    update_failures = []

    for change in changes:
        sys_id = change.get("sys_id")

        if not sys_id:
            logger.error(
                "Skipping change without sys_id: %s",
                change.get("number"),
            )
            update_failures.append({
                "number": change.get("number"),
                "status": "missing_sys_id",
            })
            continue

        # Reuse the saved assessment for this storm and change.
        cached = get_assessment(alert_id, sys_id)

        if cached:
            assessment = cached["assessment"]
            note_status = cached["work_note_status"]
        else:
            assessment = await analyze_change(change)


            # Persist the assessment before attempting ServiceNow
            # updates so a refresh won't rerun Gemini unnecessarily.
            save_assessment(alert_id, change, assessment)
            if assessment.get("risk_classification") == "high":
                set_exception_pending(alert_id, sys_id)
            
            note_status = "pending"

        classification = assessment.get(
            "risk_classification", "uncertain"
        )

        item = {
            **change,
            "risk_assessment": assessment,
            "work_note_status": note_status,
        }

        if classification == "high":
            high_risk_changes.append(item)
        elif classification == "low":
            low_risk_changes.append(item)
        else:
            review_required.append(item)

        # Already confirmed updated: never add the same notes again.
        if note_status == "updated":
            continue

        # An earlier request may have reached ServiceNow even if the
        # client did not receive its response. Don't blindly retry it.
        if note_status == "uncertain":
            item["work_note_status"] = "uncertain"
            if item not in review_required:
                review_required.append(item)
            continue

        try:
            result = await update_change_work_notes(
                sys_id,
                classification,
            )

            update_work_note_status(
                alert_id, sys_id, result["status"]
            )

            item["work_note_status"] = result["status"]

        except Exception:
            logger.exception(
                "Work-note update failed for %s",
                change.get("number"),
            )

            # A failure may be ambiguous: verify ServiceNow before
            # attempting another PATCH to avoid duplicate journal notes.
            update_work_note_status(
                alert_id, sys_id, "uncertain"
            )
            item["work_note_status"] = "uncertain"

            if item not in review_required:
                review_required.append(item)

            update_failures.append({
                "number": change.get("number"),
                "status": "uncertain",
            })

    return {
        "status": (
            "partial_failure" if update_failures else "completed"
        ),
        "total_changes": len(changes),
        "high_risk_count": len(high_risk_changes),
        "low_risk_count": len(low_risk_changes),
        "review_required_count": len(review_required),
        "high_risk_changes": high_risk_changes,
        "low_risk_changes": low_risk_changes,
        "review_required": review_required,
        "work_note_failures": update_failures,
    }

async def snow_request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 5,
    interval: int = 5,
    **kwargs,
):
    """Retry transient ServiceNow failures up to five attempts."""

    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.request(
                method,
                url,
                **kwargs,
            )

            # Retry temporary server errors and rate limits.
            if (
                response.status_code in (429, 500, 502, 503, 504)
                and attempt < max_attempts
            ):
                logger.warning(
                    "ServiceNow returned HTTP %s. "
                    "Retry %s/%s in %s seconds.",
                    response.status_code,
                    attempt,
                    max_attempts - 1,
                    interval,
                )
                await asyncio.sleep(interval)
                continue

            response.raise_for_status()
            return response

        except httpx.RequestError as exc:
            if attempt == max_attempts:
                logger.error(
                    "ServiceNow request failed after %s attempts: %s",
                    max_attempts,
                    type(exc).__name__,
                )
                raise

            logger.warning(
                "ServiceNow connection error. "
                "Retry %s/%s in %s seconds.",
                attempt,
                max_attempts - 1,
                interval,
            )
            await asyncio.sleep(interval)

    raise RuntimeError("ServiceNow retry loop ended unexpectedly.")



async def gemini_request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_attempts: int = 5,
    interval: int = 5,
    **kwargs,
):
    """Retry transient Gemini errors and network timeouts."""

    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.post(url, **kwargs)

            if (
                response.status_code
                in (429, 500, 502, 503, 504)
                and attempt < max_attempts
            ):
                logger.warning(
                    "Gemini returned HTTP %s; retry %s/%s in %s seconds.",
                    response.status_code,
                    attempt,
                    max_attempts - 1,
                    interval,
                )
                await asyncio.sleep(interval)
                continue

            response.raise_for_status()
            return response

        except httpx.RequestError as exc:
            if attempt == max_attempts:
                logger.error(
                    "Gemini request failed after %s attempts: %s",
                    max_attempts,
                    type(exc).__name__,
                )
                raise

            logger.warning(
                "Gemini connection/timeout error; retry %s/%s in %s seconds.",
                attempt,
                max_attempts - 1,
                interval,
            )
            await asyncio.sleep(interval)

    raise RuntimeError("Gemini retry loop ended unexpectedly.")
