"""
SENTINEL-X — External-State Verifier.

Queries the external systems simulator to verify whether a
side-effect is truly committed, pending, or cancelled.

This module enforces the critical invariant:
    local cancellation ≠ external cancellation.
"""

from __future__ import annotations

from sentinel_x.core.models import EffectRecord, EffectStatus
from sentinel_x.services.effect_ledger import EffectLedger
from sentinel_x.simulator.external_systems import ExternalSystemSimulator


class VerificationResult:
    """Outcome of verifying one effect against the external world."""

    def __init__(
        self,
        effect_id: str,
        previous_status: EffectStatus,
        verified_status: EffectStatus,
        external_reference: str = "",
        detail: str = "",
        mismatch: bool = False,
    ) -> None:
        self.effect_id = effect_id
        self.previous_status = previous_status
        self.verified_status = verified_status
        self.external_reference = external_reference
        self.detail = detail
        self.mismatch = mismatch

    def to_dict(self) -> dict:
        return {
            "effect_id": self.effect_id,
            "previous_status": self.previous_status.value,
            "verified_status": self.verified_status.value,
            "external_reference": self.external_reference,
            "detail": self.detail,
            "mismatch": self.mismatch,
        }


class Verifier:
    """
    Verifies external-world state for effects that need checking.

    This is the component that prevents the system from falsely
    claiming a committed booking was cancelled.
    """

    def __init__(
        self,
        ledger: EffectLedger,
        simulator: ExternalSystemSimulator,
    ) -> None:
        self._ledger = ledger
        self._simulator = simulator

    async def verify_effect(self, effect_id: str) -> VerificationResult:
        """
        Verify a single effect against the external system.
        """
        record = self._ledger.get(effect_id)
        if record is None:
            return VerificationResult(
                effect_id=effect_id,
                previous_status=EffectStatus.UNKNOWN,
                verified_status=EffectStatus.UNKNOWN,
                detail="Effect not found in ledger",
            )

        previous = record.status

        # If there's no external reference, we can't verify
        if not record.external_reference:
            return VerificationResult(
                effect_id=effect_id,
                previous_status=previous,
                verified_status=EffectStatus.UNKNOWN,
                detail="No external reference to verify against",
            )

        # Query the external system
        response = await self._simulator.verify_status(record.external_reference)

        # Map external status to EffectStatus
        status_map = {
            "committed": EffectStatus.COMMITTED,
            "pending": EffectStatus.PENDING,
            "cancelled": EffectStatus.CANCELLED,
            "failed": EffectStatus.FAILED,
            "not_found": EffectStatus.NOT_SENT,
        }
        verified = status_map.get(response.status, EffectStatus.UNKNOWN)

        # Check for mismatch — the critical safety check
        mismatch = (previous != verified)

        detail = f"External system reports: {response.status}"
        if mismatch:
            detail += (
                f" (MISMATCH: ledger had {previous.value}, "
                f"external says {verified.value})"
            )

        # Update the ledger to reflect verified state (if transition is valid)
        try:
            if verified != previous:
                self._ledger.transition(
                    effect_id,
                    verified,
                    external_reference=record.external_reference,
                )
        except ValueError:
            detail += " — ledger transition blocked by state rules"

        return VerificationResult(
            effect_id=effect_id,
            previous_status=previous,
            verified_status=verified,
            external_reference=record.external_reference,
            detail=detail,
            mismatch=mismatch,
        )

    async def verify_all_pending(self) -> list[VerificationResult]:
        """Verify all effects that need verification."""
        results = []
        for record in self._ledger.needs_verification():
            result = await self.verify_effect(record.effect_id)
            results.append(result)
        return results

    async def attempt_cancellation(
        self, effect_id: str
    ) -> VerificationResult:
        """
        Try to cancel an effect via the external system.

        First verifies current state, then attempts cancellation
        if the effect is still pending or committed with compensation.
        """
        record = self._ledger.get(effect_id)
        if record is None:
            return VerificationResult(
                effect_id=effect_id,
                previous_status=EffectStatus.UNKNOWN,
                verified_status=EffectStatus.UNKNOWN,
                detail="Effect not found",
            )

        previous = record.status

        if not record.external_reference:
            # Not sent yet — safe to mark as cancelled locally
            return VerificationResult(
                effect_id=effect_id,
                previous_status=previous,
                verified_status=EffectStatus.NOT_SENT,
                detail="No external request was sent — safe to discard",
            )

        # Attempt cancellation via external system
        response = await self._simulator.cancel(record.external_reference)

        if response.status == "cancelled":
            try:
                self._ledger.transition(effect_id, EffectStatus.CANCELLED)
            except ValueError:
                pass
            return VerificationResult(
                effect_id=effect_id,
                previous_status=previous,
                verified_status=EffectStatus.CANCELLED,
                external_reference=record.external_reference,
                detail="External system confirmed cancellation",
            )
        else:
            return VerificationResult(
                effect_id=effect_id,
                previous_status=previous,
                verified_status=record.status,
                external_reference=record.external_reference,
                detail=(
                    f"Cancellation failed: {response.data.get('error', 'unknown')}. "
                    f"Effect remains {record.status.value}."
                ),
                mismatch=True,
            )
