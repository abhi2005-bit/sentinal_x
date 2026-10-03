"""
SENTINEL-X — Semantic Impact Engine.

Given a :class:`SemanticEvent` and a :class:`TaskGraph`, determine
which tasks are PRESERVED, INVALIDATED, need REPLAN, or are UNCERTAIN.

The engine uses deterministic graph traversal (not LLM calls) to
classify every node.  This is the safety-critical decision path.
"""

from __future__ import annotations

from sentinel_x.core.models import (
    ChangeClass,
    EventType,
    ImpactClassification,
    ImpactResult,
    SemanticEvent,
    TaskImpact,
    TaskNode,
    TaskStatus,
    TaskType,
)
from sentinel_x.core.task_graph import TaskGraph


def analyze_impact(
    event: SemanticEvent,
    graph: TaskGraph,
    plan_revision: int = 0,
) -> ImpactResult:
    """
    Core impact-resolution algorithm.

    1. Identify *directly* affected tasks via hints, tags, and entity matches.
    2. Propagate invalidation transitively to downstream dependents.
    3. Classify every task as PRESERVED / INVALIDATED / REPLAN / UNCERTAIN.
    """

    # Short-circuit: non-impacting events preserve everything
    if event.change_class == ChangeClass.NON_IMPACTING:
        return _preserve_all(event, graph, plan_revision)

    # Short-circuit: global cancellation invalidates everything
    if event.change_class == ChangeClass.GLOBAL_CANCEL:
        return _invalidate_all(event, graph, plan_revision)

    # ── Step 1: find directly affected task IDs ──────────────────────
    directly_affected = _find_directly_affected(event, graph)

    # ── Step 2: propagate to transitive dependents ───────────────────
    all_affected: set[str] = set(directly_affected)
    for tid in directly_affected:
        all_affected.update(graph.transitive_dependents(tid))

    # ── Step 3: classify each task ───────────────────────────────────
    task_impacts: list[TaskImpact] = []
    preserved: list[str] = []
    invalidated: list[str] = []
    replan: list[str] = []
    uncertain: list[str] = []

    for task in graph.all_tasks():
        if task.id in all_affected:
            classification, reason = _classify_affected_task(
                task, task.id in directly_affected, event
            )
        else:
            classification = ImpactClassification.PRESERVED
            reason = "Not in the affected region"

        task_impacts.append(
            TaskImpact(
                task_id=task.id,
                classification=classification,
                reason=reason,
            )
        )

        # Bucket for convenience
        bucket = {
            ImpactClassification.PRESERVED: preserved,
            ImpactClassification.INVALIDATED: invalidated,
            ImpactClassification.REPLAN: replan,
            ImpactClassification.UNCERTAIN: uncertain,
        }[classification]
        bucket.append(task.id)

    return ImpactResult(
        event_id=event.id,
        plan_revision=plan_revision,
        task_impacts=task_impacts,
        preserved=preserved,
        invalidated=invalidated,
        replan=replan,
        uncertain=uncertain,
    )


# ── Private helpers ──────────────────────────────────────────────────────


def _find_directly_affected(
    event: SemanticEvent, graph: TaskGraph
) -> list[str]:
    """
    Match event hints/entities against task descriptions, tags, and IDs.
    """
    affected: list[str] = []
    hints = [h.lower() for h in event.affected_task_hints]
    entity_values = [v.lower() for v in event.entity_changes.values()]

    for task in graph.all_tasks():
        desc_lower = task.description.lower()
        id_lower = task.id.lower()
        tag_set = {t.lower() for t in task.tags}

        # Match via affected_task_hints
        if any(h in desc_lower or h in id_lower or h in tag_set for h in hints):
            affected.append(task.id)
            continue

        # Match via entity changes (e.g. destination name in description)
        if entity_values and any(ev in desc_lower for ev in entity_values):
            affected.append(task.id)
            continue

        # Entity change affects tasks tagged with the changed entity key
        if event.entity_changes:
            entity_keys = {k.lower() for k in event.entity_changes.keys()}
            if entity_keys & tag_set:
                affected.append(task.id)
                continue

    return affected


def _classify_affected_task(
    task: TaskNode,
    is_direct: bool,
    event: SemanticEvent,
) -> tuple[ImpactClassification, str]:
    """
    Decide whether an affected task is INVALIDATED, needs REPLAN,
    or is UNCERTAIN.
    """

    # Already completed tasks that are directly affected → INVALIDATED
    # unless they are PURE and the result is still usable.
    if task.status in (TaskStatus.COMPLETED, TaskStatus.PRESERVED):
        if is_direct:
            if task.task_type == TaskType.PURE:
                # Pure computation directly targeted → invalidated
                return (
                    ImpactClassification.INVALIDATED,
                    "Completed pure task directly affected by event",
                )
            return (
                ImpactClassification.INVALIDATED,
                "Completed task directly affected by event",
            )
        # Transitive dependent of an affected task, already completed
        return (
            ImpactClassification.REPLAN,
            "Downstream of an affected task; may need replanning",
        )

    # RUNNING tasks
    if task.status == TaskStatus.RUNNING:
        if is_direct:
            if task.task_type in (TaskType.IRREVERSIBLE, TaskType.EXTERNAL):
                return (
                    ImpactClassification.UNCERTAIN,
                    "Running irreversible/external task directly affected — "
                    "verify external state before deciding",
                )
            return (
                ImpactClassification.INVALIDATED,
                "Running task directly affected by event",
            )
        return (
            ImpactClassification.REPLAN,
            "Running downstream of affected task",
        )

    # PENDING tasks
    if task.status == TaskStatus.PENDING:
        if is_direct:
            return (
                ImpactClassification.INVALIDATED,
                "Pending task directly affected by event",
            )
        return (
            ImpactClassification.REPLAN,
            "Pending downstream of an affected task",
        )

    # Already cancelled/invalidated/failed → preserve classification
    return (
        ImpactClassification.PRESERVED,
        "Task already in terminal state",
    )


def _preserve_all(
    event: SemanticEvent,
    graph: TaskGraph,
    plan_revision: int,
) -> ImpactResult:
    """Shortcut for non-impacting events."""
    tasks = graph.all_tasks()
    return ImpactResult(
        event_id=event.id,
        plan_revision=plan_revision,
        task_impacts=[
            TaskImpact(
                task_id=t.id,
                classification=ImpactClassification.PRESERVED,
                reason="Non-impacting event",
            )
            for t in tasks
        ],
        preserved=[t.id for t in tasks],
    )


def _invalidate_all(
    event: SemanticEvent,
    graph: TaskGraph,
    plan_revision: int,
) -> ImpactResult:
    """Shortcut for global cancellation events."""
    tasks = graph.all_tasks()
    impacts: list[TaskImpact] = []
    invalidated: list[str] = []
    uncertain: list[str] = []

    for t in tasks:
        if (
            t.status == TaskStatus.RUNNING
            and t.task_type in (TaskType.IRREVERSIBLE, TaskType.EXTERNAL)
        ):
            impacts.append(
                TaskImpact(
                    task_id=t.id,
                    classification=ImpactClassification.UNCERTAIN,
                    reason="Running external/irreversible task during global cancel — verify state",
                )
            )
            uncertain.append(t.id)
        else:
            impacts.append(
                TaskImpact(
                    task_id=t.id,
                    classification=ImpactClassification.INVALIDATED,
                    reason="Global cancellation",
                )
            )
            invalidated.append(t.id)

    return ImpactResult(
        event_id=event.id,
        plan_revision=plan_revision,
        task_impacts=impacts,
        invalidated=invalidated,
        uncertain=uncertain,
    )
