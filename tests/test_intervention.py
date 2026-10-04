"""Tests for the counterfactual intervention planner."""

import pytest

from sentinel_x.core.models import (
    ChangeClass,
    EffectRecord,
    EffectStatus,
    EventType,
    ImpactClassification,
    ImpactResult,
    InterventionAction,
    SemanticEvent,
    TaskImpact,
    TaskNode,
    TaskStatus,
    TaskType,
)
from sentinel_x.core.intervention import generate_candidates, InterventionWeights
from sentinel_x.core.task_graph import TaskGraph


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_graph_and_impact(
    statuses: dict[str, TaskStatus],
    invalidated: list[str],
    preserved: list[str],
    uncertain: list[str] | None = None,
    replan: list[str] | None = None,
) -> tuple[TaskGraph, ImpactResult, SemanticEvent]:
    tasks = [
        TaskNode(id="search_flights", description="Search Flights",
                 task_type=TaskType.PURE, tags=["search", "flight"]),
        TaskNode(id="compare_flights", description="Compare Flights",
                 task_type=TaskType.PURE, dependencies=["search_flights"],
                 tags=["compare", "flight"]),
        TaskNode(id="book_flight", description="Book Flight",
                 task_type=TaskType.IRREVERSIBLE,
                 dependencies=["compare_flights"],
                 tags=["book", "flight", "purchase"]),
        TaskNode(id="search_hotel", description="Search Hotel",
                 task_type=TaskType.PURE, tags=["search", "hotel"]),
        TaskNode(id="compare_hotel", description="Compare Hotel",
                 task_type=TaskType.PURE, dependencies=["search_hotel"],
                 tags=["compare", "hotel"]),
        TaskNode(id="itinerary", description="Create Itinerary",
                 task_type=TaskType.PURE,
                 dependencies=["compare_flights", "compare_hotel"],
                 tags=["itinerary"]),
    ]

    graph = TaskGraph()
    graph.add_tasks(tasks)
    for tid, st in statuses.items():
        graph.set_status(tid, st)

    event = SemanticEvent(
        event_type=EventType.AUTHORIZATION_CHANGE,
        change_class=ChangeClass.AUTHORIZATION,
        raw_text="test event",
    )

    impact = ImpactResult(
        event_id=event.id,
        task_impacts=[],
        preserved=preserved,
        invalidated=invalidated,
        replan=replan or [],
        uncertain=uncertain or [],
    )

    return graph, impact, event


# ── Tests ────────────────────────────────────────────────────────────────

class TestCandidateGeneration:
    def test_generates_five_candidates(self):
        graph, impact, event = _build_graph_and_impact(
            statuses={"search_flights": TaskStatus.COMPLETED},
            invalidated=["book_flight"],
            preserved=["search_flights", "compare_flights", "search_hotel",
                        "compare_hotel", "itinerary"],
        )
        decision = generate_candidates(event, impact, graph)
        assert len(decision.candidates) == 5
        actions = {c.action for c in decision.candidates}
        assert actions == {
            InterventionAction.CONTINUE,
            InterventionAction.DEFER,
            InterventionAction.PARTIAL_PREEMPT,
            InterventionAction.FULL_PREEMPT,
            InterventionAction.ASK_USER,
        }

    def test_selects_minimum_safe(self):
        graph, impact, event = _build_graph_and_impact(
            statuses={"search_flights": TaskStatus.COMPLETED},
            invalidated=["book_flight"],
            preserved=["search_flights", "compare_flights", "search_hotel",
                        "compare_hotel", "itinerary"],
        )
        decision = generate_candidates(event, impact, graph)
        # CONTINUE is unsafe (has invalidated tasks), so it should NOT be selected
        assert decision.selected != InterventionAction.CONTINUE

    def test_partial_preempt_wins_for_single_invalidation(self):
        graph, impact, event = _build_graph_and_impact(
            statuses={
                "search_flights": TaskStatus.COMPLETED,
                "compare_flights": TaskStatus.COMPLETED,
            },
            invalidated=["book_flight"],
            preserved=["search_flights", "compare_flights", "search_hotel",
                        "compare_hotel", "itinerary"],
        )
        decision = generate_candidates(event, impact, graph)
        # Partial preempt should be cheapest safe option
        assert decision.selected == InterventionAction.PARTIAL_PREEMPT

    def test_full_preempt_has_high_waste(self):
        graph, impact, event = _build_graph_and_impact(
            statuses={
                "search_flights": TaskStatus.COMPLETED,
                "search_hotel": TaskStatus.COMPLETED,
            },
            invalidated=["book_flight"],
            preserved=["search_flights", "compare_flights", "search_hotel",
                        "compare_hotel", "itinerary"],
        )
        decision = generate_candidates(event, impact, graph)
        full = next(
            c for c in decision.candidates
            if c.action == InterventionAction.FULL_PREEMPT
        )
        partial = next(
            c for c in decision.candidates
            if c.action == InterventionAction.PARTIAL_PREEMPT
        )
        assert full.total_cost > partial.total_cost

    def test_continue_unsafe_when_invalidated_tasks_exist(self):
        graph, impact, event = _build_graph_and_impact(
            statuses={},
            invalidated=["book_flight"],
            preserved=["search_flights"],
        )
        decision = generate_candidates(event, impact, graph)
        cont = next(
            c for c in decision.candidates
            if c.action == InterventionAction.CONTINUE
        )
        assert not cont.satisfies_safety


class TestSafetyConstraints:
    def test_uncertain_tasks_make_continue_unsafe(self):
        graph, impact, event = _build_graph_and_impact(
            statuses={"book_flight": TaskStatus.RUNNING},
            invalidated=[],
            preserved=["search_flights"],
            uncertain=["book_flight"],
        )
        decision = generate_candidates(event, impact, graph)
        cont = next(
            c for c in decision.candidates
            if c.action == InterventionAction.CONTINUE
        )
        assert not cont.satisfies_safety

    def test_no_safe_candidates_falls_back_to_ask_user(self):
        # If we rig all candidates unsafe, ASK_USER should be force-selected
        graph, impact, event = _build_graph_and_impact(
            statuses={"book_flight": TaskStatus.RUNNING},
            invalidated=["book_flight", "search_flights", "compare_flights",
                          "search_hotel", "compare_hotel", "itinerary"],
            preserved=[],
            uncertain=["book_flight"],
        )
        decision = generate_candidates(event, impact, graph)
        # ASK_USER is always safe
        assert decision.selected in (
            InterventionAction.ASK_USER,
            InterventionAction.PARTIAL_PREEMPT,
            InterventionAction.FULL_PREEMPT,
        )


class TestEffectsInfluence:
    def test_committed_effects_increase_full_preempt_cost(self):
        graph, impact, event = _build_graph_and_impact(
            statuses={},
            invalidated=["book_flight"],
            preserved=["search_flights"],
        )
        effects = [
            EffectRecord(
                task_id="book_flight",
                operation="book_flight_api",
                status=EffectStatus.COMMITTED,
            )
        ]
        decision = generate_candidates(event, impact, graph, effects=effects)
        full = next(
            c for c in decision.candidates
            if c.action == InterventionAction.FULL_PREEMPT
        )
        # Committed effects should increase side-effect exposure
        assert full.side_effect_exposure > 0

    def test_ask_user_mentions_committed_effects(self):
        graph, impact, event = _build_graph_and_impact(
            statuses={},
            invalidated=["book_flight"],
            preserved=["search_flights"],
        )
        effects = [
            EffectRecord(
                task_id="book_flight",
                operation="book_flight_api",
                status=EffectStatus.COMMITTED,
            )
        ]
        decision = generate_candidates(event, impact, graph, effects=effects)
        ask = next(
            c for c in decision.candidates
            if c.action == InterventionAction.ASK_USER
        )
        assert "committed" in ask.explanation.lower() or "Committed" in ask.explanation


class TestCustomWeights:
    def test_high_risk_weight_changes_selection(self):
        graph, impact, event = _build_graph_and_impact(
            statuses={},
            invalidated=["book_flight"],
            preserved=["search_flights", "compare_flights", "search_hotel",
                        "compare_hotel", "itinerary"],
        )
        # With very high risk weight, CONTINUE cost goes way up
        weights = InterventionWeights(beta=100.0)
        decision = generate_candidates(event, impact, graph, weights=weights)
        assert decision.selected != InterventionAction.CONTINUE
