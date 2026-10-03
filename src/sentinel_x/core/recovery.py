"""
SENTINEL-X — Recovery Orchestration.

Applies an :class:`InterventionDecision` to the task graph and
effect ledger, then produces a :class:`StateCapsule` for resumption.

This module coordinates preemption, effect verification, and replanning
into a single recovery pass.
"""

from __future__ import annotations

from sentinel_x.core.models import (
    EffectRecord,
    EffectStatus,
    ImpactResult,
    InterventionAction,
    InterventionDecision,
    SemanticEvent,
    StateCapsule,
    TaskStatus,
)
from sentinel_x.core.state_capsule import create_capsule
from sentinel_x.core.task_graph import TaskGraph


class RecoveryResult:
    """Outcome of a recovery pass."""

    def __init__(
        self,
        capsule: StateCapsule,
        preempted_tasks: list[str],
        preserved_tasks: list[str],
        effects_to_verify: list[str],
        new_plan_revision: int,
    ) -> None:
        self.capsule = capsule
        self.preempted_tasks = preempted_tasks
        self.preserved_tasks = preserved_tasks
        self.effects_to_verify = effects_to_verify
        self.new_plan_revision = new_plan_revision


def execute_recovery(
    session_id: str,
    event: SemanticEvent,
    impact: ImpactResult,
    decision: InterventionDecision,
    graph: TaskGraph,
    effects: list[EffectRecord] | None = None,
    current_revision: int = 0,
    goal_snapshot: dict | None = None,
) -> RecoveryResult:
    """
    Apply the selected intervention to the graph and effects,
    then return a :class:`RecoveryResult` with the capsule.
    """
    effects = effects or []
    preempted: list[str] = []
    preserved: list[str] = []
    effects_to_verify: list[str] = []
    new_revision = current_revision + 1

    action = decision.selected

    if action == InterventionAction.CONTINUE:
        # Nothing to preempt — preserve everything
        preserved = [t.id for t in graph.all_tasks()]

    elif action == InterventionAction.DEFER:
        # Let running tasks finish, but mark invalidated as pending cancel
        for tid in impact.invalidated:
            task = graph.get_task(tid)
            if task and task.status == TaskStatus.PENDING:
                graph.set_status(tid, TaskStatus.INVALIDATED)
                preempted.append(tid)
        preserved = impact.preserved[:]

    elif action == InterventionAction.PARTIAL_PREEMPT:
        # Stop invalidated tasks, preserve the rest
        for tid in impact.invalidated:
            task = graph.get_task(tid)
            if task and task.status in (
                TaskStatus.PENDING, TaskStatus.RUNNING
            ):
                graph.set_status(tid, TaskStatus.CANCELLED)
                preempted.append(tid)
            elif task and task.status == TaskStatus.COMPLETED:
                graph.set_status(tid, TaskStatus.INVALIDATED)
                preempted.append(tid)

        # Mark uncertain tasks as needing verification
        for tid in impact.uncertain:
            task = graph.get_task(tid)
            if task:
                # Find associated effects
                task_effects = [e for e in effects if e.task_id == tid]
                for eff in task_effects:
                    if eff.status in (
                        EffectStatus.PENDING,
                        EffectStatus.COMMITTED,
                        EffectStatus.UNKNOWN,
                    ):
                        effects_to_verify.append(eff.effect_id)

        # Mark replan tasks
        for tid in impact.replan:
            task = graph.get_task(tid)
            if task and task.status == TaskStatus.PENDING:
                # Keep pending — they'll be re-evaluated
                pass

        # Preserve unaffected tasks
        for tid in impact.preserved:
            task = graph.get_task(tid)
            if task and task.status == TaskStatus.COMPLETED:
                graph.set_status(tid, TaskStatus.PRESERVED)
                preserved.append(tid)
            elif task:
                preserved.append(tid)

    elif action == InterventionAction.FULL_PREEMPT:
        # Stop everything
        for task in graph.all_tasks():
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                graph.set_status(task.id, TaskStatus.CANCELLED)
                preempted.append(task.id)
            elif task.status == TaskStatus.COMPLETED:
                graph.set_status(task.id, TaskStatus.INVALIDATED)
                preempted.append(task.id)

        # All effects need verification
        for eff in effects:
            if eff.status in (
                EffectStatus.PENDING,
                EffectStatus.COMMITTED,
                EffectStatus.UNKNOWN,
            ):
                effects_to_verify.append(eff.effect_id)

    elif action == InterventionAction.ASK_USER:
        # Pause running tasks but don't cancel yet
        for tid in impact.invalidated + impact.uncertain:
            task = graph.get_task(tid)
            if task and task.status == TaskStatus.RUNNING:
                # Mark as cancelled for now; user may restore
                graph.set_status(tid, TaskStatus.CANCELLED)
                preempted.append(tid)

        preserved = impact.preserved[:]
        for eff in effects:
            if eff.status in (EffectStatus.PENDING, EffectStatus.UNKNOWN):
                effects_to_verify.append(eff.effect_id)

    # Build the capsule
    capsule = create_capsule(
        session_id=session_id,
        plan_revision=new_revision,
        graph=graph,
        impact=impact,
        effects=effects,
        goal_snapshot=goal_snapshot,
    )

    return RecoveryResult(
        capsule=capsule,
        preempted_tasks=preempted,
        preserved_tasks=preserved,
        effects_to_verify=effects_to_verify,
        new_plan_revision=new_revision,
    )
