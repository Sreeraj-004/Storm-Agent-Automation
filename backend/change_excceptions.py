import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
import asyncio

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException
from langchain_openai import ChatOpenAI
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

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv()

# Configure basic logging format if not already configured
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

logger = logging.getLogger(__name__)

SNOW_INSTANCE_URL = os.getenv(
    "SNOW_INSTANCE_URL", ""
).rstrip("/")
SNOW_USERNAME = os.getenv("SNOW_USERNAME")
SNOW_PASSWORD = os.getenv("SNOW_PASSWORD")

# GenAILab / OpenAI LLM Configuration
GENAILAB_BASE_URL = os.getenv("GENAILAB_BASE_URL", "https://genailab.tcs.in")
GENAILAB_MODEL = os.getenv("GENAILAB_MODEL", "azure/genailab-maas-gpt-4o-mini")
GENAILAB_API_KEY = (
    os.getenv("GENAILAB_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
    or os.getenv("API_KEY")
)

SCHEDULED_STATE_VALUE = os.getenv("SNOW_SCHEDULED_STATE_VALUE", "-2")
CANCELED_STATE_VALUE = os.getenv("SNOW_CANCELLED_STATE_VALUE", "4")

FREEZE_NOTE = "Change freeze applied until further notice."
HIGH_RISK_NOTE = (
    "Analyzed the risk of the change, requested for approval "
    "to continue the change as per the schedule."
)


def extract_json(text: str) -> dict:
    """Extract and parse JSON object from LLM response text."""
    logger.debug("extract_json called with raw text (len=%d)", len(text))
    text = text.strip()
    if "<think>" in text and "</think>" in text:
        logger.debug("Stripping <think> reasoning tags from LLM response")
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

    try:
        parsed = json.loads(text)
        logger.debug("Successfully parsed JSON payload with keys: %s", list(parsed.keys()))
        return parsed
    except Exception as exc:
        logger.error(
            "Failed to parse JSON from LLM response: %s. Raw snippet: %r",
            exc,
            text[:200],
        )
        raise


async def fetch_changes(start: datetime, end: datetime):
    """Fetch ServiceNow changes overlapping a storm window."""
    logger.info(
        "fetch_changes called for storm window: start=%s, end=%s",
        start.isoformat() if hasattr(start, "isoformat") else start,
        end.isoformat() if hasattr(end, "isoformat") else end,
    )

    if not all([SNOW_INSTANCE_URL, SNOW_USERNAME, SNOW_PASSWORD]):
        logger.error(
            "ServiceNow configuration incomplete (URL=%s, USERNAME=%s, PASSWORD=%s)",
            bool(SNOW_INSTANCE_URL),
            bool(SNOW_USERNAME),
            bool(SNOW_PASSWORD),
        )
        raise HTTPException(
            status_code=500,
            detail="ServiceNow configuration is incomplete.",
        )

    if start.tzinfo is None or end.tzinfo is None or end <= start:
        logger.error("Invalid storm window provided: start=%s, end=%s", start, end)
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
            "backout_plan,test_plan,on_hold,on_hold_reason"
        ),
        "sysparm_display_value": "true",
        "sysparm_limit": "100",
    }

    logger.info(
        "Querying ServiceNow for overlapping change requests: %s (limit=%s)",
        params["sysparm_query"],
        params["sysparm_limit"],
    )

    try:
        async with httpx.AsyncClient(timeout=30, verify=False) as client:
            response = await snow_request_with_retry(
                client,
                "GET",
                url,
                params=params,
                auth=(SNOW_USERNAME, SNOW_PASSWORD),
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            changes = response.json().get("result", [])
            logger.info(
                "Successfully fetched %d change request(s) from ServiceNow.",
                len(changes),
            )
            return changes

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
        logger.exception("ServiceNow connection request failed during fetch_changes")
        raise HTTPException(
            status_code=502,
            detail="ServiceNow is temporarily unreachable.",
        ) from exc


async def analyze_change(change: dict):
    """Classify the business impact of postponing a change."""
    chg_number = change.get("number", "Unknown")
    chg_sys_id = change.get("sys_id", "Unknown")
    chg_type = change.get("type", "Unknown")
    short_desc = change.get("short_description", "No description")

    logger.info(
        "analyze_change started for change %s (%s) [type=%s]: '%s'",
        chg_number,
        chg_sys_id,
        chg_type,
        short_desc[:80],
    )

    api_key = (
        os.getenv("GENAILAB_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("API_KEY")
    )

    if not api_key:
        logger.error("LLM API key not found in environment for analyze_change.")
        raise HTTPException(
            status_code=500,
            detail="GENAILAB_API_KEY is not configured.",
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
You are an IT change assessment assistant operating during an
active Storm Mode change freeze.

OBJECTIVE
Assess the business impact of postponing the requested IT change
until the Storm Mode freeze is lifted. Determine whether the
documented evidence justifies requesting an exception.

All changes are frozen by default. Your assessment does not
authorize implementation or replace the required human approval.

RISK CLASSIFICATION

1. LOW
Classify as "low" when the change can reasonably be postponed
until the freeze ends without significant immediate business harm.

Examples:
- Routine operating system patching without an urgent vulnerability.
- Database index optimization or routine performance tuning.
- Planned application upgrades and feature deployments.
- Routine infrastructure maintenance.
- Capacity expansion when existing capacity remains adequate.
- Planned configuration changes without a time-critical dependency.

These are examples, not automatic classifications. Use the
evidence in the actual change record.

2. HIGH
Classify as "high" only when the supplied evidence supports a
significant and immediate business consequence if the change
is postponed.

Examples:
- An ongoing critical production outage requiring remediation.
- An actively exploited security vulnerability requiring urgent
  mitigation.
- An imminent risk of critical data loss or system failure.
- A documented, time-critical business obligation that cannot
  reasonably wait until the freeze ends.
- An urgent recovery action necessary to restore a critical service.

A high implementation risk does not automatically mean that
postponement has a high business impact. Assess the consequences
of delaying the change, not merely the danger of implementing it.

3. UNCERTAIN
Classify as "uncertain" when the available record does not contain
enough reliable evidence to determine the consequences of
postponement.

Examples:
- The description claims urgency but provides no supporting details.
- The business deadline or impact is not documented.
- The affected service or dependency is unclear.
- The proposed change lacks sufficient justification.
- The record contains conflicting information.

Do not classify a change as high merely because information is
missing. Use "uncertain" when the evidence is insufficient.

EXCEPTION APPROVAL DECISION

Set "requires_exception_approval" to true only when:
- risk_classification is "high";
- the documented evidence establishes a genuine need to proceed
  during the freeze; and
- postponement would create significant business, operational,
  security, or recovery consequences.

Set "requires_exception_approval" to false when:
- the change can reasonably wait until the freeze ends;
- the evidence does not establish a need to proceed during the
  freeze; or
- the assessment is uncertain and requires manual review.

A high classification means the change deserves review. It does
not automatically mean an exception should be requested.

An emergency change type alone does not prove that the change
must proceed during the freeze. Likewise, a normal change may
qualify for an exception if the documented evidence establishes
a genuine time-critical business need.

Do not grant approval or authorize implementation. The final
decision must follow the configured ServiceNow approval process
and organizational emergency-change policy.

EVIDENCE AND REASONING RULES

- Use only the supplied change record.
- Do not invent outages, vulnerabilities, deadlines, dependencies,
  regulatory obligations, or business consequences.
- Do not assume a change is urgent because its title contains
  words such as "critical", "production", "security", "emergency",
  "performance", or "high priority".
- Distinguish implementation risk from the impact of postponement.
- Consider the stated justification, description, implementation
  plan, risk and impact analysis, backout plan, test plan, and
  scheduled dates when available.
- Consider whether the record identifies a realistic alternative
  or whether the action can safely wait.
- Explain the classification using specific evidence from the
  record.
- Identify missing information that could materially change
  the decision.
- Be conservative about unsupported claims, but do not classify
  every change as high simply to be cautious.

OUTPUT REQUIREMENTS

Return exactly one valid JSON object.
Do not return Markdown fences, introductory text, or explanations
outside the JSON object.

Use this exact schema:
{{
  "risk_classification": "low",
  "requires_exception_approval": false,
  "flag_summary": "Concise explanation of the assessment",
  "business_impact_if_delayed": "Evidence-based explanation",
  "reason": "Explanation supported by the supplied record",
  "missing_information": []
}}

The values above illustrate the required data types and structure.
Replace them with the actual assessment. They are not a default
classification.

STRICT OUTPUT CONSTRAINTS

- "risk_classification" must be exactly one of:
  "high", "low", or "uncertain".
- "requires_exception_approval" must be a JSON boolean: true or false.
- "flag_summary" must be a non-empty string.
- "business_impact_if_delayed" must be a string.
- "reason" must be a non-empty string.
- "missing_information" must be an array of strings.
- If risk_classification is "uncertain", set
  requires_exception_approval to false and explain why manual
  review is needed.
- If risk_classification is "low", set
  requires_exception_approval to false.
- If risk_classification is "high", set
  requires_exception_approval to true only when the evidence
  establishes that proceeding during the freeze is justified.
- Never use true as a substitute for an actual approval decision.

CHANGE RECORD:
{json.dumps(evidence, ensure_ascii=False)}
"""


    base_url = os.getenv("GENAILAB_BASE_URL", GENAILAB_BASE_URL)
    model = os.getenv("GENAILAB_MODEL", GENAILAB_MODEL)

    logger.debug(
        "Invoking LLM for change %s using model='%s', base_url='%s'",
        chg_number,
        model,
        base_url,
    )

    client = httpx.Client(verify=False)
    async_client = httpx.AsyncClient(verify=False)

    try:
        llm = ChatOpenAI(
            base_url=base_url,
            model=model,
            api_key=api_key,
            http_client=client,
            http_async_client=async_client,
            temperature=0.1,
        )

        response = await llm.ainvoke(prompt)
        raw_text = response.content if hasattr(response, "content") else str(response)
        logger.debug("Received raw LLM response for change %s: %s", chg_number, raw_text[:200])

        result = extract_json(raw_text)

        if result.get("risk_classification") not in (
            "high", "low", "uncertain"
        ):
            logger.warning(
                "Invalid risk classification '%s' from LLM for %s",
                result.get("risk_classification"),
                chg_number,
            )
            raise ValueError("Invalid risk classification.")

            if not isinstance(result.get("requires_exception_approval"), bool):
                raise ValueError(
                    "Invalid requires_exception_approval value."
                )

            if result["risk_classification"] != "high":
                result["requires_exception_approval"] = False

        # Add a fallback if LLM doesn't provide a summary.
        if not result.get("flag_summary"):
            logger.info("Applying fallback flag_summary for change %s", chg_number)
            result["flag_summary"] = (
                "The change requires manual review because "
                "the business impact needs clarification."
            )

        logger.info(
            "Risk analysis completed for %s: classification='%s', flag_summary='%s'",
            chg_number,
            result.get("risk_classification"),
            result.get("flag_summary"),
        )
        return result

    except Exception:
        logger.exception(
            "Risk analysis failed for change %s; defaulting to 'uncertain'",
            chg_number,
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
    """Release the hold before applying an exception decision."""
    logger.info(
        "update_exception_decision_work_note called: sys_id=%s, decision=%s",
        sys_id,
        decision,
    )

    if decision not in ("approve", "reject"):
        logger.error("Invalid exception decision '%s' for sys_id=%s", decision, sys_id)
        raise ValueError("Invalid exception decision.")

    if not all([
        SNOW_INSTANCE_URL,
        SNOW_USERNAME,
        SNOW_PASSWORD,
    ]):
        logger.error("ServiceNow configuration is incomplete.")
        raise RuntimeError("ServiceNow configuration is incomplete.")

    if decision == "approve":
        target_state = SCHEDULED_STATE_VALUE
        expected_state = str(SCHEDULED_STATE_VALUE)
        note = (
            "Exception approved by Change Manager. "
            "Storm Mode hold released. Approved to proceed "
            "as per the scheduled implementation window."
        )
    else:
        target_state = CANCELED_STATE_VALUE
        expected_state = str(CANCELED_STATE_VALUE)
        note = (
            "Exception rejected by Change Manager. "
            "Change canceled and will not proceed as scheduled."
        )

    if not target_state:
        logger.error("State value is not configured for decision: %s", decision)
        raise RuntimeError(
            f"State value is not configured for decision: {decision}"
        )

    url = (
        f"{SNOW_INSTANCE_URL}/api/now/table/"
        f"change_request/{sys_id}"
    )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    auth = (SNOW_USERNAME, SNOW_PASSWORD)

    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        # Step 1: Release the Storm Mode hold.
        logger.info("Step 1: Releasing Storm Mode hold for change %s", sys_id)
        release_response = await snow_request_with_retry(
            client,
            "PATCH",
            url,
            auth=auth,
            headers=headers,
            json={"on_hold": False},
        )
        release_response.raise_for_status()

        # Verify that ServiceNow has released the hold.
        logger.info("Step 1: Verifying hold release in ServiceNow for %s", sys_id)
        verify_hold_response = await snow_request_with_retry(
            client,
            "GET",
            url,
            auth=auth,
            headers={"Accept": "application/json"},
            params={
                "sysparm_fields": "sys_id,on_hold",
                "sysparm_display_value": "false",
            },
        )
        verify_hold_response.raise_for_status()

        record = verify_hold_response.json().get("result", {})

        if str(record.get("on_hold", "")).lower() != "false":
            logger.error(
                "ServiceNow did not confirm hold release for %s (on_hold=%s)",
                sys_id,
                record.get("on_hold"),
            )
            raise RuntimeError(
                "ServiceNow did not confirm that the hold was released."
            )
        logger.info("Step 1 verified: Hold released for change %s", sys_id)

        # Step 2: Apply the decision and add its work note.
        logger.info(
            "Step 2: Updating state to '%s' and adding work note for change %s",
            target_state,
            sys_id,
        )
        decision_response = await snow_request_with_retry(
            client,
            "PATCH",
            url,
            auth=auth,
            headers=headers,
            json={
                "state": target_state,
                "work_notes": note,
            },
        )
        decision_response.raise_for_status()

        # Step 3: Verify the final state and hold flag.
        logger.info("Step 3: Verifying final state and hold for %s", sys_id)
        verify_response = await snow_request_with_retry(
            client,
            "GET",
            url,
            auth=auth,
            headers={"Accept": "application/json"},
            params={
                "sysparm_fields": "sys_id,state,on_hold",
                "sysparm_display_value": "false",
            },
        )
        verify_response.raise_for_status()

        final_record = verify_response.json().get("result", {})

        actual_state = str(final_record.get("state", ""))
        actual_hold = str(final_record.get("on_hold", "")).lower()

        if actual_state != expected_state or actual_hold != "false":
            logger.error(
                "Final state mismatch for %s: expected state=%s, got=%s; expected hold=false, got=%s",
                sys_id,
                expected_state,
                actual_state,
                actual_hold,
            )
            raise RuntimeError(
                "ServiceNow did not confirm the requested final state "
                "and released hold."
            )

    logger.info(
        "Successfully applied exception decision '%s' for change %s (final_state=%s)",
        decision,
        sys_id,
        actual_state,
    )

    return {
        "status": "updated",
        "decision": decision,
        "state": actual_state,
        "on_hold": False,
        "work_note_status": "submitted",
    }


async def update_change_work_notes(
    sys_id: str,
    classification: str,
):
    """Add the appropriate freeze work note in ServiceNow."""
    logger.info(
        "update_change_work_notes called: sys_id=%s, classification=%s",
        sys_id,
        classification,
    )

    if classification not in {"high", "low", "uncertain"}:
        logger.error("Invalid risk classification '%s' for sys_id=%s", classification, sys_id)
        raise ValueError(
            f"Invalid risk classification: {classification}"
        )

    if not all([SNOW_INSTANCE_URL, SNOW_USERNAME, SNOW_PASSWORD]):
        logger.error("ServiceNow configuration is incomplete.")
        raise RuntimeError("ServiceNow configuration is incomplete.")

    if classification == "high":
        work_note = f"{FREEZE_NOTE} {HIGH_RISK_NOTE}"
    else:
        work_note = FREEZE_NOTE

    url = (
        f"{SNOW_INSTANCE_URL}/api/now/table/"
        f"change_request/{sys_id}"
    )

    logger.info(
        "Adding freeze work note to change %s in ServiceNow (classification=%s)",
        sys_id,
        classification,
    )

    async with httpx.AsyncClient(timeout=30, verify=False) as client:
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
        response.raise_for_status()

    logger.info("Successfully updated work notes for change %s", sys_id)

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
    logger.info(
        "process_storm_changes started: alert_id=%s, start=%s, end=%s",
        alert_id,
        start.isoformat() if hasattr(start, "isoformat") else start,
        end.isoformat() if hasattr(end, "isoformat") else end,
    )

    from database import get_assessment

    changes = await fetch_changes(start, end)
    logger.info(
        "Processing %d total changes for storm alert_id=%s",
        len(changes),
        alert_id,
    )

    high_risk_changes = []
    low_risk_changes = []
    review_required = []
    update_failures = []

    for idx, change in enumerate(changes, start=1):
        number = change.get("number", "Unknown")
        sys_id = change.get("sys_id")

        logger.info(
            "--- Processing change [%d/%d]: %s (sys_id=%s) ---",
            idx,
            len(changes),
            number,
            sys_id,
        )

        if not sys_id:
            logger.error(
                "Skipping change without sys_id: %s",
                number,
            )
            update_failures.append({
                "number": number,
                "status": "missing_sys_id",
            })
            continue

        # Reuse the saved assessment for this storm and change.
        cached = get_assessment(alert_id, sys_id)

        if cached:
            assessment = cached["assessment"]
            note_status = cached["work_note_status"]
            logger.info(
                "Reusing cached assessment for %s: classification='%s', note_status='%s'",
                number,
                assessment.get("risk_classification"),
                note_status,
            )
        else:
            logger.info("No cached assessment found for %s; running AI analysis...", number)
            assessment = await analyze_change(change)

            # Persist the assessment before attempting ServiceNow
            # updates so a refresh won't rerun LLM unnecessarily.
            save_assessment(alert_id, change, assessment)
            logger.info(
                "Saved new assessment for %s (classification='%s') to DB",
                number,
                assessment.get("risk_classification"),
            )

            if assessment.get("risk_classification") == "high":
                logger.info("Marking high-risk exception pending in DB for %s", number)
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

        # Put change on hold
        try:
            logger.info("Attempting to put change %s on hold in ServiceNow...", number)
            hold_result = await put_change_on_hold(change)

            item["hold_status"] = hold_result["status"]
            item["hold_result"] = hold_result
            logger.info(
                "Hold placement for %s completed with status: %s",
                number,
                hold_result["status"],
            )

            if hold_result["status"] == "failed":
                update_failures.append({
                    "number": number,
                    "status": "hold_update_failed",
                })

        except Exception:
            logger.exception(
                "Failed to put change %s on hold",
                number,
            )
            item["hold_status"] = "failed"
            update_failures.append({
                "number": number,
                "status": "hold_update_failed",
            })

        if classification == "high":
            high_risk_changes.append(item)
        elif classification == "low":
            low_risk_changes.append(item)
        else:
            review_required.append(item)

        # Already confirmed updated: never add the same notes again.
        if note_status == "updated":
            logger.info("Work note already updated for %s; skipping note update.", number)
            continue

        # An earlier request may have reached ServiceNow even if the
        # client did not receive its response. Don't blindly retry it.
        if note_status == "uncertain":
            logger.warning(
                "Work note status for %s is uncertain; flagging for manual review.",
                number,
            )
            item["work_note_status"] = "uncertain"
            if item not in review_required:
                review_required.append(item)
            continue

        try:
            logger.info(
                "Updating freeze work note in ServiceNow for %s (classification=%s)...",
                number,
                classification,
            )
            result = await update_change_work_notes(
                sys_id,
                classification,
            )

            update_work_note_status(
                alert_id, sys_id, result["status"]
            )

            item["work_note_status"] = result["status"]
            logger.info(
                "Successfully updated work note for %s in ServiceNow (status=%s)",
                number,
                result["status"],
            )

        except Exception:
            logger.exception(
                "Work-note update failed for %s",
                number,
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
                "number": number,
                "status": "uncertain",
            })

    summary = {
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

    logger.info(
        "process_storm_changes finished for alert_id=%s: status=%s, total=%d (high=%d, low=%d, review_required=%d, failures=%d)",
        alert_id,
        summary["status"],
        summary["total_changes"],
        summary["high_risk_count"],
        summary["low_risk_count"],
        summary["review_required_count"],
        len(update_failures),
    )

    return summary


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
    logger.debug(
        "snow_request_with_retry: %s %s (max_attempts=%d)",
        method,
        url,
        max_attempts,
    )

    for attempt in range(1, max_attempts + 1):
        try:
            logger.debug(
                "ServiceNow attempt %d/%d: %s %s",
                attempt,
                max_attempts,
                method,
                url,
            )
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
                    "ServiceNow returned HTTP %s on attempt %d/%d. Retry in %s seconds.",
                    response.status_code,
                    attempt,
                    max_attempts,
                    interval,
                )
                await asyncio.sleep(interval)
                continue

            response.raise_for_status()
            if attempt > 1:
                logger.info(
                    "ServiceNow request succeeded on attempt %d after retry: %s %s",
                    attempt,
                    method,
                    url,
                )
            return response

        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text[:1000] if hasattr(exc, "response") else ""
            logger.error(
                "ServiceNow HTTP %s for %s %s. Response: %s",
                exc.response.status_code,
                method,
                url,
                error_body,
            )
            raise

        except httpx.RequestError as exc:
            if attempt == max_attempts:
                logger.error(
                    "ServiceNow request failed after %s attempts: %s for %s %s",
                    max_attempts,
                    type(exc).__name__,
                    method,
                    url,
                )
                raise

            logger.warning(
                "ServiceNow connection error on attempt %d/%d (%s). Retry in %s seconds.",
                attempt,
                max_attempts,
                type(exc).__name__,
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
    """Retry transient Gemini/HTTP errors and network timeouts."""
    logger.debug("gemini_request_with_retry: POST %s (max_attempts=%d)", url, max_attempts)

    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.post(url, **kwargs)

            if (
                response.status_code
                in (429, 500, 502, 503, 504)
                and attempt < max_attempts
            ):
                logger.warning(
                    "LLM HTTP endpoint returned %s; retry %s/%s in %s seconds.",
                    response.status_code,
                    attempt,
                    max_attempts,
                    interval,
                )
                await asyncio.sleep(interval)
                continue

            response.raise_for_status()
            return response

        except httpx.RequestError as exc:
            if attempt == max_attempts:
                logger.error(
                    "LLM HTTP request failed after %s attempts: %s",
                    max_attempts,
                    type(exc).__name__,
                )
                raise

            logger.warning(
                "LLM HTTP connection error; retry %s/%s in %s seconds.",
                attempt,
                max_attempts,
                interval,
            )
            await asyncio.sleep(interval)

    raise RuntimeError("LLM retry loop ended unexpectedly.")


async def put_change_on_hold(change: dict):
    """Place a scheduled change on hold without changing its state."""
    number = change.get("number", "Unknown")
    sys_id = change.get("sys_id")
    current_state = str(change.get("state", "")).strip().lower()
    already_on_hold = (
        str(change.get("on_hold", "false")).strip().lower() == "true"
    )

    logger.info(
        "put_change_on_hold called for %s (sys_id=%s): state='%s', on_hold=%s",
        number,
        sys_id,
        current_state,
        already_on_hold,
    )

    if current_state != "scheduled":
        logger.info(
            "Skipping hold for %s: state '%s' is not 'Scheduled'",
            number,
            current_state,
        )
        return {
            "sys_id": sys_id,
            "status": "skipped",
            "reason": "Change is not in Scheduled state.",
        }

    if already_on_hold:
        logger.info(
            "Skipping hold for %s: change is already on hold.",
            number,
        )
        return {
            "sys_id": sys_id,
            "status": "already_on_hold",
            "reason": "Change is already on hold.",
        }

    if not all([SNOW_INSTANCE_URL, SNOW_USERNAME, SNOW_PASSWORD]):
        logger.error("ServiceNow configuration is incomplete.")
        raise RuntimeError("ServiceNow configuration is incomplete.")

    url = (
        f"{SNOW_INSTANCE_URL}/api/now/table/"
        f"change_request/{sys_id}"
    )

    logger.info("Sending PATCH to place %s on hold in ServiceNow...", number)

    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        response = await snow_request_with_retry(
            client,
            "PATCH",
            url,
            auth=(SNOW_USERNAME, SNOW_PASSWORD),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "on_hold": True,
                "on_hold_reason": (
                    "Storm Mode: implementation temporarily suspended "
                    "due to severe weather."
                ),
            },
        )
        response.raise_for_status()

    logger.info("Successfully placed change %s on hold in ServiceNow.", number)

    return {
        "sys_id": sys_id,
        "status": "updated",
        "on_hold": True,
        "state": "Scheduled",
    }
