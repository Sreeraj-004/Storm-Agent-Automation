
def build_exception_card(change: dict, alert_id: str) -> dict:
    """Build an Adaptive Card for User 2's exception decision."""

    assessment = change.get("risk_assessment", {})

    flag_summary = assessment.get(
        "flag_summary",
        "Flagged for review due to potential business impact."
    )

    return {
        "$schema": (
            "https://adaptivecards.io/schemas/"
            "adaptive-card.json"
        ),
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "Storm Freeze - Exception Request",
                "weight": "Bolder",
                "size": "Large",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {
                        "title": "Change",
                        "value": str(
                            change.get("number", "Unknown")
                        ),
                    },
                    {
                        "title": "Description",
                        "value": str(
                            change.get(
                                "short_description",
                                "Not provided",
                            )
                        ),
                    },
                    {
                        "title": "Change type",
                        "value": str(
                            change.get("type", "Unknown")
                        ),
                    },
                    {
                        "title": "Risk assessment",
                        "value": "High - AI recommendation",
                    },
                ],
            },
            {
                "type": "TextBlock",
                "text": "Why was this flagged?",
                "weight": "Bolder",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": str(flag_summary),
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "Business impact if postponed",
                "weight": "Bolder",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": str(
                    assessment.get(
                        "business_impact_if_delayed",
                        "Impact information unavailable.",
                    )
                ),
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": "AI reasoning",
                "weight": "Bolder",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": str(
                    assessment.get(
                        "reason",
                        "Manual review is required.",
                    )
                ),
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": (
                    "The AI recommendation is not approval. "
                    "Your decision is required."
                ),
                "isSubtle": True,
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Accept Exception",
                "style": "positive",
                "data": {
                    "action": "accept",
                    "alert_id": alert_id,
                    "sys_id": change.get("sys_id"),
                },
            },
            {
                "type": "Action.Submit",
                "title": "Reject Exception",
                "style": "destructive",
                "data": {
                    "action": "reject",
                    "alert_id": alert_id,
                    "sys_id": change.get("sys_id"),
                },
            },
        ],
    }
