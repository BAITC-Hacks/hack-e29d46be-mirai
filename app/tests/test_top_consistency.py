import json

from fastapi.testclient import TestClient
from app.server import create_app


def test_top_uses_current_graph_when_csv_is_partial_or_stale(tmp_path):
    output = tmp_path / "outputs"
    output.mkdir()
    a, b, c = "100000004015047100", "100000004015047101", "100000004015047102"
    graph = {"nodes": [
        {"id": a, "role": "transit", "priority_score": .9, "priority_why": "Новый приоритет"},
        {"id": b, "role": "coordinator", "priority_score": .8, "evidence": "Новое основание"},
        {"id": c, "role": "peripheral", "priority_score": .1},
    ], "edges": []}
    path = output / "graph.json"
    path.write_text(json.dumps(graph), encoding="utf-8")
    (output / "top_nodes.csv").write_text(
        "rank,gid,role,priority_score,why\n1," + b + ",terminal,0.1234,Старая причина\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))
    rows = client.get("/api/top?n=3").json()
    assert [row["gid"] for row in rows] == [a, b, c]
    assert [row["rank"] for row in rows] == [1, 2, 3]
    assert rows[0]["why"] == "Новый приоритет"
    assert rows[1]["why"] == "Новое основание"
    for row in rows:
        node = client.get("/api/node/" + row["gid"]).json()["node"]
        assert row["priority_score"] == node["priority_score"]
        assert row["role"] == node["role"]

    # Replacing just graph.json must update ranking even if CSV is never replaced.
    graph["nodes"][1].update(priority_score=.99, role="distributor", priority_why="Смена версии")
    path.write_text(json.dumps(graph), encoding="utf-8")
    current = client.get("/api/top?n=1").json()
    assert current == [{"rank": 1, "gid": b, "role": "distributor",
                        "priority_score": .99, "why": "Смена версии"}]
