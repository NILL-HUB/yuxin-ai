from unittest.mock import MagicMock
from pytest import raises

from internal.entity.dag_entity import DAGGraph, DAGNode
from internal.service.dag_engine_service import DAGEngine, DAGValidationError


def _make_engine():
    return DAGEngine(db=MagicMock())


def _node(nid: str, depends_on: list[str] | None = None) -> DAGNode:
    return DAGNode(id=nid, agent_id="a1", title=nid, description=nid, depends_on=depends_on or [])


def _graph(nodes: list[DAGNode]) -> DAGGraph:
    return DAGGraph(nodes={n.id: n for n in nodes})


class TestDAGValidation:
    def test_empty_graph_raises(self):
        with raises(DAGValidationError, match="at least one node"):
            _make_engine().validate(_graph([]))

    def test_missing_dependency_raises(self):
        nodes = [_node("a"), _node("b", depends_on=["c"])]
        with raises(DAGValidationError, match="depends on.*c.*does not exist"):
            _make_engine().validate(_graph(nodes))

    def test_self_reference_raised(self):
        nodes = [_node("a", depends_on=["a"])]
        with raises(DAGValidationError, match="Cycle detected"):
            _make_engine().validate(_graph(nodes))

    def test_diamond_dag_validates(self):
        nodes = [
            _node("root"),
            _node("a", depends_on=["root"]),
            _node("b", depends_on=["root"]),
            _node("leaf", depends_on=["a", "b"]),
        ]
        engine = _make_engine()
        engine.validate(_graph(nodes))


class TestWave:
    def test_single_node_returns_one_wave(self):
        g = _graph([_node("a")])
        waves = _make_engine().wave(g)
        assert waves == [{"a"}]

    def test_linear_dag_returns_two_waves(self):
        g = _graph([_node("a"), _node("b", depends_on=["a"])])
        waves = _make_engine().wave(g)
        assert len(waves) == 2
        assert waves[0] == {"a"}
        assert waves[1] == {"b"}

    def test_fan_out_returns_parallel_wave(self):
        g = _graph([_node("a"), _node("b", depends_on=["a"]), _node("c", depends_on=["a"])])
        waves = _make_engine().wave(g)
        assert len(waves) == 2
        assert waves[1] == {"b", "c"}

    def test_diamond_returns_three_waves(self):
        g = _graph([
            _node("a"),
            _node("b", depends_on=["a"]),
            _node("c", depends_on=["a"]),
            _node("d", depends_on=["b", "c"]),
        ])
        waves = _make_engine().wave(g)
        assert len(waves) == 3
        assert waves[0] == {"a"}
        assert waves[2] == {"d"}
