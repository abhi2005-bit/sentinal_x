"""Tests for TaskGraph construction and dependency traversal."""

import pytest

from sentinel_x.core.models import TaskNode, TaskStatus, TaskType
from sentinel_x.core.task_graph import TaskGraph


def _travel_graph() -> tuple[TaskGraph, dict[str, str]]:
    """
    Build the canonical travel-agent graph from the doc:

        search_flights -> compare_flights -> book_flight
                |               |
                |               +-> itinerary
                |
        search_hotel -> compare_hotel --------> itinerary
    """
    ids: dict[str, str] = {}
    tasks = [
        TaskNode(id="search_flights", description="Search Flights",
                 task_type=TaskType.PURE, tags=["search", "flight", "destination"]),
        TaskNode(id="search_hotel", description="Search Hotel",
                 task_type=TaskType.PURE, tags=["search", "hotel", "destination"]),
        TaskNode(id="compare_flights", description="Compare Flights",
                 task_type=TaskType.PURE, dependencies=["search_flights"],
                 tags=["compare", "flight"]),
        TaskNode(id="compare_hotel", description="Compare Hotel",
                 task_type=TaskType.PURE, dependencies=["search_hotel"],
                 tags=["compare", "hotel"]),
        TaskNode(id="book_flight", description="Book Flight",
                 task_type=TaskType.IRREVERSIBLE,
                 dependencies=["compare_flights"],
                 tags=["book", "flight", "purchase"]),
        TaskNode(id="itinerary", description="Create Itinerary",
                 task_type=TaskType.PURE,
                 dependencies=["compare_flights", "compare_hotel"],
                 tags=["itinerary"]),
    ]

    graph = TaskGraph()
    graph.add_tasks(tasks)
    ids = {t.id: t.id for t in tasks}
    return graph, ids


class TestGraphConstruction:
    def test_add_tasks(self):
        graph, ids = _travel_graph()
        assert len(graph) == 6

    def test_is_dag(self):
        graph, _ = _travel_graph()
        assert graph.is_dag()

    def test_all_tasks_present(self):
        graph, _ = _travel_graph()
        assert set(graph.task_ids) == {
            "search_flights", "search_hotel",
            "compare_flights", "compare_hotel",
            "book_flight", "itinerary",
        }


class TestDependencyTraversal:
    def test_direct_dependencies(self):
        graph, _ = _travel_graph()
        assert graph.direct_dependencies("compare_flights") == ["search_flights"]

    def test_direct_dependents(self):
        graph, _ = _travel_graph()
        deps = set(graph.direct_dependents("compare_flights"))
        assert deps == {"book_flight", "itinerary"}

    def test_transitive_dependents_of_search_flights(self):
        graph, _ = _travel_graph()
        trans = graph.transitive_dependents("search_flights")
        assert set(trans) == {"compare_flights", "book_flight", "itinerary"}

    def test_transitive_dependents_of_search_hotel(self):
        graph, _ = _travel_graph()
        trans = graph.transitive_dependents("search_hotel")
        assert set(trans) == {"compare_hotel", "itinerary"}

    def test_transitive_dependencies_of_itinerary(self):
        graph, _ = _travel_graph()
        ancs = graph.transitive_dependencies("itinerary")
        assert set(ancs) == {
            "search_flights", "compare_flights",
            "search_hotel", "compare_hotel",
        }

    def test_root_tasks(self):
        graph, _ = _travel_graph()
        assert set(graph.root_tasks()) == {"search_flights", "search_hotel"}

    def test_leaf_tasks(self):
        graph, _ = _travel_graph()
        assert set(graph.leaf_tasks()) == {"book_flight", "itinerary"}

    def test_topological_order(self):
        graph, _ = _travel_graph()
        order = graph.topological_order()
        assert len(order) == 6
        # search_ tasks must appear before their dependents
        assert order.index("search_flights") < order.index("compare_flights")
        assert order.index("compare_flights") < order.index("book_flight")
        assert order.index("search_hotel") < order.index("compare_hotel")


class TestStatusManagement:
    def test_set_and_get_status(self):
        graph, _ = _travel_graph()
        graph.set_status("search_flights", TaskStatus.COMPLETED)
        assert graph.get_status("search_flights") == TaskStatus.COMPLETED

    def test_tasks_by_status(self):
        graph, _ = _travel_graph()
        graph.set_status("search_flights", TaskStatus.COMPLETED)
        graph.set_status("search_hotel", TaskStatus.COMPLETED)
        assert set(graph.tasks_by_status(TaskStatus.COMPLETED)) == {
            "search_flights", "search_hotel",
        }

    def test_runnable_tasks_initially(self):
        graph, _ = _travel_graph()
        # Only root tasks should be runnable
        assert set(graph.runnable_tasks()) == {
            "search_flights", "search_hotel",
        }

    def test_runnable_tasks_after_completion(self):
        graph, _ = _travel_graph()
        graph.set_status("search_flights", TaskStatus.COMPLETED)
        graph.set_status("search_hotel", TaskStatus.COMPLETED)
        runnable = set(graph.runnable_tasks())
        assert "compare_flights" in runnable
        assert "compare_hotel" in runnable

    def test_missing_task_raises(self):
        graph, _ = _travel_graph()
        with pytest.raises(KeyError):
            graph.set_status("nonexistent", TaskStatus.RUNNING)


class TestSerialization:
    def test_roundtrip(self):
        graph, _ = _travel_graph()
        graph.set_status("search_flights", TaskStatus.COMPLETED)
        data = graph.to_dict()
        restored = TaskGraph.from_dict(data)
        assert len(restored) == len(graph)
        assert restored.get_status("search_flights") == TaskStatus.COMPLETED

    def test_snapshot_ids(self):
        graph, _ = _travel_graph()
        graph.set_status("search_flights", TaskStatus.COMPLETED)
        snap = graph.snapshot_ids()
        assert "COMPLETED" in snap
        assert "search_flights" in snap["COMPLETED"]
