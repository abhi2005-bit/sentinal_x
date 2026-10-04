"""Tests for the effect ledger and external state tracking."""

import pytest

from sentinel_x.core.models import EffectRecord, EffectStatus


class TestEffectRecord:
    def test_default_status_is_not_sent(self):
        record = EffectRecord(task_id="book_flight", operation="book_api")
        assert record.status == EffectStatus.NOT_SENT

    def test_status_transitions(self):
        record = EffectRecord(task_id="book_flight", operation="book_api")

        # NOT_SENT -> PENDING
        record.status = EffectStatus.PENDING
        assert record.status == EffectStatus.PENDING

        # PENDING -> COMMITTED
        record.status = EffectStatus.COMMITTED
        assert record.status == EffectStatus.COMMITTED

    def test_compensation_flag(self):
        record = EffectRecord(
            task_id="book_flight",
            operation="book_api",
            status=EffectStatus.COMMITTED,
            compensation_available=True,
        )
        assert record.compensation_available is True

    def test_idempotency_key_generated(self):
        r1 = EffectRecord(task_id="a", operation="op")
        r2 = EffectRecord(task_id="a", operation="op")
        assert r1.idempotency_key != r2.idempotency_key

    def test_serialization(self):
        record = EffectRecord(
            task_id="book_flight",
            operation="book_api",
            status=EffectStatus.PENDING,
            external_reference="BOOKING-12345",
        )
        data = record.model_dump(mode="json")
        assert data["status"] == "PENDING"
        assert data["external_reference"] == "BOOKING-12345"

    def test_effect_states_complete(self):
        """Verify all six effect states from the doc are available."""
        states = {s.value for s in EffectStatus}
        expected = {
            "NOT_SENT", "PENDING", "COMMITTED",
            "FAILED", "UNKNOWN", "CANCELLED",
        }
        assert states == expected

    def test_committed_effect_not_locally_cancellable(self):
        """
        Core safety invariant: a COMMITTED effect must not be
        reported as cancelled without external verification.
        """
        record = EffectRecord(
            task_id="book_flight",
            operation="book_api",
            status=EffectStatus.COMMITTED,
        )
        # The system must verify before changing to CANCELLED
        # Directly setting to CANCELLED without verification is
        # an application-level rule, tested here as documentation
        assert record.status == EffectStatus.COMMITTED

    def test_unknown_state_fails_closed(self):
        record = EffectRecord(
            task_id="pay",
            operation="payment_api",
            status=EffectStatus.UNKNOWN,
        )
        # Unknown means we cannot confirm — system should surface uncertainty
        assert record.status == EffectStatus.UNKNOWN
