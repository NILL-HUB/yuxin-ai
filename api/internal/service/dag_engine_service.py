from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from injector import inject

from internal.entity.dag_entity import DAGGraph, DAGNode
from internal.entity.cancel_token_entity import CancelToken
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


class DAGValidationError(ValueError):
    pass


@inject
@dataclass
class DAGEngine(BaseService):
    db: SQLAlchemy

    MAX_PARALLEL: int = 8

    def validate(self, graph: DAGGraph) -> None:
        if not graph.nodes:
            raise DAGValidationError("DAG graph must contain at least one node")

        for node in graph.nodes.values():
            for dep in node.depends_on:
                if dep not in graph.nodes:
                    raise DAGValidationError(
                        f"Node '{node.id}' depends on '{dep}' which does not exist"
                    )

        visited: set[str] = set()
        in_stack: set[str] = set()

        def _detect_cycle(node_id: str, path: list[str]) -> None:
            visited.add(node_id)
            in_stack.add(node_id)
            path.append(node_id)
            for dep in graph.nodes[node_id].depends_on:
                if dep not in visited:
                    _detect_cycle(dep, path)
                elif dep in in_stack:
                    cycle = path[path.index(dep):] + [dep]
                    raise DAGValidationError(f"Cycle detected: {' -> '.join(cycle)}")
            path.pop()
            in_stack.discard(node_id)

        for nid in graph.nodes:
            if nid not in visited:
                _detect_cycle(nid, [])

    def wave(self, graph: DAGGraph) -> list[set[str]]:
        self.validate(graph)

        remaining = set(graph.nodes.keys())
        completed: set[str] = set()
        waves: list[set[str]] = []

        while remaining:
            ready = {
                nid
                for nid in remaining
                if all(dep in completed for dep in graph.nodes[nid].depends_on)
            }
            if not ready:
                remaining_details = {nid: list(graph.nodes[nid].depends_on) for nid in remaining}
                raise DAGValidationError(
                    f"No nodes are ready to execute. Remaining: {remaining_details}"
                )
            waves.append(ready)
            completed |= ready
            remaining -= ready

        return waves

    def execute(
        self,
        graph: DAGGraph,
        instance_pool: Any,
        coordinator: Any,
        cancel_token: CancelToken | None = None,
        collector: Any | None = None,
    ) -> list[dict]:
        waves = self.wave(graph)
        results: dict[str, dict] = {}

        for wave_idx, wave_nodes in enumerate(waves):
            if cancel_token and cancel_token.is_cancelled():
                self._mark_nodes_cancelled(graph.nodes.values(), results)
                break

            node_ids = sorted(wave_nodes)
            max_workers = min(self.MAX_PARALLEL, len(node_ids))

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {}
                for nid in node_ids:
                    node = graph.nodes[nid]
                    instance = instance_pool.get_instance(node.agent_id) if node.agent_id else None
                    if instance:
                        node.status = "running"
                        if collector:
                            collector.record(node.id, "running")
                        future = executor.submit(
                            self._execute_node,
                            node=node,
                            instance=instance,
                            cancel_token=cancel_token,
                        )
                        future_map[future] = nid
                    else:
                        error_msg = f"No agent instance for node '{nid}'"
                        node.status = "failed"
                        node.error = error_msg
                        results[nid] = {"task_id": nid, "answer": "", "error": error_msg}
                        if collector:
                            collector.record(nid, "failed", error=error_msg)

                for future in as_completed(future_map):
                    nid = future_map[future]
                    try:
                        result = future.result()
                        results[nid] = result
                    except Exception as exc:
                        graph.nodes[nid].status = "failed"
                        graph.nodes[nid].error = str(exc)
                        results[nid] = {"task_id": nid, "answer": "", "error": str(exc)}
                        if collector:
                            collector.record(nid, "failed", error=str(exc))

        return list(results.values())

    def _execute_node(
        self,
        node: DAGNode,
        instance: Any,
        cancel_token: CancelToken | None = None,
    ) -> dict:
        try:
            result = instance.stream(node.description)
            answer = self._extract_answer(result)
            node.status = "success"
            node.answer = answer
            return {"task_id": node.id, "answer": answer, "error": None}
        except Exception as exc:
            node.status = "failed"
            node.error = str(exc)
            return {"task_id": node.id, "answer": "", "error": str(exc)}

    @staticmethod
    def _extract_answer(result: Any) -> str:
        if isinstance(result, dict):
            return result.get("answer", str(result))
        if isinstance(result, str):
            return result
        return str(result)

    @staticmethod
    def _mark_nodes_cancelled(nodes: Any, results: dict) -> None:
        for node in nodes:
            if node.status in ("pending", "running"):
                node.status = "failed"
                node.error = "cancelled"
                if node.id not in results:
                    results[node.id] = {"task_id": node.id, "answer": "", "error": "cancelled"}
