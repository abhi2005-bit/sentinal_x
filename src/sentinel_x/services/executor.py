"""
SENTINEL-X — Agent Execution Engine.

Simulates executing the task graph asynchronously.
Integrates with the event bus and effect ledger.
Handles task state transitions and safe preemption.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sentinel_x.core.models import (
    EffectStatus,
    TaskStatus,
    TaskType,
)
from sentinel_x.core.task_graph import TaskGraph
from sentinel_x.services.effect_ledger import EffectLedger
from sentinel_x.services.event_bus import EventBus, SystemEvent, SystemEventType
from sentinel_x.simulator.external_systems import ExternalSystemSimulator


logger = logging.getLogger(__name__)


class Executor:
    """
    Simulates the agent's execution loop.

    Runs runnable tasks concurrently, respects dependencies,
    and supports stopping (preemption) during interrupts.
    """

    def __init__(
        self,
        session_id: str,
        graph: TaskGraph,
        bus: EventBus,
        ledger: EffectLedger,
        simulator: ExternalSystemSimulator,
    ) -> None:
        self.session_id = session_id
        self.graph = graph
        self.bus = bus
        self.ledger = ledger
        self.simulator = simulator

        self._stop_event = asyncio.Event()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._loop_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the execution loop in the background."""
        self._stop_event.clear()
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._execution_loop())

    async def stop(self) -> None:
        """Signal the executor to stop scheduling new tasks."""
        self._stop_event.set()
        if self._loop_task:
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

    async def preempt(self) -> None:
        """
        Hard-stop execution. Cancels all running asyncio tasks
        and the main loop immediately.
        """
        self._stop_event.set()

        for tid, task in self._running_tasks.items():
            if not task.done():
                task.cancel()

        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()

        # Wait for cancellations to process
        if self._running_tasks:
            await asyncio.gather(
                *self._running_tasks.values(), return_exceptions=True
            )
        self._running_tasks.clear()

    async def _execution_loop(self) -> None:
        """Main loop that polls for runnable tasks and spawns them."""
        try:
            while not self._stop_event.is_set():
                # Clean up completed asyncio tasks
                done = [
                    tid for tid, task in self._running_tasks.items()
                    if task.done()
                ]
                for tid in done:
                    self._running_tasks.pop(tid, None)

                # Are we done with the whole graph?
                pending = self.graph.tasks_by_status(TaskStatus.PENDING)
                running = self.graph.tasks_by_status(TaskStatus.RUNNING)
                if not pending and not running:
                    break

                # Find runnable tasks
                runnable = self.graph.runnable_tasks()
                for tid in runnable:
                    if tid not in self._running_tasks and not self._stop_event.is_set():
                        # Spawn execution
                        task = asyncio.create_task(self._execute_task(tid))
                        self._running_tasks[tid] = task

                await asyncio.sleep(0.1)  # Tick rate

        except asyncio.CancelledError:
            pass
        finally:
            self._loop_task = None

    async def _execute_task(self, task_id: str) -> None:
        """Execute a single task node."""
        node = self.graph.get_task(task_id)
        if not node:
            return

        try:
            # Mark RUNNING
            self.graph.set_status(task_id, TaskStatus.RUNNING)
            await self.bus.publish(
                SystemEvent(
                    SystemEventType.TASK_STARTED,
                    self.session_id,
                    {"task_id": task_id, "description": node.description},
                )
            )

            # Execution logic based on TaskType
            if node.task_type == TaskType.EXTERNAL or node.task_type == TaskType.IRREVERSIBLE:
                await self._execute_external(task_id)
            else:
                await self._execute_pure(task_id)

            # If we weren't preempted, mark COMPLETED
            if node.status == TaskStatus.RUNNING:
                self.graph.set_status(task_id, TaskStatus.COMPLETED)
                await self.bus.publish(
                    SystemEvent(
                        SystemEventType.TASK_COMPLETED,
                        self.session_id,
                        {"task_id": task_id},
                    )
                )

        except asyncio.CancelledError:
            # Task was preempted
            logger.info(f"Task {task_id} execution cancelled")
            raise
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            if self.graph.get_status(task_id) == TaskStatus.RUNNING:
                self.graph.set_status(task_id, TaskStatus.FAILED)

    async def _execute_pure(self, task_id: str) -> None:
        """Simulate pure computation with a small delay."""
        await asyncio.sleep(0.5)

    async def _execute_external(self, task_id: str) -> None:
        """Execute an external side-effect via the simulator."""
        node = self.graph.get_task(task_id)
        if not node:
            return

        system_name = node.metadata.get("system", "flight_booking")

        # 1. Register intent in ledger
        effect = self.ledger.register(task_id, f"call_{system_name}")

        # 2. Transition to PENDING
        self.ledger.transition(effect.effect_id, EffectStatus.PENDING)

        await self.bus.publish(
            SystemEvent(
                SystemEventType.EFFECT_UPDATED,
                self.session_id,
                {"effect_id": effect.effect_id, "status": EffectStatus.PENDING.value},
            )
        )

        # 3. Call external system
        params = node.metadata.copy()
        try:
            response = await self.simulator.execute(system_name, "execute", params)
            
            # Map status
            status_map = {
                "committed": EffectStatus.COMMITTED,
                "pending": EffectStatus.PENDING,
                "failed": EffectStatus.FAILED,
            }
            new_status = status_map.get(response.status, EffectStatus.UNKNOWN)

            # 4. Transition to result state
            self.ledger.transition(
                effect.effect_id,
                new_status,
                external_reference=response.reference_id,
                result=response.data,
            )

            await self.bus.publish(
                SystemEvent(
                    SystemEventType.EFFECT_UPDATED,
                    self.session_id,
                    {
                        "effect_id": effect.effect_id,
                        "status": new_status.value,
                        "reference_id": response.reference_id,
                    },
                )
            )

        except asyncio.CancelledError:
            # If we get cancelled while waiting for the external system,
            # we MUST leave the effect in PENDING/UNKNOWN state because
            # we don't know if the server received it. The verifier will handle it.
            raise
