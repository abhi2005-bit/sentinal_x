"""
SENTINEL-X — State Capsule.

Creates resume-safe snapshots of execution state after an intervention
decision has been applied.  Used by the recovery module to restore
execution from a known-good point.
"""

from __future__ import annotations

from sentinel_x.core.models import (
    EffectRecord,
    EffectStatus,
    ImpactResult,
    StateCapsule,
    TaskStatus,
)
from sentinel_x.core.task_graph import TaskGraph


def create_capsule(
    session_id: str,
    plan_revision: int,
    graph: TaskGraph,
    impact: ImpactResult,
    effects: list[EffectRecord] | None = None,
    goal_snapshot: dict | None = None,
) -> StateCapsule:
    """
    Build a :class:`StateCapsule` from the current graph state,
    impact result, and effect records.

    The capsule captures everything needed to resume safely:
    - Which tasks are done and preserved
    - Which are invalidated or uncertain
    - Which effects are pending or committed
    - What the next safe starting task is
    """
    effects = effects or []

    completed = graph.tasks_by_status(TaskStatus.COMPLETED)
    running = graph.tasks_by_status(TaskStatus.RUNNING)
    preserved_by_status = graph.tasks_by_status(TaskStatus.PRESERVED)

    # Merge graph status + impact analysis
    preserved = list(set(preserved_by_status) | set(impact.preserved))
    invalidated = list(set(impact.invalidated))
    uncertain = list(set(impact.uncertain))

    pending_effects = [
        e.effect_id for e in effects if e.status == EffectStatus.PENDING
    ]
    committed_effects = [
        e.effect_id for e in effects if e.status == EffectStatus.COMMITTED
    ]

    # Find the next safe task to execute: first runnable task
    # after applying the intervention
    next_safe = _find_next_safe_task(graph, invalidated, uncertain)

    return StateCapsule(
        session_id=session_id,
        plan_revision=plan_revision,
        completed=completed,
        running=running,
        preserved=preserved,
        invalidated=invalidated,
        uncertain=uncertain,
        pending_effects=pending_effects,
        committed_effects=committed_effects,
        next_safe_task=next_safe,
        goal_snapshot=goal_snapshot or {},
    )


def _find_next_safe_task(
    graph: TaskGraph,
    invalidated: list[str],
    uncertain: list[str],
) -> str | None:
    """
    Find the first PENDING task whose dependencies are all satisfied
    and that is not in the invalidated or uncertain set.
    """
    blocked = set(invalidated) | set(uncertain)
    for tid in graph.topological_order():
        if tid in blocked:
            continue
        task = graph.get_task(tid)
        if task is None:
            continue
        if task.status != TaskStatus.PENDING:
            continue
        # Check all dependencies are in a safe terminal state
        deps = graph.direct_dependencies(tid)
        all_deps_ok = all(
            (graph.get_task(d) is not None
             and graph.get_task(d).status
             in (TaskStatus.COMPLETED, TaskStatus.PRESERVED)
             and d not in blocked)
            for d in deps
        )
        if all_deps_ok:
            return tid
    return None
