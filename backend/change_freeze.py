
import logging
import asyncio
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

logger = logging.getLogger(__name__)

SNOW_INSTANCE_URL = os.getenv(
    "SNOW_INSTANCE_URL", ""
).rstrip("/")
SNOW_USERNAME = os.getenv("SNOW_USERNAME")
SNOW_PASSWORD = os.getenv("SNOW_PASSWORD")

FREEZE_NOTE = "Change freeze applied until further notice."
HIGH_RISK_NOTE = (
    "Analyzed the risk of the change, requested for approval "
    "to continue the change as per the schedule."
)



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



async def apply_change_freeze(start: datetime, end: datetime):
    """Find overlapping change requests and add freeze work notes."""

    if not all([
        SNOW_INSTANCE_URL,
        SNOW_USERNAME,
        SNOW_PASSWORD,
    ]):
        raise HTTPException(
            status_code=500,
            detail="ServiceNow configuration is incomplete.",
        )

    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail="Storm dates must include timezone information.",
        )

    if end <= start:
        raise HTTPException(
            status_code=400,
            detail="Storm end must be after storm start.",
        )

    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)

    start_value = start.strftime("%Y-%m-%d %H:%M:%S")
    end_value = end.strftime("%Y-%m-%d %H:%M:%S")

    base_url = (
        f"{SNOW_INSTANCE_URL}/api/now/table/change_request"
    )

    auth = (SNOW_USERNAME, SNOW_PASSWORD)
    headers = {"Accept": "application/json"}

    params = {
        "sysparm_query": (
            f"start_date<={end_value}"
            f"^end_date>={start_value}"
            "^ORDERBYstart_date"
        ),
        "sysparm_fields": (
            "sys_id,number,short_description,start_date,end_date"
        ),
        "sysparm_limit": "100",
    }

    results = []

    try:
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            # Retrieve changes overlapping the storm window.
            response = await snow_request_with_retry(
                client,
                "GET",
                base_url,
                params=params,
                auth=auth,
                headers=headers,
            )
            response.raise_for_status()

            changes = response.json().get("result", [])

            # Update the work notes on each matching change.
            for change in changes:
                sys_id = change.get("sys_id")
                number = change.get("number")

                if not sys_id:
                    results.append({
                        "number": number,
                        "status": "failed",
                        "message": "Missing sys_id.",
                    })
                    continue

                try:
                    update_response = await client.patch(
                        f"{base_url}/{sys_id}",
                        auth=auth,
                        headers={
                            **headers,
                            "Content-Type": "application/json",
                        },
                        json={"work_notes": FREEZE_NOTE},
                    )
                    update_response.raise_for_status()

                    results.append({
                        "number": number,
                        "status": "updated",
                    })

                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "Work note update failed for %s: HTTP %s",
                        number,
                        exc.response.status_code,
                    )
                    results.append({
                        "number": number,
                        "status": "failed",
                        "message": (
                            f"ServiceNow HTTP "
                            f"{exc.response.status_code}"
                        ),
                    })

                except httpx.RequestError:
                    logger.exception(
                        "ServiceNow request failed for %s", number
                    )
                    results.append({
                        "number": number,
                        "status": "failed",
                        "message": "ServiceNow connection failed.",
                    })

    except httpx.HTTPStatusError as exc:
        logger.error(
            "ServiceNow lookup failed: HTTP %s",
            exc.response.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to retrieve ServiceNow changes.",
        ) from exc

    except httpx.RequestError as exc:
        logger.exception("ServiceNow connection failed")
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to ServiceNow.",
        ) from exc

    updated = sum(
        item["status"] == "updated" for item in results
    )
    failed = sum(
        item["status"] == "failed" for item in results
    )

    return {
        "status": (
            "completed" if failed == 0
            else "partial_failure" if updated > 0
            else "failed"
        ),
        "storm_period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "total_changes": len(results),
        "updated": updated,
        "failed": failed,
        "results": results,
    }
