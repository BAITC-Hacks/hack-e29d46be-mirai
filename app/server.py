"""Local, offline-first HTTP interface for the pipeline's graph contract.

Run independently with: python -m uvicorn app.server:app --host 127.0.0.1
The team launcher can import ``app`` from this module.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import json
import logging
import math
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Path as PathParam
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
log = logging.getLogger(__name__)


def score(node: dict) -> float:
    try:
        value = float(node.get("priority_score", 0))
        return value if math.isfinite(value) else 0.0
    except (TypeError, ValueError):
        return 0.0


class GraphStore:
    """Refresh on file replacement, including when real output replaces the mock."""

    def __init__(self, root: Path, output_dir: Path | None = None):
        self.root = root
        self.output_dir = Path(output_dir) if output_dir is not None else root / "outputs"
        self.version = ""
        self.lock = threading.RLock()
        self.signature = None
        self.graph = None
        self.nodes = {}
        self.incoming = {}
        self.outgoing = {}

    def read(self):
        with self.lock:
            output = self.output_dir / "graph.json"
            path = output if output.is_file() else self.root / "shared/sample_graph.json"
            try:
                stat = path.stat()
                signature = (str(path), stat.st_mtime_ns, stat.st_size)
                if signature != self.signature:
                    raw = path.read_text(encoding="utf-8")
                    graph = json.loads(raw)
                    # IDs exceed JavaScript's 2**53 limit. Preserve decimal strings
                    # throughout the HTTP and assistant boundary, including CSV.
                    for node in graph["nodes"]:
                        node["id"] = str(node["id"])
                    nodes = {n["id"]: n for n in graph["nodes"]}
                    if len(nodes) != len(graph["nodes"]):
                        raise ValueError("Duplicate node ids")
                    incoming = {gid: [] for gid in nodes}
                    outgoing = {gid: [] for gid in nodes}
                    for edge in graph["edges"]:
                        edge["source"], edge["target"] = str(edge["source"]), str(edge["target"])
                        outgoing[edge["source"]].append(edge)
                        incoming[edge["target"]].append(edge)
                    for cluster in graph.get("clusters", []):
                        if isinstance(cluster.get("top_gids"), list):
                            cluster["top_gids"] = [str(gid) for gid in cluster["top_gids"]]
                    if isinstance(graph.get("extras"), dict) and "cycles" in graph["extras"]:
                        graph["extras"]["cycles"] = [[str(gid) for gid in cycle] for cycle in graph["extras"]["cycles"]]
                    # Reject non-finite values before they reach JSON responses.
                    json.dumps(graph, allow_nan=False)
                    self.graph, self.nodes = graph, nodes
                    self.incoming, self.outgoing = incoming, outgoing
                    self.signature = signature
                    self.version = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
                return self.graph, self.nodes, self.incoming, self.outgoing, path
            except FileNotFoundError as exc:
                raise HTTPException(503, "Данные ещё не готовы. Запустите пайплайн или добавьте shared/sample_graph.json.") from exc
            except (OSError, ValueError, TypeError, KeyError) as exc:
                log.warning("Graph could not be loaded: %s", type(exc).__name__)
                raise HTTPException(503, "Файл графа обновляется или содержит ошибку. Повторите загрузку.") from exc


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    graph_version: str | None = Field(default=None, max_length=100)


def checked_actions(raw, graph: dict) -> list[dict]:
    """Optional map actions contain only real string IDs and directed paths."""
    if not isinstance(raw, list):
        return []
    ids = {n["id"] for n in graph["nodes"]}
    pairs = {(e["source"], e["target"]) for e in graph["edges"]}
    actions = []
    for item in raw[:8]:
        if not isinstance(item, dict) or item.get("kind") not in ("nodes", "path"):
            continue
        gids = item.get("gids")
        if not isinstance(gids, list) or not 1 <= len(gids) <= 500:
            continue
        if any(not isinstance(gid, str) or gid not in ids for gid in gids):
            continue
        if item["kind"] == "path" and any(pair not in pairs for pair in zip(gids, gids[1:])):
            continue
        label = item.get("label")
        actions.append({"kind": item["kind"], "gids": gids,
                        "label": label[:180] if isinstance(label, str) else "Показать на карте"})
    return actions


def template_card(node: dict) -> dict:
    evidence = node.get("evidence") or "Обоснование пока не передано пайплайном."
    text = f"Узел {node['id']}. Роль-гипотеза: {node.get('role', 'не определена')}. {evidence}"
    if "truncated_by_depth" in (node.get("flags") or []) or node.get("depth") == 4:
        text += " На четвёртом колене связи могут быть обрезаны: отсутствие исходящих не доказывает оседание денег."
    if node.get("is_seed"):
        text += " Входящие seed-клиента видны не полностью."
    return {"text": text, "source": "template"}


async def assistant_call(name: str, argument, graph: dict, fallback: dict) -> dict:
    try:
        module = importlib.import_module("assistant")
        function = getattr(module, name)
        result = await asyncio.wait_for(
            run_in_threadpool(function, argument, copy.deepcopy(graph)), timeout=25
        )
        if not isinstance(result, dict):
            return fallback
        if name == "node_card":
            if isinstance(result.get("text"), str) and result.get("source") in {"llm", "template"}:
                return {"text": result["text"], "source": result["source"]}
        elif isinstance(result.get("answer"), str) and result.get("source") in {"llm", "fallback"}:
            valid_ids = {n["id"] for n in graph["nodes"]}
            citations = result.get("cited_gids", [])
            if isinstance(citations, list):
                answer = {"answer": result["answer"], "source": result["source"],
                        "cited_gids": list(dict.fromkeys(str(g) for g in citations
                                                       if type(g) in {str, int} and str(g) in valid_ids))}
                actions = checked_actions(result.get("actions"), graph)
                if actions:
                    answer["actions"] = actions
                return answer
    except Exception as exc:
        # Avoid logging prompts, provider secrets, or customer graph data.
        log.info("Assistant fallback: %s", type(exc).__name__)
    return fallback


def create_app(root: Path = ROOT, output_dir: Path | None = None) -> FastAPI:
    application = FastAPI(title="Mirai · Граф денег")
    store = GraphStore(Path(root), output_dir)
    application.state.graph_store = store
    application.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")

    @application.get("/")
    def index():
        if not (STATIC / "index.html").is_file():
            raise HTTPException(503, "Интерфейс ещё не установлен.")
        return FileResponse(STATIC / "index.html")

    @application.get("/api/graph")
    def graph(workspace: bool = False):
        with store.lock:
            graph, _, _, _, path = store.read()
            if not workspace:
                return graph
            # UI builds its top-list and cards from this same immutable snapshot.
            return {**graph, "meta": {**graph.get("meta", {}),
                    "app_version": store.version,
                    "app_data_source": "sample" if path.name == "sample_graph.json" else "outputs"}}

    def require_version(version: str | None):
        if version is not None and version != store.version:
            raise HTTPException(409, "Данные изменились. Обновите граф перед запросом к ассистенту.")

    @application.get("/api/node/{gid}")
    def node(gid: str = PathParam(pattern=r"^\d{1,20}$")):
        _, nodes, incoming, outgoing, _ = store.read()
        if gid not in nodes:
            raise HTTPException(404, "Узел не найден.")
        neighbor_ids = {e["source"] for e in incoming[gid]} | {e["target"] for e in outgoing[gid]}
        neighbor_ids.discard(gid)
        return {"node": nodes[gid], "incoming": incoming[gid], "outgoing": outgoing[gid],
                "neighbors": [nodes[n] for n in sorted(neighbor_ids)]}

    @application.get("/api/search")
    def search(q: str = Query(default="", max_length=80)):
        _, nodes, _, _, _ = store.read()
        query = q.strip()
        if not query:
            return []
        matches = [n for gid, n in nodes.items() if query in str(gid)]
        matches.sort(key=lambda n: (str(n["id"]) != query, -score(n), int(n["id"])))
        return matches[:20]

    @application.get("/api/top")
    def top(n: int = Query(default=20, ge=1, le=2248)):
        # CSV files are replaced separately by the pipeline. Use the same graph
        # snapshot as /api/node so old or partial CSV cannot mix versions.
        _, nodes, _, _, _ = store.read()
        ordered = sorted(nodes.values(), key=lambda x: (-score(x), int(x["id"])))[:n]
        return [{"rank": i, "gid": node["id"], "role": node.get("role", "peripheral"),
                 "priority_score": score(node), "why": node.get("priority_why") or node.get("evidence", "")}
                for i, node in enumerate(ordered, 1)]

    @application.get("/api/node/{gid}/card")
    async def card(gid: str = PathParam(pattern=r"^\d{1,20}$"), graph_version: str | None = Query(default=None, max_length=100)):
        with store.lock:
            graph, nodes, _, _, _ = store.read()
            require_version(graph_version)
        if gid not in nodes:
            raise HTTPException(404, "Узел не найден.")
        return await assistant_call("node_card", gid, graph, template_card(nodes[gid]))

    @application.post("/api/ask")
    async def ask(body: Question):
        question = body.question.strip()
        if not question:
            raise HTTPException(422, "Введите вопрос.")
        with store.lock:
            graph = store.read()[0]
            require_version(body.graph_version)
        fallback = {"answer": "Ассистент пока недоступен. Используйте поиск по gid, список приоритетов и метрики узла.",
                    "cited_gids": [], "source": "fallback"}
        return await assistant_call("ask", question, graph, fallback)

    return application


app = create_app(output_dir=Path(os.environ["MIRAI_OUTPUT_DIR"]) if os.environ.get("MIRAI_OUTPUT_DIR") else None)
