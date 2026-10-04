"""Tests for recovery orchestration and state capsule creation."""

import pytest

from sentinel_x.core.models import (
    ChangeClass,
    EffectRecord,
    EffectStatus,
    EventType,
    ImpactClassification,
    ImpactResult,
    InterventionAction,
    InterventionDecision,
    SemanticEvent,
    TaskImpact,
    TaskNode,
    TaskStatus,
    TaskType,
)
from sentinel_x.core.recovery import execute_recovery
from sentinel_x.core.state_capsule import create_capsule
from sentinel_x.core.task_graph import TaskGraph


# ── Helpers ──────────────────────────────────────────────────────────────

def _setup(
    statuses: dict[str, TaskStatus],
    invalidated: list[str],
    preserved: list[str],
    uncertain: list[str] | None = None,
    replan: list[str] | None = None,
    selected_action: InterventionAction = InterventionAction.PARTIAL_PREEMPT,
    effects: list[EffectRecord] | None = None,
) -> tuple:
    tasks = [
        TaskNode(id="search_flights", description="Search Flights",
                 task_type=TaskType.PURE, tags=["search"]),
        TaskNode(id="compare_flights", description="Compare Flights",
                 task_type=TaskType.PURE, dependencies=["search_flights"],
                 tags=["compare"]),
        TaskNode(id="book_flight", description="Book Flight",
                 task_type=TaskType.IRREVERSIBLE,
                 dependencies=["compare_flights"],
                 tags=["book", "purchase"]),
        TaskNode(id="search_hotel", description="Search Hotel",
                 task_type=TaskType.PURE, tags=["search"]),
    ]

    graph = TaskGraph()
    graph.add_tasks(tasks)
    for tid, st in statuses.items():
        graph.set_status(tid, st)

    event = SemanticEvent(
        event_type=EventType.AUTHORIZATION_CHANGE,
        change_class=ChangeClass.AUTHORIZATION,
        raw_text="test",
    )
    impact = ImpactResult(
        event_id=event.id,
        preserved=preserved,
        invalidated=invalidated,
        replan=replan or [],
        uncertain=uncertain or [],
    )
    decision = InterventionDecision(
        event_id=event.id,
        selected=selected_action,
    )

    return graph, event, impact, decision, effects or []


# ── Tests ────────────────────────────────────────────────────────────────

class TestPartialPreemptRecovery:
    def test_invalidated_tasks_cancelled(self):
        graph, event, impact, decision, effects = _setup(
            statuses={
                "search_flights": TaskStatus.COMPLETED,
                "compare_flights": TaskStatus.COMPLETED,
                "book_flight": TaskStatus.PENDING,
            },
            invalidated=["book_flight"],
            preserved=["search_flights", "compare_flights", "search_hotel"],
            selected_action=InterventionAction.PARTIAL_PREEMPT,
        )
        result = execute_recovery("sess1", event, impact, decision, graph, effects)

        assert "book_flight" in result.preempted_tasks
        assert graph.get_status("book_flight") == TaskStatus.CANCELLED

    def test_preserved_tasks_remain(self):
        graph, event, impact, decision, effects = _setup(
            statuses={
                "search_flights": TaskStatus.COMPLETED,
                "compare_flights": TaskStatus.COMPLETED,
                "book_flight": TaskStatus.PENDING,
            },
            invalidated=["book_flight"],
            preserved=["search_flights", "compare_flights", "search_hotel"],
            selected_action=InterventionAction.PARTIAL_PREEMPT,
        )
        result = execute_recovery("sess1", event, impact, decision, graph, effects)

        assert "search_flights" in result.preserved_tasks
        assert graph.get_status("search_flights") == TaskStatus.PRESERVED

    def test_capsule_created(self):
        graph, event, impact, decision, effects = _setup(
            statuses={
                "search_flights": TaskStatus.COMPLETED,
                "book_flight": TaskStatus.PENDING,
            },
            invalidated=["book_flight"],
            preserved=["search_flights", "compare_flights", "search_hotel"],
            selected_action=InterventionAction.PARTIAL_PREEMPT,
        )
        result = execute_recovery("sess1", event, impact, decision, graph, effects)

        assert result.capsule.session_id == "sess1"
        assert result.new_plan_revision == 1


class TestFullPreemptRecovery:
    def test_all_tasks_cancelled(self):
        graph, event, impact, decision, effects = _setup(
            statuses={
                "search_flights": TaskStatus.COMPLETED,
                "compare_flights": TaskStatus.RUNNING,
                "book_flight": TaskStatus.PENDING,
                "search_hotel": TaskStatus.PENDING,
            },
            invalidated=["book_flight"],
            preserved=["search_flights"],
            selected_action=InterventionAction.FULL_PREEMPT,
        )
        result = execute_recovery("sess1", event, impact, decision, graph, effects)

        assert len(result.preempted_tasks) == 4  # all tasks

    def test_effects_flagged_for_verification(self):
        effects = [
            EffectRecord(
                task_id="book_flight",
                operation="book_api",
                status=EffectStatus.COMMITTED,
            ),
        ]
        graph, event, impact, decision, _ = _setup(
            statuses={"book_flight": TaskStatus.RUNNING},
            invalidated=["book_flight"],
            preserved=[],
            selected_action=InterventionAction.FULL_PREEMPT,
        )
        result = execute_recovery("sess1", event, impact, decision, graph, effects)

        assert len(result.effects_to_verify) > 0


class TestContinueRecovery:
    def test_nothing_preempted(self):
        graph, event, impact, decision, effects = _setup(
            statuses={"search_flights": TaskStatus.RUNNING},
            invalidated=[],
            preserved=["search_flights", "compare_flights",
                        "book_flight", "search_hotel"],
            selected_action=InterventionAction.CONTINUE,
        )
        result = execute_recovery("sess1", event, impact, decision, graph, effects)

        assert len(result.preempted_tasks) == 0


class TestDeferRecovery:
    def test_pending_invalidated_tasks_marked(self):
        graph, event, impact, decision, effects = _setup(
            statuses={
                "search_flights": TaskStatus.COMPLETED,
                "book_flight": TaskStatus.PENDING,
            },
            invalidated=["book_flight"],
            preserved=["search_flights", "compare_flights", "search_hotel"],
            selected_action=InterventionAction.DEFER,
        )
        result = execute_recovery("sess1", event, impact, decision, graph, effects)

        assert graph.get_status("book_flight") == TaskStatus.INVALIDATED


class TestAskUserRecovery:
    def test_running_affected_tasks_paused(self):
        graph, event, impact, decision, effects = _setup(
            statuses={"book_flight": TaskStatus.RUNNING},
            invalidated=["book_flight"],
            preserved=["search_flights", "search_hotel"],
            selected_action=InterventionAction.ASK_USER,
        )
        result = execute_recovery("sess1", event, impact, decision, graph, effects)

        assert graph.get_status("book_flight") == TaskStatus.CANCELLED
        assert "book_flight" in result.preempted_tasks


class TestStateCapsule:
    def test_capsule_includes_pending_effects(self):
        graph, event, impact, _, _ = _setup(
            statuses={"search_flights": TaskStatus.COMPLETED},
            invalidated=["book_flight"],
            preserved=["search_flights"],
        )
        effects = [
            EffectRecord(
                task_id="book_flight",
                operation="book",
                status=EffectStatus.PENDING,
            ),
        ]
        capsule = create_capsule("sess1", 1, graph, impact, effects)

        assert len(capsule.pending_effects) == 1
        assert len(capsule.committed_effects) == 0

    def test_capsule_finds_next_safe_task(self):
        graph, event, impact, _, _ = _setup(
            statuses={
                "search_flights": TaskStatus.COMPLETED,
                "compare_flights": TaskStatus.COMPLETED,
            },
            invalidated=["book_flight"],
            preserved=["search_flights", "compare_flights", "search_hotel"],
        )
        capsule = create_capsule("sess1", 1, graph, impact)
        # search_hotel is PENDING with no deps → should be next safe
        assert capsule.next_safe_task == "search_hotel"

    def test_capsule_serialization(self):
        graph, event, impact, _, _ = _setup(
            statuses={"search_flights": TaskStatus.COMPLETED},
            invalidated=[],
            preserved=["search_flights"],
        )
        capsule = create_capsule("sess1", 1, graph, impact)
        data = capsule.model_dump(mode="json")
        assert data["session_id"] == "sess1"
        assert isinstance(data["completed"], list)
