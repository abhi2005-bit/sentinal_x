"""Tests for the semantic impact engine — 10+ deterministic scenarios."""

import pytest

from sentinel_x.core.models import (
    ChangeClass,
    EventType,
    ImpactClassification,
    SemanticEvent,
    TaskNode,
    TaskStatus,
    TaskType,
)
from sentinel_x.core.impact_engine import analyze_impact
from sentinel_x.core.task_graph import TaskGraph


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_travel_graph(
    statuses: dict[str, TaskStatus] | None = None,
) -> TaskGraph:
    """
    Standard travel graph.  Optionally set per-task statuses.
    """
    tasks = [
        TaskNode(id="search_flights", description="Search Flights",
                 task_type=TaskType.PURE, tags=["search", "flight", "destination"]),
        TaskNode(id="search_hotel", description="Search Hotel",
                 task_type=TaskType.PURE, tags=["search", "hotel", "destination"]),
        TaskNode(id="compare_flights", description="Compare Flights",
                 task_type=TaskType.PURE, dependencies=["search_flights"],
                 tags=["compare", "flight"]),
        TaskNode(id="compare_hotel", description="Compare Hotel",
                 task_type=TaskType.PURE, dependencies=["search_hotel"],
                 tags=["compare", "hotel"]),
        TaskNode(id="book_flight", description="Book Flight",
                 task_type=TaskType.IRREVERSIBLE,
                 dependencies=["compare_flights"],
                 tags=["book", "flight", "purchase"]),
        TaskNode(id="itinerary", description="Create Itinerary",
                 task_type=TaskType.PURE,
                 dependencies=["compare_flights", "compare_hotel"],
                 tags=["itinerary"]),
    ]

    graph = TaskGraph()
    graph.add_tasks(tasks)

    if statuses:
        for tid, status in statuses.items():
            graph.set_status(tid, status)
    return graph


def _get_classification(result, task_id) -> ImpactClassification:
    for ti in result.task_impacts:
        if ti.task_id == task_id:
            return ti.classification
    raise KeyError(f"No impact for {task_id}")


# ── Scenario 1: "Do not book anything" ──────────────────────────────────

class TestAuthorizationChange:
    def test_booking_invalidated(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.COMPLETED,
            "search_hotel": TaskStatus.COMPLETED,
            "compare_flights": TaskStatus.RUNNING,
            "compare_hotel": TaskStatus.RUNNING,
        })
        event = SemanticEvent(
            event_type=EventType.AUTHORIZATION_CHANGE,
            change_class=ChangeClass.AUTHORIZATION,
            authorization_changes=["booking_removed"],
            affected_task_hints=["book", "purchase"],
            replan_required=True,
            raw_text="Do not book anything.",
        )
        result = analyze_impact(event, graph)

        assert _get_classification(result, "book_flight") == ImpactClassification.INVALIDATED
        assert "book_flight" in result.invalidated

    def test_search_preserved(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.COMPLETED,
            "search_hotel": TaskStatus.COMPLETED,
        })
        event = SemanticEvent(
            event_type=EventType.AUTHORIZATION_CHANGE,
            change_class=ChangeClass.AUTHORIZATION,
            authorization_changes=["booking_removed"],
            affected_task_hints=["book", "purchase"],
            replan_required=True,
            raw_text="Do not book anything.",
        )
        result = analyze_impact(event, graph)

        assert _get_classification(result, "search_flights") == ImpactClassification.PRESERVED
        assert _get_classification(result, "search_hotel") == ImpactClassification.PRESERVED


# ── Scenario 2: "Change destination to Mumbai" ──────────────────────────

class TestEntityChange:
    def test_destination_tasks_affected(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.COMPLETED,
            "search_hotel": TaskStatus.COMPLETED,
        })
        event = SemanticEvent(
            event_type=EventType.ENTITY_CHANGE,
            change_class=ChangeClass.ENTITY,
            entity_changes={"destination": "Mumbai"},
            affected_task_hints=["destination", "search", "compare"],
            replan_required=True,
            raw_text="Change destination to Mumbai.",
        )
        result = analyze_impact(event, graph)

        # search tasks are directly affected (tagged "destination")
        assert _get_classification(result, "search_flights") == ImpactClassification.INVALIDATED
        assert _get_classification(result, "search_hotel") == ImpactClassification.INVALIDATED

    def test_downstream_tasks_replan(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.COMPLETED,
            "search_hotel": TaskStatus.COMPLETED,
        })
        event = SemanticEvent(
            event_type=EventType.ENTITY_CHANGE,
            change_class=ChangeClass.ENTITY,
            entity_changes={"destination": "Mumbai"},
            affected_task_hints=["destination", "search", "compare"],
            replan_required=True,
            raw_text="Change destination to Mumbai.",
        )
        result = analyze_impact(event, graph)

        # Compare tasks are transitive dependents, should be REPLAN or INVALIDATED
        c_flights = _get_classification(result, "compare_flights")
        assert c_flights in (
            ImpactClassification.REPLAN,
            ImpactClassification.INVALIDATED,
        )


# ── Scenario 3: "Cancel everything" ─────────────────────────────────────

class TestGlobalCancellation:
    def test_all_invalidated(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.COMPLETED,
            "compare_flights": TaskStatus.RUNNING,
        })
        event = SemanticEvent(
            event_type=EventType.GLOBAL_CANCELLATION,
            change_class=ChangeClass.GLOBAL_CANCEL,
            replan_required=True,
            raw_text="Cancel everything.",
        )
        result = analyze_impact(event, graph)

        # All tasks should be invalidated (except running external/irreversible → uncertain)
        for ti in result.task_impacts:
            assert ti.classification in (
                ImpactClassification.INVALIDATED,
                ImpactClassification.UNCERTAIN,
            )

    def test_running_irreversible_is_uncertain(self):
        graph = _build_travel_graph({
            "book_flight": TaskStatus.RUNNING,
        })
        event = SemanticEvent(
            event_type=EventType.GLOBAL_CANCELLATION,
            change_class=ChangeClass.GLOBAL_CANCEL,
            replan_required=True,
            raw_text="Cancel everything.",
        )
        result = analyze_impact(event, graph)
        assert _get_classification(result, "book_flight") == ImpactClassification.UNCERTAIN


# ── Scenario 4: Non-impacting event ─────────────────────────────────────

class TestNonImpacting:
    def test_all_preserved(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.RUNNING,
            "search_hotel": TaskStatus.RUNNING,
        })
        event = SemanticEvent(
            event_type=EventType.NON_IMPACTING,
            change_class=ChangeClass.NON_IMPACTING,
            raw_text="Okay, continue.",
        )
        result = analyze_impact(event, graph)

        assert len(result.invalidated) == 0
        assert len(result.uncertain) == 0
        assert len(result.preserved) == 6


# ── Scenario 5: Interrupt during pure computation ───────────────────────

class TestInterruptPureComputation:
    def test_pure_running_invalidated(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.COMPLETED,
            "compare_flights": TaskStatus.RUNNING,
        })
        event = SemanticEvent(
            event_type=EventType.AUTHORIZATION_CHANGE,
            change_class=ChangeClass.AUTHORIZATION,
            affected_task_hints=["compare"],
            replan_required=True,
            raw_text="Stop comparing flights.",
        )
        result = analyze_impact(event, graph)
        assert _get_classification(result, "compare_flights") == ImpactClassification.INVALIDATED


# ── Scenario 6: Interrupt before irreversible action ────────────────────

class TestInterruptBeforeIrreversible:
    def test_pending_irreversible_invalidated(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.COMPLETED,
            "compare_flights": TaskStatus.COMPLETED,
            "book_flight": TaskStatus.PENDING,
        })
        event = SemanticEvent(
            event_type=EventType.AUTHORIZATION_CHANGE,
            change_class=ChangeClass.AUTHORIZATION,
            affected_task_hints=["book", "purchase"],
            replan_required=True,
            raw_text="Do not book.",
        )
        result = analyze_impact(event, graph)
        assert _get_classification(result, "book_flight") == ImpactClassification.INVALIDATED


# ── Scenario 7: Interrupt while irreversible is RUNNING ─────────────────

class TestInterruptDuringIrreversible:
    def test_running_irreversible_uncertain(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.COMPLETED,
            "compare_flights": TaskStatus.COMPLETED,
            "book_flight": TaskStatus.RUNNING,
        })
        event = SemanticEvent(
            event_type=EventType.AUTHORIZATION_CHANGE,
            change_class=ChangeClass.AUTHORIZATION,
            affected_task_hints=["book"],
            replan_required=True,
            raw_text="Stop the booking.",
        )
        result = analyze_impact(event, graph)
        assert _get_classification(result, "book_flight") == ImpactClassification.UNCERTAIN


# ── Scenario 8: Constraint change (date) ────────────────────────────────

class TestConstraintChange:
    def test_date_change_affects_search(self):
        graph = _build_travel_graph()
        # Add date tag to search tasks
        graph.get_task("search_flights").tags.append("date")
        graph.get_task("search_hotel").tags.append("date")

        event = SemanticEvent(
            event_type=EventType.CONSTRAINT_CHANGE,
            change_class=ChangeClass.CONSTRAINT,
            constraints_added=["date:tomorrow"],
            affected_task_hints=["date", "search"],
            replan_required=True,
            raw_text="Use tomorrow instead.",
        )
        result = analyze_impact(event, graph)

        assert _get_classification(result, "search_flights") == ImpactClassification.INVALIDATED
        assert _get_classification(result, "search_hotel") == ImpactClassification.INVALIDATED


# ── Scenario 9: Two unrelated branches — only one affected ──────────────

class TestPartialBranchImpact:
    def test_hotel_branch_preserved_when_flight_affected(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.COMPLETED,
            "search_hotel": TaskStatus.COMPLETED,
            "compare_flights": TaskStatus.COMPLETED,
            "compare_hotel": TaskStatus.COMPLETED,
        })
        event = SemanticEvent(
            event_type=EventType.AUTHORIZATION_CHANGE,
            change_class=ChangeClass.AUTHORIZATION,
            affected_task_hints=["book"],
            replan_required=True,
            raw_text="Do not book the flight.",
        )
        result = analyze_impact(event, graph)

        # Hotel branch should be preserved
        assert _get_classification(result, "search_hotel") == ImpactClassification.PRESERVED
        assert _get_classification(result, "compare_hotel") == ImpactClassification.PRESERVED
        # Flight booking invalidated
        assert _get_classification(result, "book_flight") == ImpactClassification.INVALIDATED


# ── Scenario 10: Goal change — research only ────────────────────────────

class TestGoalChange:
    def test_research_only(self):
        graph = _build_travel_graph({
            "search_flights": TaskStatus.COMPLETED,
            "search_hotel": TaskStatus.COMPLETED,
            "compare_flights": TaskStatus.RUNNING,
        })
        event = SemanticEvent(
            event_type=EventType.GOAL_CHANGE,
            change_class=ChangeClass.GOAL,
            goal_changes=["research_only"],
            authorization_changes=["booking_removed"],
            affected_task_hints=["book", "purchase", "confirm"],
            replan_required=True,
            raw_text="I only want research.",
        )
        result = analyze_impact(event, graph)

        # Booking invalidated
        assert _get_classification(result, "book_flight") == ImpactClassification.INVALIDATED
        # Research tasks preserved
        assert _get_classification(result, "search_flights") == ImpactClassification.PRESERVED
        assert _get_classification(result, "search_hotel") == ImpactClassification.PRESERVED
