"""
SENTINEL-X — Task Dependency Graph.

Wraps NetworkX to manage the agent's active plan as a DAG.
Supports construction, dependency traversal, transitive impact
propagation, and status queries.
"""

from __future__ import annotations

from typing import Optional

import networkx as nx

from sentinel_x.core.models import TaskNode, TaskStatus


class TaskGraph:
    """
    A directed acyclic graph (DAG) of :class:`TaskNode` objects.

    Edges point from dependency → dependent:
        ``A → B`` means *B depends on A*.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._nodes: dict[str, TaskNode] = {}

    # ── Construction ─────────────────────────────────────────────────

    def add_task(self, task: TaskNode) -> None:
        """Add a task node (and its dependency edges) to the graph."""
        self._nodes[task.id] = task
        self._graph.add_node(task.id)
        for dep_id in task.dependencies:
            # Edge from dependency to this task
            self._graph.add_edge(dep_id, task.id)

    def add_tasks(self, tasks: list[TaskNode]) -> None:
        """Convenience: add multiple tasks in order."""
        for t in tasks:
            self.add_task(t)

    def remove_task(self, task_id: str) -> None:
        """Remove a task and its edges from the graph."""
        self._graph.remove_node(task_id)
        self._nodes.pop(task_id, None)

    # ── Queries ──────────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        """Return a task by ID, or ``None``."""
        return self._nodes.get(task_id)

    def all_tasks(self) -> list[TaskNode]:
        """Return all task nodes in insertion order."""
        return list(self._nodes.values())

    @property
    def task_ids(self) -> list[str]:
        return list(self._nodes.keys())

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, task_id: str) -> bool:
        return task_id in self._nodes

    # ── Dependency Traversal ─────────────────────────────────────────

    def direct_dependencies(self, task_id: str) -> list[str]:
        """Return IDs of tasks that *this* task directly depends on."""
        return list(self._graph.predecessors(task_id))

    def direct_dependents(self, task_id: str) -> list[str]:
        """Return IDs of tasks that directly depend on *this* task."""
        return list(self._graph.successors(task_id))

    def transitive_dependents(self, task_id: str) -> list[str]:
        """
        Return *all* downstream tasks reachable from ``task_id``,
        in topological order.  Does **not** include ``task_id`` itself.
        """
        descendants = nx.descendants(self._graph, task_id)
        # Return in topological order for determinism
        topo = list(nx.topological_sort(self._graph))
        return [n for n in topo if n in descendants]

    def transitive_dependencies(self, task_id: str) -> list[str]:
        """Return *all* upstream tasks that ``task_id`` transitively depends on."""
        ancestors = nx.ancestors(self._graph, task_id)
        topo = list(nx.topological_sort(self._graph))
        return [n for n in topo if n in ancestors]

    def root_tasks(self) -> list[str]:
        """Tasks with no dependencies (in-degree 0)."""
        return [n for n in self._graph.nodes if self._graph.in_degree(n) == 0]

    def leaf_tasks(self) -> list[str]:
        """Tasks with no dependents (out-degree 0)."""
        return [n for n in self._graph.nodes if self._graph.out_degree(n) == 0]

    def topological_order(self) -> list[str]:
        """Return task IDs in topological (execution) order."""
        return list(nx.topological_sort(self._graph))

    def is_dag(self) -> bool:
        """Return True if the graph is a valid DAG."""
        return nx.is_directed_acyclic_graph(self._graph)

    # ── Status Management ────────────────────────────────────────────

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        """Update the status of a task node."""
        node = self._nodes.get(task_id)
        if node is None:
            raise KeyError(f"Task {task_id!r} not found in graph")
        node.status = status

    def get_status(self, task_id: str) -> TaskStatus:
        node = self._nodes.get(task_id)
        if node is None:
            raise KeyError(f"Task {task_id!r} not found in graph")
        return node.status

    def tasks_by_status(self, status: TaskStatus) -> list[str]:
        """Return IDs of all tasks with the given status."""
        return [tid for tid, t in self._nodes.items() if t.status == status]

    def runnable_tasks(self) -> list[str]:
        """
        Return PENDING tasks whose *all* dependencies are COMPLETED
        or PRESERVED — i.e. they are ready to execute.
        """
        ready = []
        for tid, task in self._nodes.items():
            if task.status != TaskStatus.PENDING:
                continue
            deps = self.direct_dependencies(tid)
            if all(
                self._nodes[d].status
                in (TaskStatus.COMPLETED, TaskStatus.PRESERVED)
                for d in deps
                if d in self._nodes
            ):
                ready.append(tid)
        return ready

    # ── Serialization ────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize graph to a JSON-friendly dict."""
        return {
            "nodes": [t.model_dump(mode="json") for t in self._nodes.values()],
            "edges": [
                {"from": u, "to": v} for u, v in self._graph.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskGraph":
        """Reconstruct a TaskGraph from ``to_dict()`` output."""
        graph = cls()
        for node_data in data["nodes"]:
            graph.add_task(TaskNode(**node_data))
        return graph

    def snapshot_ids(self) -> dict[str, list[str]]:
        """Return current task IDs grouped by status — useful for state capsules."""
        result: dict[str, list[str]] = {}
        for status in TaskStatus:
            ids = self.tasks_by_status(status)
            if ids:
                result[status.value] = ids
        return result
