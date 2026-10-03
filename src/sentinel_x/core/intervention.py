"""
SENTINEL-X — Counterfactual Intervention Planner.

Evaluates all five intervention candidates against the impact result
and selects the minimum-safe intervention.

Cost model (from the doc):
    C(I) = α·W + β·R + γ·L + δ·S + ε·U

    W = wasted work
    R = estimated risk
    L = recovery latency
    S = side-effect exposure
    U = unnecessary disruption
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sentinel_x.core.models import (
    EffectRecord,
    EffectStatus,
    ImpactClassification,
    ImpactResult,
    InterventionAction,
    InterventionCandidate,
    InterventionDecision,
    SemanticEvent,
    TaskNode,
    TaskStatus,
    TaskType,
)
from sentinel_x.core.task_graph import TaskGraph


# ── Configurable weights ────────────────────────────────────────────────

@dataclass
class InterventionWeights:
    """Tunable weights for the cost function."""
    alpha: float = 1.0   # wasted work
    beta: float = 2.0    # risk (intentionally high)
    gamma: float = 0.5   # recovery latency
    delta: float = 1.5   # side-effect exposure
    epsilon: float = 0.8  # disruption


DEFAULT_WEIGHTS = InterventionWeights()


# ── Public API ───────────────────────────────────────────────────────────

def generate_candidates(
    event: SemanticEvent,
    impact: ImpactResult,
    graph: TaskGraph,
    effects: list[EffectRecord] | None = None,
    weights: InterventionWeights | None = None,
) -> InterventionDecision:
    """
    Score all five intervention candidates and select the best one.
    """
    w = weights or DEFAULT_WEIGHTS
    effects = effects or []

    total_tasks = len(graph)
    n_invalidated = len(impact.invalidated)
    n_preserved = len(impact.preserved)
    n_uncertain = len(impact.uncertain)
    n_replan = len(impact.replan)

    has_running_external = _has_running_externals(impact, graph)
    has_committed_effects = any(
        e.status == EffectStatus.COMMITTED for e in effects
    )
    has_pending_effects = any(
        e.status == EffectStatus.PENDING for e in effects
    )

    candidates: list[InterventionCandidate] = []

    # ── 1. CONTINUE ──────────────────────────────────────────────────
    candidates.append(_score_continue(
        impact, total_tasks, n_invalidated, n_uncertain,
        has_running_external, w,
    ))

    # ── 2. DEFER ─────────────────────────────────────────────────────
    candidates.append(_score_defer(
        impact, total_tasks, n_invalidated, n_uncertain,
        has_running_external, w,
    ))

    # ── 3. PARTIAL PREEMPT ───────────────────────────────────────────
    candidates.append(_score_partial_preempt(
        impact, total_tasks, n_invalidated, n_preserved,
        n_uncertain, has_pending_effects, w,
    ))

    # ── 4. FULL PREEMPT ──────────────────────────────────────────────
    candidates.append(_score_full_preempt(
        impact, total_tasks, n_preserved, has_committed_effects, w,
    ))

    # ── 5. ASK USER ──────────────────────────────────────────────────
    candidates.append(_score_ask_user(
        impact, n_uncertain, has_committed_effects, w,
    ))

    # ── Safety filter + selection ────────────────────────────────────
    safe = [c for c in candidates if c.satisfies_safety]
    if not safe:
        # If nothing is safe, fall back to ASK_USER
        ask = next(c for c in candidates if c.action == InterventionAction.ASK_USER)
        ask.satisfies_safety = True
        ask.explanation += " (safety fallback)"
        safe = [ask]

    selected = min(safe, key=lambda c: c.total_cost)

    return InterventionDecision(
        event_id=event.id,
        candidates=candidates,
        selected=selected.action,
        selected_explanation=selected.explanation,
        safety_override=len(safe) < len(candidates),
    )


# ── Scoring helpers ──────────────────────────────────────────────────────

def _score_continue(
    impact: ImpactResult,
    total: int,
    n_inv: int,
    n_unc: int,
    has_ext: bool,
    w: InterventionWeights,
) -> InterventionCandidate:
    """CONTINUE: keep executing everything as-is."""
    wasted = 0.0  # no wasted work
    risk = (n_inv + n_unc) / max(total, 1) * 10   # high risk if many affected
    latency = 0.0
    side_effect = 5.0 if has_ext else 0.0
    disruption = 0.0

    safe = (n_inv == 0 and n_unc == 0)
    cost = (
        w.alpha * wasted
        + w.beta * risk
        + w.gamma * latency
        + w.delta * side_effect
        + w.epsilon * disruption
    )

    return InterventionCandidate(
        action=InterventionAction.CONTINUE,
        total_cost=round(cost, 3),
        wasted_work=wasted,
        risk=round(risk, 3),
        recovery_latency=latency,
        side_effect_exposure=side_effect,
        disruption=disruption,
        satisfies_safety=safe,
        explanation=(
            "Continue all tasks. "
            + ("Safe: no tasks affected." if safe else
               f"UNSAFE: {n_inv} invalidated, {n_unc} uncertain.")
        ),
    )


def _score_defer(
    impact: ImpactResult,
    total: int,
    n_inv: int,
    n_unc: int,
    has_ext: bool,
    w: InterventionWeights,
) -> InterventionCandidate:
    """DEFER: let running tasks finish, then resolve."""
    wasted = n_inv / max(total, 1) * 3  # some waste from finishing bad tasks
    risk = n_unc / max(total, 1) * 5
    latency = 3.0   # wait for running tasks
    side_effect = 3.0 if has_ext else 0.0
    disruption = 1.0

    safe = (n_inv <= 1 and n_unc == 0)
    cost = (
        w.alpha * wasted
        + w.beta * risk
        + w.gamma * latency
        + w.delta * side_effect
        + w.epsilon * disruption
    )

    return InterventionCandidate(
        action=InterventionAction.DEFER,
        total_cost=round(cost, 3),
        wasted_work=round(wasted, 3),
        risk=round(risk, 3),
        recovery_latency=latency,
        side_effect_exposure=side_effect,
        disruption=disruption,
        satisfies_safety=safe,
        explanation=(
            "Defer: let running work finish, then resolve. "
            + ("Safe." if safe else
               f"Risk: {n_inv} invalidated, {n_unc} uncertain.")
        ),
    )


def _score_partial_preempt(
    impact: ImpactResult,
    total: int,
    n_inv: int,
    n_pres: int,
    n_unc: int,
    has_pending: bool,
    w: InterventionWeights,
) -> InterventionCandidate:
    """PARTIAL_PREEMPT: stop only affected tasks, preserve the rest."""
    wasted = 0.5  # minimal waste from cancelling in-flight tasks
    risk = n_unc / max(total, 1) * 2  # lower risk — we preempted the bad
    latency = 1.5
    side_effect = 2.0 if has_pending else 0.0
    disruption = n_inv / max(total, 1) * 3

    safe = True  # partial preempt is always considered safe
    cost = (
        w.alpha * wasted
        + w.beta * risk
        + w.gamma * latency
        + w.delta * side_effect
        + w.epsilon * disruption
    )

    return InterventionCandidate(
        action=InterventionAction.PARTIAL_PREEMPT,
        total_cost=round(cost, 3),
        wasted_work=wasted,
        risk=round(risk, 3),
        recovery_latency=latency,
        side_effect_exposure=side_effect,
        disruption=round(disruption, 3),
        satisfies_safety=safe,
        explanation=(
            f"Partial preempt: stop {n_inv} affected task(s), "
            f"preserve {n_pres} valid task(s)."
        ),
    )


def _score_full_preempt(
    impact: ImpactResult,
    total: int,
    n_pres: int,
    has_committed: bool,
    w: InterventionWeights,
) -> InterventionCandidate:
    """FULL_PREEMPT: stop everything and rebuild."""
    wasted = n_pres / max(total, 1) * 8  # high waste — we kill valid work
    risk = 0.5  # low risk — we stop everything
    latency = 5.0  # high latency — full restart
    side_effect = 4.0 if has_committed else 1.0
    disruption = 8.0

    safe = True
    cost = (
        w.alpha * wasted
        + w.beta * risk
        + w.gamma * latency
        + w.delta * side_effect
        + w.epsilon * disruption
    )

    return InterventionCandidate(
        action=InterventionAction.FULL_PREEMPT,
        total_cost=round(cost, 3),
        wasted_work=round(wasted, 3),
        risk=risk,
        recovery_latency=latency,
        side_effect_exposure=side_effect,
        disruption=disruption,
        satisfies_safety=safe,
        explanation=(
            f"Full preempt: stop all {total} task(s) and restart. "
            f"Wastes {n_pres} preserved task(s)."
        ),
    )


def _score_ask_user(
    impact: ImpactResult,
    n_unc: int,
    has_committed: bool,
    w: InterventionWeights,
) -> InterventionCandidate:
    """ASK_USER: pause and ask for explicit user guidance."""
    wasted = 0.0
    risk = 0.0  # zero risk — human decides
    latency = 8.0  # high latency — waiting on user
    side_effect = 0.0
    disruption = 4.0  # moderate — user is interrupted

    safe = True
    cost = (
        w.alpha * wasted
        + w.beta * risk
        + w.gamma * latency
        + w.delta * side_effect
        + w.epsilon * disruption
    )

    reason = "Pause and request user guidance."
    if n_unc > 0:
        reason += f" {n_unc} task(s) have uncertain external state."
    if has_committed:
        reason += " Committed effects present — user confirmation recommended."

    return InterventionCandidate(
        action=InterventionAction.ASK_USER,
        total_cost=round(cost, 3),
        wasted_work=wasted,
        risk=risk,
        recovery_latency=latency,
        side_effect_exposure=side_effect,
        disruption=disruption,
        satisfies_safety=safe,
        explanation=reason,
    )


def _has_running_externals(impact: ImpactResult, graph: TaskGraph) -> bool:
    """Check if any affected task is a running external/irreversible task."""
    affected = set(impact.invalidated) | set(impact.uncertain) | set(impact.replan)
    for tid in affected:
        task = graph.get_task(tid)
        if task and task.status == TaskStatus.RUNNING and task.task_type in (
            TaskType.EXTERNAL, TaskType.IRREVERSIBLE,
        ):
            return True
    return False
