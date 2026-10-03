"""
SENTINEL-X — Event schema and normalization primitives.

Provides deterministic rule-based semantic interpretation so the
demo works without an LLM API key.  The LLM interpreter in
``services/interpreter.py`` produces the same :class:`SemanticEvent`
schema; this module is the fallback.
"""

from __future__ import annotations

import re
from typing import Optional

from sentinel_x.core.models import (
    ChangeClass,
    EventType,
    SemanticEvent,
)


# ── Keyword-based rules ─────────────────────────────────────────────────

_RULES: list[dict] = [
    {
        "patterns": [
            r"\bcancel\s+everything\b",
            r"\bstop\s+everything\b",
            r"\babort\s+all\b",
            r"\bcancel\s+all\b",
        ],
        "event_type": EventType.GLOBAL_CANCELLATION,
        "change_class": ChangeClass.GLOBAL_CANCEL,
        "replan_required": True,
    },
    {
        "patterns": [
            r"\bdo\s+not\s+book\b",
            r"\bdon'?t\s+book\b",
            r"\bno\s+booking\b",
            r"\bstop\s+(?:the\s+)?booking\b",
            r"\bdo\s+not\s+purchase\b",
            r"\bdon'?t\s+purchase\b",
            r"\bonly\s+research",
        ],
        "event_type": EventType.AUTHORIZATION_CHANGE,
        "change_class": ChangeClass.AUTHORIZATION,
        "authorization_changes": ["booking_removed"],
        "affected_task_hints": ["book", "purchase", "payment", "confirm"],
        "replan_required": True,
    },
    {
        "patterns": [
            r"\bchange\s+(?:the\s+)?destination\s+to\s+(\w+)\b",
            r"\bgo\s+to\s+(\w+)\s+instead\b",
            r"\bchange\s+.*?to\s+(\w+)\b",
        ],
        "event_type": EventType.ENTITY_CHANGE,
        "change_class": ChangeClass.ENTITY,
        "replan_required": True,
        "entity_capture_key": "destination",
    },
    {
        "patterns": [
            r"\b(?:change|use|switch\s+to)\s+(?:the\s+)?(?:date|day)\b",
            r"\btomorrow\b",
            r"\bnext\s+\w+\b",
        ],
        "event_type": EventType.CONSTRAINT_CHANGE,
        "change_class": ChangeClass.CONSTRAINT,
        "replan_required": True,
    },
    {
        "patterns": [
            r"\bonly\s+(?:want|need)\s+research\b",
            r"\bjust\s+research\b",
            r"\bresearch\s+only\b",
        ],
        "event_type": EventType.GOAL_CHANGE,
        "change_class": ChangeClass.GOAL,
        "goal_changes": ["research_only"],
        "authorization_changes": ["booking_removed"],
        "affected_task_hints": ["book", "purchase", "payment", "confirm"],
        "replan_required": True,
    },
    {
        "patterns": [
            r"\bcontinue\b",
            r"\bgo\s+ahead\b",
            r"\bokay\b",
            r"\bproceed\b",
        ],
        "event_type": EventType.NON_IMPACTING,
        "change_class": ChangeClass.NON_IMPACTING,
        "replan_required": False,
    },
]


# ── Public API ───────────────────────────────────────────────────────────

def normalize_event(raw_text: str) -> SemanticEvent:
    """
    Apply deterministic keyword rules to produce a
    :class:`SemanticEvent`.  This is the rule-based fallback used
    when no LLM provider is configured.
    """
    text = raw_text.strip().lower()

    for rule in _RULES:
        for pattern in rule["patterns"]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                event = SemanticEvent(
                    raw_text=raw_text,
                    event_type=rule["event_type"],
                    change_class=rule["change_class"],
                    replan_required=rule.get("replan_required", False),
                    confidence=0.85,  # rule-based → slightly below 1.0
                )

                # Copy list/dict fields when present in the rule
                if "goal_changes" in rule:
                    event.goal_changes = list(rule["goal_changes"])
                if "authorization_changes" in rule:
                    event.authorization_changes = list(
                        rule["authorization_changes"]
                    )
                if "affected_task_hints" in rule:
                    event.affected_task_hints = list(
                        rule["affected_task_hints"]
                    )
                if "constraints_added" in rule:
                    event.constraints_added = list(rule["constraints_added"])

                # Entity change: capture the new value from regex groups
                if rule.get("entity_capture_key") and match.lastindex:
                    event.entity_changes = {
                        rule["entity_capture_key"]: match.group(1).title()
                    }
                    event.affected_task_hints = [
                        rule["entity_capture_key"],
                        "search",
                        "compare",
                    ]

                return event

    # Nothing matched → treat as non-impacting
    return SemanticEvent(
        raw_text=raw_text,
        event_type=EventType.NON_IMPACTING,
        change_class=ChangeClass.NON_IMPACTING,
        replan_required=False,
        confidence=0.50,
    )


def classify_event(event: SemanticEvent) -> str:
    """Return a human-readable one-liner describing the event."""
    labels = {
        ChangeClass.AUTHORIZATION: "Authorization change",
        ChangeClass.GOAL: "Goal change",
        ChangeClass.CONSTRAINT: "Constraint change",
        ChangeClass.ENTITY: "Entity change",
        ChangeClass.GLOBAL_CANCEL: "Global cancellation",
        ChangeClass.NON_IMPACTING: "Non-impacting event",
        ChangeClass.EXTERNAL: "External-world change",
    }
    base = labels.get(event.change_class, "Unknown")
    if event.entity_changes:
        details = ", ".join(
            f"{k}→{v}" for k, v in event.entity_changes.items()
        )
        return f"{base} ({details})"
    if event.authorization_changes:
        return f"{base} ({', '.join(event.authorization_changes)})"
    return base
