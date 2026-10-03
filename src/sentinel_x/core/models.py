"""
SENTINEL-X — Canonical types, enums, and Pydantic models.

This module is the single source of truth for every data structure used
across the pipeline.  All other modules import from here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Enums ────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    """Lifecycle state of a single task node."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PRESERVED = "PRESERVED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TaskType(str, Enum):
    """Side-effect classification of a task."""
    PURE = "PURE"                  # No external side-effects
    REVERSIBLE = "REVERSIBLE"      # Can be undone
    IRREVERSIBLE = "IRREVERSIBLE"  # Cannot be undone once committed
    EXTERNAL = "EXTERNAL"          # Calls an external service


class EventType(str, Enum):
    """Category of an incoming real-time event."""
    AUTHORIZATION_CHANGE = "AUTHORIZATION_CHANGE"
    GOAL_CHANGE = "GOAL_CHANGE"
    CONSTRAINT_CHANGE = "CONSTRAINT_CHANGE"
    ENTITY_CHANGE = "ENTITY_CHANGE"
    GLOBAL_CANCELLATION = "GLOBAL_CANCELLATION"
    NON_IMPACTING = "NON_IMPACTING"
    EXTERNAL_WORLD_CHANGE = "EXTERNAL_WORLD_CHANGE"


class ChangeClass(str, Enum):
    """Semantic classification of what changed."""
    AUTHORIZATION = "AUTHORIZATION"
    GOAL = "GOAL"
    CONSTRAINT = "CONSTRAINT"
    ENTITY = "ENTITY"
    GLOBAL_CANCEL = "GLOBAL_CANCEL"
    NON_IMPACTING = "NON_IMPACTING"
    EXTERNAL = "EXTERNAL"


class InterventionAction(str, Enum):
    """Possible intervention strategies."""
    CONTINUE = "CONTINUE"
    DEFER = "DEFER"
    PARTIAL_PREEMPT = "PARTIAL_PREEMPT"
    FULL_PREEMPT = "FULL_PREEMPT"
    ASK_USER = "ASK_USER"


class EffectStatus(str, Enum):
    """External side-effect lifecycle state."""
    NOT_SENT = "NOT_SENT"
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


class ImpactClassification(str, Enum):
    """How a task is affected by a semantic event."""
    PRESERVED = "PRESERVED"
    INVALIDATED = "INVALIDATED"
    REPLAN = "REPLAN"
    UNCERTAIN = "UNCERTAIN"


# ── Helpers ──────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Core Data Models ────────────────────────────────────────────────────

class TaskNode(BaseModel):
    """A single node in the agent's task dependency graph."""
    id: str = Field(default_factory=_new_id)
    description: str
    status: TaskStatus = TaskStatus.PENDING
    task_type: TaskType = TaskType.PURE
    dependencies: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Tags used by the impact engine to match semantic events
    tags: list[str] = Field(default_factory=list)

    model_config = ConfigDict(use_enum_values=False)


class SemanticEvent(BaseModel):
    """
    Structured output of the semantic interpreter.

    Represents *what changed* in intent, constraints, authorization,
    or the external environment.
    """
    id: str = Field(default_factory=_new_id)
    raw_text: str = ""
    event_type: EventType
    change_class: ChangeClass

    goal_changes: list[str] = Field(default_factory=list)
    authorization_changes: list[str] = Field(default_factory=list)
    constraints_added: list[str] = Field(default_factory=list)
    constraints_removed: list[str] = Field(default_factory=list)
    entity_changes: dict[str, str] = Field(default_factory=dict)

    affected_task_hints: list[str] = Field(default_factory=list)
    replan_required: bool = False
    confidence: float = 1.0

    timestamp: datetime = Field(default_factory=_utcnow)


class TaskImpact(BaseModel):
    """Impact classification for a single task."""
    task_id: str
    classification: ImpactClassification
    reason: str = ""


class ImpactResult(BaseModel):
    """Output of the impact engine: which tasks are affected and how."""
    event_id: str
    plan_revision: int = 0
    task_impacts: list[TaskImpact] = Field(default_factory=list)
    preserved: list[str] = Field(default_factory=list)
    invalidated: list[str] = Field(default_factory=list)
    replan: list[str] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_utcnow)


class InterventionCandidate(BaseModel):
    """One possible intervention with its cost breakdown."""
    action: InterventionAction
    total_cost: float = 0.0
    wasted_work: float = 0.0       # W
    risk: float = 0.0              # R
    recovery_latency: float = 0.0  # L
    side_effect_exposure: float = 0.0  # S
    disruption: float = 0.0        # U
    explanation: str = ""
    satisfies_safety: bool = True


class InterventionDecision(BaseModel):
    """
    Final decision of the counterfactual intervention planner.

    Contains all candidates, the selected action, and the reasoning.
    """
    event_id: str
    candidates: list[InterventionCandidate] = Field(default_factory=list)
    selected: InterventionAction = InterventionAction.CONTINUE
    selected_explanation: str = ""
    safety_override: bool = False
    timestamp: datetime = Field(default_factory=_utcnow)


class EffectRecord(BaseModel):
    """Tracks a single external side-effect (e.g. a booking API call)."""
    effect_id: str = Field(default_factory=_new_id)
    task_id: str
    operation: str = ""
    request_id: str = ""
    idempotency_key: str = Field(default_factory=_new_id)
    status: EffectStatus = EffectStatus.NOT_SENT
    external_reference: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    result: dict[str, Any] = Field(default_factory=dict)
    compensation_available: bool = False


class StateCapsule(BaseModel):
    """Resume-safe snapshot of the execution state after an intervention."""
    session_id: str
    plan_revision: int = 0
    completed: list[str] = Field(default_factory=list)
    running: list[str] = Field(default_factory=list)
    preserved: list[str] = Field(default_factory=list)
    invalidated: list[str] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)
    pending_effects: list[str] = Field(default_factory=list)
    committed_effects: list[str] = Field(default_factory=list)
    next_safe_task: Optional[str] = None
    goal_snapshot: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)


class SessionState(BaseModel):
    """Top-level mutable state for one agent session."""
    session_id: str = Field(default_factory=_new_id)
    goal: str = ""
    plan_revision: int = 0
    tasks: list[TaskNode] = Field(default_factory=list)
    events: list[SemanticEvent] = Field(default_factory=list)
    effects: list[EffectRecord] = Field(default_factory=list)
    decisions: list[InterventionDecision] = Field(default_factory=list)
    capsules: list[StateCapsule] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
