"""Contract and failure-mode tests. Run: python -m pytest app/tests -q."""
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.server import create_app


@pytest.fixture
def graph():
    return {"meta": {}, "nodes": [
        {"id": 12, "role": "transit", "priority_score": .5, "evidence": "2 перевода", "is_seed": True},
        {"id": 123, "role": "terminal", "priority_score": .9, "depth": 4},
        {"id": 999, "role": "peripheral", "priority_score": .1},
    ], "edges": [{"source": 12, "target": 123, "sum_kzt": 5000, "n_tx": 2}], "clusters": []}


def write_graph(root, graph, output=False):
    path = root / ("outputs/graph.json" if output else "shared/sample_graph.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph), encoding="utf-8")


@pytest.fixture
def client(tmp_path, graph):
    write_graph(tmp_path, graph)
    return TestClient(create_app(tmp_path))


def test_contract_and_search(client):
    assert client.get("/api/graph").status_code == 200
    node = client.get("/api/node/12").json()
    assert node["node"]["id"] == "12"
    assert node["incoming"] == []
    assert node["outgoing"][0]["target"] == "123"
    assert [n["id"] for n in node["neighbors"]] == ["123"]
    assert client.get("/api/node/999").json()["neighbors"] == []
    assert client.get("/api/node/42").status_code == 404
    assert [n["id"] for n in client.get("/api/search?q=12").json()] == ["12", "123"]
    assert client.get("/api/search?q=").json() == []
    assert client.get("/api/top?n=1").json()[0]["gid"] == "123"
    assert client.get("/api/top?n=0").status_code == 422
    assert client.get("/api/node/nope").status_code == 422


def test_reload_prefers_real_output_and_csv(client, tmp_path, graph):
    assert len(client.get("/api/graph").json()["nodes"]) == 3
    graph["nodes"].append({"id": 777, "priority_score": 1})
    write_graph(tmp_path, graph, output=True)
    assert len(client.get("/api/graph").json()["nodes"]) == 4
    (tmp_path / "outputs/top_nodes.csv").write_text(
        "rank,gid,role,priority_score,why\n1,12,transit,0.5,Причина из CSV\n", encoding="utf-8")
    assert client.get("/api/top").json()[0]["why"] == "Причина из CSV"
    graph["nodes"][0]["evidence"] = "Обновлено"
    write_graph(tmp_path, graph, output=True)
    assert client.get("/api/node/12").json()["node"]["evidence"] == "Обновлено"


def test_missing_and_invalid_graph(tmp_path, graph):
    client = TestClient(create_app(tmp_path))
    assert client.get("/api/graph").status_code == 503
    write_graph(tmp_path, graph)
    (tmp_path / "shared/sample_graph.json").write_text("{", encoding="utf-8")
    assert client.get("/api/graph").status_code == 503
    graph["edges"][0]["target"] = 404
    write_graph(tmp_path, graph)
    assert client.get("/api/graph").status_code == 503


def test_missing_assistant_and_validation(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "assistant", None)
    assert client.get("/api/node/12/card").json()["source"] == "template"
    assert "четвёртом" in client.get("/api/node/123/card").json()["text"]
    assert client.get("/api/node/404/card").status_code == 404
    assert client.post("/api/ask", json={"question": "Что видно?"}).json()["source"] == "fallback"
    for value in ["", "  ", "x" * 4001]:
        assert client.post("/api/ask", json={"question": value}).status_code == 422


def test_assistant_forwarding_and_errors(client, monkeypatch):
    calls = []
    def card(gid, graph):
        calls.append((gid, len(graph["nodes"])))
        graph["nodes"].clear()
        return {"text": "Карточка", "source": "llm"}
    module = types.SimpleNamespace(node_card=card, ask=lambda q, g: {
        "answer": q, "cited_gids": [12, 12, 98765, "123"], "source": "llm"})
    monkeypatch.setitem(sys.modules, "assistant", module)
    assert client.get("/api/node/12/card").json() == {"text": "Карточка", "source": "llm"}
    assert calls == [("12", 3)]
    assert len(client.get("/api/graph").json()["nodes"]) == 3
    answer = client.post("/api/ask", json={"question": "  Вопрос  "}).json()
    assert answer["answer"] == "Вопрос" and answer["cited_gids"] == ["12", "123"]
    def broken(*args):
        raise RuntimeError("Provider failed")
    module.ask = broken
    assert client.post("/api/ask", json={"question": "Вопрос"}).json()["source"] == "fallback"
    module.node_card = lambda *args: {"text": 5, "source": "llm"}
    assert client.get("/api/node/12/card").json()["source"] == "template"


def test_scale_and_search_limit(tmp_path):
    graph = {"meta": {}, "nodes": [{"id": i, "priority_score": i / 2248} for i in range(2248)],
             "edges": [{"source": i, "target": i+1} for i in range(2247)]}
    write_graph(tmp_path, graph)
    client = TestClient(create_app(tmp_path))
    assert len(client.get("/api/graph").json()["nodes"]) == 2248
    assert len(client.get("/api/search?q=1").json()) == 20
    assert client.get("/api/search?q=1").json()[0]["id"] == "1"
    assert client.get("/api/top?n=100").json()[0]["gid"] == "2247"


def test_self_loop_and_optional_fields(tmp_path):
    graph = {"nodes": [{"id": 1}], "edges": [{"source": 1, "target": 1}]}
    write_graph(tmp_path, graph)
    client = TestClient(create_app(tmp_path))
    node = client.get("/api/node/1").json()
    assert len(node["incoming"]) == len(node["outgoing"]) == 1
    assert node["neighbors"] == []
    assert client.get("/api/top").json()[0]["priority_score"] == 0


def test_18_digit_ids_remain_exact(tmp_path, monkeypatch):
    first, second = "100000004015047100", "100000004015047101"
    graph = {"nodes": [{"id": first}, {"id": second}],
             "edges": [{"source": first, "target": second}],
             "clusters": [{"top_gids": [first, second]}],
             "extras": {"cycles": [[first, second, first]]}}
    write_graph(tmp_path, graph, output=True)
    (tmp_path / "outputs/top_nodes.csv").write_text(
        f"rank,gid,role,priority_score,why\n1,{second},transit,0.9,Проверка\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path))
    assert client.get("/api/graph").json() == graph
    assert client.get(f"/api/search?q={second}").json()[0]["id"] == second
    assert client.get(f"/api/node/{first}").json()["neighbors"][0]["id"] == second
    assert client.get("/api/top").json()[0]["gid"] == second
    def card(gid, graph):
        assert gid == first and isinstance(gid, str)
        return {"text": gid, "source": "template"}
    monkeypatch.setitem(sys.modules, "assistant", types.SimpleNamespace(
        node_card=card, ask=lambda q, g: {"answer": second, "cited_gids": [first, second], "source": "fallback"}))
    assert client.get(f"/api/node/{first}/card").json()["text"] == first
    assert client.post("/api/ask", json={"question": "Проверка"}).json()["cited_gids"] == [first, second]
