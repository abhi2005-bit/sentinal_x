"""
SENTINEL-X — External Systems Simulator.

Simulates booking, payment, email, and calendar APIs with
controllable latencies and configurable effect outcomes.
Used for deterministic demo and benchmark scenarios.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ExternalSystemType(str, Enum):
    FLIGHT_BOOKING = "FLIGHT_BOOKING"
    HOTEL_BOOKING = "HOTEL_BOOKING"
    PAYMENT = "PAYMENT"
    EMAIL = "EMAIL"
    CALENDAR = "CALENDAR"


@dataclass
class ExternalResponse:
    """Response from a simulated external system."""
    success: bool
    reference_id: str = ""
    status: str = "unknown"
    data: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0


@dataclass
class SystemConfig:
    """Config for one simulated external system."""
    system_type: ExternalSystemType
    latency_ms: int = 500            # simulated processing time
    success_rate: float = 1.0        # 1.0 = always succeed
    cancellation_supported: bool = True
    compensation_available: bool = True
    # When set, force a specific outcome (for deterministic demos)
    forced_outcome: Optional[str] = None  # "committed" | "failed" | "pending"


class ExternalSystemSimulator:
    """
    Simulates external service APIs for the travel-agent demo.

    Each system is independently configurable for latency, success rate,
    and forced outcomes.
    """

    def __init__(self) -> None:
        self._systems: dict[str, SystemConfig] = {}
        self._bookings: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def register_system(self, name: str, config: SystemConfig) -> None:
        self._systems[name] = config

    def _next_ref(self, prefix: str = "REF") -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:05d}"

    async def execute(
        self,
        system_name: str,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> ExternalResponse:
        """
        Simulate an external API call.

        Returns an :class:`ExternalResponse` after the configured latency.
        """
        config = self._systems.get(system_name)
        if config is None:
            return ExternalResponse(
                success=False,
                status="error",
                data={"error": f"System {system_name!r} not registered"},
            )

        # Simulate latency
        await asyncio.sleep(config.latency_ms / 1000)

        # Determine outcome
        if config.forced_outcome:
            outcome = config.forced_outcome
        elif random.random() <= config.success_rate:
            outcome = "committed"
        else:
            outcome = "failed"

        ref_id = self._next_ref(system_name.upper()[:3])

        if outcome == "committed":
            self._bookings[ref_id] = {
                "system": system_name,
                "operation": operation,
                "params": params or {},
                "status": "committed",
            }
            return ExternalResponse(
                success=True,
                reference_id=ref_id,
                status="committed",
                data={"operation": operation, "params": params or {}},
                latency_ms=config.latency_ms,
            )
        elif outcome == "pending":
            self._bookings[ref_id] = {
                "system": system_name,
                "operation": operation,
                "params": params or {},
                "status": "pending",
            }
            return ExternalResponse(
                success=True,
                reference_id=ref_id,
                status="pending",
                data={"operation": operation, "message": "Processing..."},
                latency_ms=config.latency_ms,
            )
        else:
            return ExternalResponse(
                success=False,
                reference_id=ref_id,
                status="failed",
                data={"error": "Simulated failure"},
                latency_ms=config.latency_ms,
            )

    async def verify_status(self, reference_id: str) -> ExternalResponse:
        """
        Check the current status of a previously issued request.

        This is the key API for the late-interrupt verification flow.
        """
        booking = self._bookings.get(reference_id)
        if booking is None:
            return ExternalResponse(
                success=False,
                reference_id=reference_id,
                status="not_found",
                data={"error": "No booking found with this reference"},
            )
        return ExternalResponse(
            success=True,
            reference_id=reference_id,
            status=booking["status"],
            data=booking,
        )

    async def cancel(self, reference_id: str) -> ExternalResponse:
        """
        Attempt to cancel a previously committed/pending booking.
        """
        booking = self._bookings.get(reference_id)
        if booking is None:
            return ExternalResponse(
                success=False,
                reference_id=reference_id,
                status="not_found",
                data={"error": "No booking found"},
            )

        system_name = booking.get("system", "")
        config = self._systems.get(system_name)

        if config and not config.cancellation_supported:
            return ExternalResponse(
                success=False,
                reference_id=reference_id,
                status="cancellation_not_supported",
                data={"error": "This system does not support cancellation"},
            )

        if booking["status"] == "committed":
            if config and config.compensation_available:
                booking["status"] = "cancelled"
                return ExternalResponse(
                    success=True,
                    reference_id=reference_id,
                    status="cancelled",
                    data={"message": "Booking cancelled successfully"},
                )
            else:
                return ExternalResponse(
                    success=False,
                    reference_id=reference_id,
                    status="committed",
                    data={"error": "Cannot cancel committed booking — no compensation available"},
                )
        elif booking["status"] == "pending":
            booking["status"] = "cancelled"
            return ExternalResponse(
                success=True,
                reference_id=reference_id,
                status="cancelled",
                data={"message": "Pending request cancelled"},
            )
        else:
            return ExternalResponse(
                success=False,
                reference_id=reference_id,
                status=booking["status"],
                data={"error": f"Cannot cancel booking in state: {booking['status']}"},
            )

    def reset(self) -> None:
        """Clear all bookings (for benchmark/demo reset)."""
        self._bookings.clear()
        self._counter = 0


def create_travel_simulator() -> ExternalSystemSimulator:
    """
    Factory that returns a simulator pre-configured with
    flight, hotel, payment, email, and calendar systems.
    """
    sim = ExternalSystemSimulator()
    sim.register_system("flight_booking", SystemConfig(
        system_type=ExternalSystemType.FLIGHT_BOOKING,
        latency_ms=300,
        cancellation_supported=True,
        compensation_available=True,
    ))
    sim.register_system("hotel_booking", SystemConfig(
        system_type=ExternalSystemType.HOTEL_BOOKING,
        latency_ms=250,
        cancellation_supported=True,
        compensation_available=True,
    ))
    sim.register_system("payment", SystemConfig(
        system_type=ExternalSystemType.PAYMENT,
        latency_ms=400,
        cancellation_supported=False,
        compensation_available=False,
    ))
    sim.register_system("email", SystemConfig(
        system_type=ExternalSystemType.EMAIL,
        latency_ms=100,
        cancellation_supported=False,
        compensation_available=False,
    ))
    sim.register_system("calendar", SystemConfig(
        system_type=ExternalSystemType.CALENDAR,
        latency_ms=150,
        cancellation_supported=True,
        compensation_available=True,
    ))
    return sim
