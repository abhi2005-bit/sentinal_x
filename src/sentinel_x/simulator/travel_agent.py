"""
SENTINEL-X — Travel Agent Scenario Builder.

Creates the canonical travel-planning task graph and provides
pre-built demo scenarios for benchmarking and demonstration.
"""

from __future__ import annotations

from sentinel_x.core.models import TaskNode, TaskType
from sentinel_x.core.task_graph import TaskGraph


def build_travel_graph(
    origin: str = "Chennai",
    destination: str = "Delhi",
) -> TaskGraph:
    """
    Build the canonical travel-agent graph from the documentation:

        search_flights → compare_flights → book_flight
               |               |
               |               +→ itinerary
               |
        search_hotel → compare_hotel --------→ itinerary
    """
    tasks = [
        TaskNode(
            id="search_flights",
            description=f"Search flights from {origin} to {destination}",
            task_type=TaskType.EXTERNAL,
            tags=["search", "flight", "destination", origin.lower(), destination.lower()],
            metadata={"origin": origin, "destination": destination},
        ),
        TaskNode(
            id="search_hotel",
            description=f"Search hotels in {destination}",
            task_type=TaskType.EXTERNAL,
            tags=["search", "hotel", "destination", destination.lower()],
            metadata={"destination": destination},
        ),
        TaskNode(
            id="compare_flights",
            description="Compare flight options and select the best",
            task_type=TaskType.PURE,
            dependencies=["search_flights"],
            tags=["compare", "flight"],
        ),
        TaskNode(
            id="compare_hotel",
            description="Compare hotel options and select the best",
            task_type=TaskType.PURE,
            dependencies=["search_hotel"],
            tags=["compare", "hotel"],
        ),
        TaskNode(
            id="book_flight",
            description=f"Book the selected flight from {origin} to {destination}",
            task_type=TaskType.IRREVERSIBLE,
            dependencies=["compare_flights"],
            tags=["book", "flight", "purchase", "booking"],
            metadata={"system": "flight_booking"},
        ),
        TaskNode(
            id="itinerary",
            description="Create a travel itinerary combining flights and hotel",
            task_type=TaskType.PURE,
            dependencies=["compare_flights", "compare_hotel"],
            tags=["itinerary", "planning"],
        ),
    ]

    graph = TaskGraph()
    graph.add_tasks(tasks)
    return graph


def build_extended_travel_graph(
    origin: str = "Chennai",
    destination: str = "Delhi",
) -> TaskGraph:
    """
    Extended version with hotel booking, payment, email, and calendar tasks.
    """
    tasks = [
        TaskNode(
            id="search_flights",
            description=f"Search flights from {origin} to {destination}",
            task_type=TaskType.EXTERNAL,
            tags=["search", "flight", "destination", origin.lower(), destination.lower()],
            metadata={"origin": origin, "destination": destination},
        ),
        TaskNode(
            id="search_hotel",
            description=f"Search hotels in {destination}",
            task_type=TaskType.EXTERNAL,
            tags=["search", "hotel", "destination", destination.lower()],
            metadata={"destination": destination},
        ),
        TaskNode(
            id="compare_flights",
            description="Compare flight options and select the best",
            task_type=TaskType.PURE,
            dependencies=["search_flights"],
            tags=["compare", "flight"],
        ),
        TaskNode(
            id="compare_hotel",
            description="Compare hotel options and select the best",
            task_type=TaskType.PURE,
            dependencies=["search_hotel"],
            tags=["compare", "hotel"],
        ),
        TaskNode(
            id="book_flight",
            description=f"Book the selected flight to {destination}",
            task_type=TaskType.IRREVERSIBLE,
            dependencies=["compare_flights"],
            tags=["book", "flight", "purchase", "booking"],
            metadata={"system": "flight_booking"},
        ),
        TaskNode(
            id="book_hotel",
            description=f"Book the selected hotel in {destination}",
            task_type=TaskType.IRREVERSIBLE,
            dependencies=["compare_hotel"],
            tags=["book", "hotel", "purchase", "booking"],
            metadata={"system": "hotel_booking"},
        ),
        TaskNode(
            id="process_payment",
            description="Process payment for flight and hotel bookings",
            task_type=TaskType.IRREVERSIBLE,
            dependencies=["book_flight", "book_hotel"],
            tags=["payment", "purchase"],
            metadata={"system": "payment"},
        ),
        TaskNode(
            id="send_confirmation",
            description="Send booking confirmation email",
            task_type=TaskType.EXTERNAL,
            dependencies=["process_payment"],
            tags=["email", "confirmation", "confirm"],
            metadata={"system": "email"},
        ),
        TaskNode(
            id="itinerary",
            description="Create comprehensive travel itinerary",
            task_type=TaskType.PURE,
            dependencies=["book_flight", "book_hotel"],
            tags=["itinerary", "planning"],
        ),
        TaskNode(
            id="calendar_event",
            description="Add trip to calendar",
            task_type=TaskType.REVERSIBLE,
            dependencies=["itinerary"],
            tags=["calendar"],
            metadata={"system": "calendar"},
        ),
    ]

    graph = TaskGraph()
    graph.add_tasks(tasks)
    return graph


# ── Pre-built scenario configs ───────────────────────────────────────────

DEMO_SCENARIOS: dict[str, dict] = {
    "normal_interrupt": {
        "name": "Normal Interrupt — Do not book",
        "description": (
            "User says 'Do not book anything' while searches are running. "
            "SENTINEL-X should preserve search results and invalidate booking tasks."
        ),
        "graph_builder": "standard",
        "interrupt_text": "Do not book anything. I am only researching.",
        "interrupt_after_tasks": ["search_flights", "search_hotel"],
        "running_at_interrupt": ["compare_flights", "compare_hotel"],
    },
    "late_interrupt": {
        "name": "Late Interrupt — Booking already sent",
        "description": (
            "User says 'Stop the booking' AFTER the flight booking request "
            "has been sent and becomes COMMITTED. SENTINEL-X must verify "
            "external state and not falsely report cancellation."
        ),
        "graph_builder": "standard",
        "interrupt_text": "Stop the booking.",
        "interrupt_after_tasks": [
            "search_flights", "search_hotel",
            "compare_flights", "compare_hotel",
        ],
        "running_at_interrupt": ["book_flight"],
        "committed_effects": ["book_flight"],
    },
    "change_destination": {
        "name": "Change Destination — Chennai to Mumbai",
        "description": (
            "User changes destination mid-search. Destination-dependent "
            "branches must be invalidated and replanned."
        ),
        "graph_builder": "standard",
        "interrupt_text": "Change the destination to Mumbai.",
        "interrupt_after_tasks": [],
        "running_at_interrupt": ["search_flights", "search_hotel"],
    },
    "cancel_everything": {
        "name": "Global Cancellation",
        "description": "User cancels everything. All tasks invalidated.",
        "graph_builder": "standard",
        "interrupt_text": "Cancel everything.",
        "interrupt_after_tasks": ["search_flights"],
        "running_at_interrupt": ["search_hotel"],
    },
    "non_impacting": {
        "name": "Non-impacting Event",
        "description": "User says something irrelevant. No plan change.",
        "graph_builder": "standard",
        "interrupt_text": "Okay, continue.",
        "interrupt_after_tasks": ["search_flights"],
        "running_at_interrupt": ["compare_flights"],
    },
}
