"""
SENTINEL-X — Side-Effect Ledger Service.

Manages :class:`EffectRecord` lifecycle.  Tracks every external
action the agent performs and enforces state-transition rules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sentinel_x.core.models import EffectRecord, EffectStatus, _new_id


# Valid state transitions
_VALID_TRANSITIONS: dict[EffectStatus, set[EffectStatus]] = {
    EffectStatus.NOT_SENT: {EffectStatus.PENDING, EffectStatus.FAILED},
    EffectStatus.PENDING: {
        EffectStatus.COMMITTED,
        EffectStatus.FAILED,
        EffectStatus.UNKNOWN,
        EffectStatus.CANCELLED,
    },
    EffectStatus.COMMITTED: {EffectStatus.CANCELLED},  # only via compensation
    EffectStatus.FAILED: set(),       # terminal
    EffectStatus.UNKNOWN: {
        EffectStatus.COMMITTED,
        EffectStatus.FAILED,
        EffectStatus.CANCELLED,
    },
    EffectStatus.CANCELLED: set(),    # terminal
}


class EffectLedger:
    """
    In-memory ledger of external side-effects.

    Enforces valid state transitions and provides queries
    for the recovery engine.
    """

    def __init__(self) -> None:
        self._effects: dict[str, EffectRecord] = {}

    # ── Creation ─────────────────────────────────────────────────────

    def register(
        self,
        task_id: str,
        operation: str,
        request_id: str = "",
        compensation_available: bool = False,
    ) -> EffectRecord:
        """Create a new effect record in NOT_SENT state."""
        record = EffectRecord(
            task_id=task_id,
            operation=operation,
            request_id=request_id,
            compensation_available=compensation_available,
        )
        self._effects[record.effect_id] = record
        return record

    # ── Transitions ──────────────────────────────────────────────────

    def transition(
        self,
        effect_id: str,
        new_status: EffectStatus,
        external_reference: str = "",
        result: dict | None = None,
    ) -> EffectRecord:
        """
        Move an effect to a new state.

        Raises ``ValueError`` if the transition is not valid.
        """
        record = self._effects.get(effect_id)
        if record is None:
            raise KeyError(f"Effect {effect_id!r} not found")

        allowed = _VALID_TRANSITIONS.get(record.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {record.status.value} → {new_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        record.status = new_status
        record.updated_at = datetime.now(timezone.utc)
        if external_reference:
            record.external_reference = external_reference
        if result:
            record.result = result
        return record

    # ── Queries ──────────────────────────────────────────────────────

    def get(self, effect_id: str) -> Optional[EffectRecord]:
        return self._effects.get(effect_id)

    def get_by_task(self, task_id: str) -> list[EffectRecord]:
        return [e for e in self._effects.values() if e.task_id == task_id]

    def all_effects(self) -> list[EffectRecord]:
        return list(self._effects.values())

    def pending_effects(self) -> list[EffectRecord]:
        return [
            e for e in self._effects.values()
            if e.status == EffectStatus.PENDING
        ]

    def committed_effects(self) -> list[EffectRecord]:
        return [
            e for e in self._effects.values()
            if e.status == EffectStatus.COMMITTED
        ]

    def needs_verification(self) -> list[EffectRecord]:
        """Effects in PENDING, COMMITTED, or UNKNOWN state need external check."""
        return [
            e for e in self._effects.values()
            if e.status in (
                EffectStatus.PENDING,
                EffectStatus.COMMITTED,
                EffectStatus.UNKNOWN,
            )
        ]

    def to_list(self) -> list[dict]:
        return [e.model_dump(mode="json") for e in self._effects.values()]
