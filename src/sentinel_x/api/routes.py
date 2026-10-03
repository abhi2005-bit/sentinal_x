"""
SENTINEL-X — FastAPI Routes.

REST endpoints for session management, execution control, and
interruption handling.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from sentinel_x.core.models import (
    SessionState,
    TaskStatus,
)
from sentinel_x.core.impact_engine import analyze_impact
from sentinel_x.core.intervention import generate_candidates
from sentinel_x.core.recovery import execute_recovery
from sentinel_x.services.event_bus import SystemEvent, SystemEventType

# For the prototype, we store session components globally.
# In production, these would be in a DB/Redis.
from sentinel_x.api.websocket import get_bus
from sentinel_x.simulator.travel_agent import build_travel_graph
from sentinel_x.simulator.external_systems import create_travel_simulator
from sentinel_x.services.effect_ledger import EffectLedger
from sentinel_x.services.executor import Executor
from sentinel_x.services.interpreter import SemanticInterpreter
from sentinel_x.services.verifier import Verifier


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


# Global state for prototype
_STATE: dict[str, SessionState] = {}
_EXECUTORS: dict[str, Executor] = {}
_LEDGERS: dict[str, EffectLedger] = {}
_SIMULATORS: dict[str, Any] = {}
_GRAPHS: dict[str, Any] = {}
_INTERPRETER = SemanticInterpreter(use_llm=False)


class CreateSessionRequest(BaseModel):
    goal: str = "Plan Chennai to Delhi trip"


class InterruptRequest(BaseModel):
    raw_text: str


@router.post("", response_model=SessionState)
async def create_session(req: CreateSessionRequest):
    """Initialize a new agent session."""
    graph = build_travel_graph()
    state = SessionState(goal=req.goal, tasks=graph.all_tasks())
    
    # Init components
    sid = state.session_id
    simulator = create_travel_simulator()
    ledger = EffectLedger()
    bus = get_bus()
    executor = Executor(sid, graph, bus, ledger, simulator)
    
    _STATE[sid] = state
    _EXECUTORS[sid] = executor
    _LEDGERS[sid] = ledger
    _SIMULATORS[sid] = simulator
    _GRAPHS[sid] = graph
    
    await bus.publish(SystemEvent(SystemEventType.SESSION_STARTED, sid, {"goal": req.goal}))
    return state


@router.get("/{session_id}", response_model=SessionState)
async def get_session(session_id: str):
    """Retrieve session state."""
    state = _STATE.get(session_id)
    if not state:
        raise HTTPException(404, "Session not found")
    # Update tasks from live graph
    state.tasks = _GRAPHS[session_id].all_tasks()
    state.effects = _LEDGERS[session_id].all_effects()
    return state


@router.post("/{session_id}/start")
async def start_session(session_id: str, background_tasks: BackgroundTasks):
    """Start the execution loop for the session."""
    executor = _EXECUTORS.get(session_id)
    if not executor:
        raise HTTPException(404, "Session not found")
    
    # Fire and forget
    background_tasks.add_task(executor.start)
    return {"status": "started", "session_id": session_id}


@router.post("/{session_id}/interrupt")
async def interrupt_session(session_id: str, req: InterruptRequest):
    """
    Handle a real-time event.
    Executes the entire SENTINEL-X core pipeline.
    """
    executor = _EXECUTORS.get(session_id)
    graph = _GRAPHS.get(session_id)
    state = _STATE.get(session_id)
    ledger = _LEDGERS.get(session_id)
    simulator = _SIMULATORS.get(session_id)
    bus = get_bus()
    
    if not all([executor, graph, state, ledger, simulator]):
        raise HTTPException(404, "Session not found")

    # 1. Stop current execution
    await executor.preempt()
    await bus.publish(SystemEvent(SystemEventType.INTERRUPT_RECEIVED, session_id, {"raw_text": req.raw_text}))

    # 2. Semantic Interpretation
    semantic_event = await _INTERPRETER.interpret(req.raw_text)
    state.events.append(semantic_event)

    # 3. Impact Analysis
    impact = analyze_impact(semantic_event, graph, state.plan_revision)
    await bus.publish(SystemEvent(SystemEventType.IMPACT_ANALYZED, session_id, impact.model_dump(mode="json")))

    # 4. Counterfactual Planning
    decision = generate_candidates(semantic_event, impact, graph, ledger.all_effects())
    state.decisions.append(decision)
    await bus.publish(SystemEvent(SystemEventType.INTERVENTION_SELECTED, session_id, decision.model_dump(mode="json")))

    # 5. External Verification
    verifier = Verifier(ledger, simulator)
    await bus.publish(SystemEvent(SystemEventType.EXTERNAL_STATE_VERIFIED, session_id, {"status": "verifying"}))
    await verifier.verify_all_pending()

    # 6. Recovery & State Capsule
    recovery_result = execute_recovery(
        session_id, semantic_event, impact, decision, graph, ledger.all_effects(), state.plan_revision, {"goal": state.goal}
    )
    
    # For tasks needing verification (like late interrupt), try cancellation if preempted
    for tid in recovery_result.preempted_tasks:
        effects = ledger.get_by_task(tid)
        for e in effects:
            await verifier.attempt_cancellation(e.effect_id)

    state.capsules.append(recovery_result.capsule)
    state.plan_revision = recovery_result.new_plan_revision
    
    # Map back to state model
    state.tasks = graph.all_tasks()
    state.effects = ledger.all_effects()

    await bus.publish(SystemEvent(SystemEventType.REPLAN_COMPLETED, session_id, {"capsule_id": len(state.capsules)}))
    
    return {
        "status": "interrupted",
        "decision": decision.selected.value,
        "preempted": recovery_result.preempted_tasks,
        "preserved": recovery_result.preserved_tasks,
    }


@router.post("/{session_id}/resume")
async def resume_session(session_id: str, background_tasks: BackgroundTasks):
    """Resume execution after an interrupt."""
    executor = _EXECUTORS.get(session_id)
    bus = get_bus()
    if not executor:
        raise HTTPException(404, "Session not found")
        
    await bus.publish(SystemEvent(SystemEventType.SESSION_RESUMED, session_id))
    background_tasks.add_task(executor.start)
    return {"status": "resumed", "session_id": session_id}


@router.get("/{session_id}/metrics")
async def get_metrics(session_id: str):
    """Expose metrics for benchmarking."""
    graph = _GRAPHS.get(session_id)
    ledger = _LEDGERS.get(session_id)
    if not graph or not ledger:
        raise HTTPException(404, "Session not found")
        
    return {
        "completed_tasks": len(graph.tasks_by_status(TaskStatus.COMPLETED)),
        "preserved_tasks": len(graph.tasks_by_status(TaskStatus.PRESERVED)),
        "cancelled_tasks": len(graph.tasks_by_status(TaskStatus.CANCELLED)),
        "invalidated_tasks": len(graph.tasks_by_status(TaskStatus.INVALIDATED)),
        "total_effects": len(ledger.all_effects()),
    }
