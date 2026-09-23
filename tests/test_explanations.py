"""Independent checks of projection, witnesses and score reconstruction."""
from pathlib import Path
import networkx as nx
import pandas as pd
import pytest

from pipeline.clusters import assign_clusters, undirected_projection
from pipeline.main import run, _extras
from pipeline.priority import assign_priority, stability_scenarios
from pipeline.roles import _coordinators


def test_reciprocal_weights_and_self_loop_are_not_lost_or_doubled():
    graph = nx.DiGraph()
    graph.add_nodes_from([4, 3, 2, 1])
    graph.add_weighted_edges_from([(1, 2, 3), (2, 1, 7), (3, 3, 5)], weight="sum_kzt")
    projected = undirected_projection(graph)
    assert list(projected) == [1, 2, 3, 4]
    assert projected[1][2]["sum_kzt"] == 10
    assert projected[3][3]["sum_kzt"] == 5
    assert projected.size(weight="sum_kzt") == graph.size(weight="sum_kzt")


def test_clustering_unchanged_when_input_order_reversed():
    pairs = [(1, 2, 3), (2, 1, 7), (2, 3, 1), (3, 4, 9), (4, 3, 2), (4, 5, 1)]
    results = []
    for reverse in (False, True):
        graph = nx.DiGraph()
        gids = list(range(1, 7))[::(-1 if reverse else 1)]
        graph.add_nodes_from(gids)
        graph.add_weighted_edges_from(pairs[::-1] if reverse else pairs, weight="sum_kzt")
        frame = pd.DataFrame({"gid": gids, "role": "peripheral", "is_seed": False, "priority_score": .1})
        assigned, clusters = assign_clusters(graph, frame)
        results.append((assigned.set_index("gid").cluster_id.sort_index(), clusters))
    pd.testing.assert_series_equal(results[0][0], results[1][0])
    pd.testing.assert_frame_equal(results[0][1], results[1][1])


def test_rank_sensitivity_includes_baseline_and_preserves_ties():
    frame = pd.DataFrame({"gid": [100000000000000003, 100000000000000001, 100000000000000002],
                          "role": "peripheral", "role_score": .2, "in_kzt": 100., "out_kzt": 100.,
                          "seed_exposure": .1, "betweenness": .1, "fast_forward_share": .5,
                          "flags": [[], [], []]})
    result = assign_priority(frame)
    assert result.gid.tolist() == sorted(frame.gid)
    for rank, row in enumerate(result.itertuples(), 1):
        assert row.rank_stability["min_rank"] == row.rank_stability["max_rank"] == rank
        assert row.rank_stability["top_k_share"] == 1
        assert sum(x["contribution"] for x in row.priority_components) == pytest.approx(row.priority_score, abs=.00005)
    for scenario in stability_scenarios():
        assert sum(scenario["weights"].values()) == pytest.approx(1)


def test_real_graph_witnesses_and_scores(tmp_path):
    graph = run(Path(__file__).resolve().parents[1] / "data", tmp_path)
    gids = {n["id"] for n in graph["nodes"]}
    edges = {(e["source"], e["target"]) for e in graph["edges"]}
    assert graph["meta"]["period_start"] == "2026-07-01"
    assert graph["meta"]["period_end"] == "2026-07-31"
    assert graph["meta"]["dataset_version"].startswith("sha256:")
    for node in graph["nodes"]:
        for item in node["evidence_items"]:
            assert node["id"] in item["gids"]
            assert set(item["gids"]) <= gids
            for edge in item["edges"]:
                assert (edge["source"], edge["target"]) in edges
                assert node["id"] in (edge["source"], edge["target"])
        parts = node["priority_components"]
        assert len(parts) == 5
        for part in parts:
            assert part["value"] * part["weight"] == pytest.approx(part["contribution"])
        assert sum(p["contribution"] for p in parts) == pytest.approx(node["priority_score"], abs=.00005)
        stability = node["rank_stability"]
        assert stability["min_rank"] <= node["rank"] <= stability["max_rank"]
        assert stability["scenarios"] == 11
        assert 0 <= stability["top_k_share"] <= 1
    # Reversed real input must retain communities, not just community count.
    reverse = nx.DiGraph()
    reverse.add_nodes_from(int(n["id"]) for n in reversed(graph["nodes"]))
    for edge in reversed(graph["edges"]):
        reverse.add_edge(int(edge["source"]), int(edge["target"]), sum_kzt=edge["sum_kzt"])
    frame = pd.read_csv(tmp_path / "nodes_roles.csv").iloc[::-1]
    assigned, _ = assign_clusters(reverse, frame)
    assert dict(zip(assigned.gid.astype(str), assigned.cluster_id)) == {n["id"]: n["cluster_id"] for n in graph["nodes"]}


def test_coordinator_witness_contains_only_rule_supporting_edges():
    graph = nx.DiGraph()
    graph.add_weighted_edges_from([(1, 3, 10), (2, 3, 20), (4, 3, 999)], weight="sum_kzt")
    frame = pd.DataFrame({"gid": [1, 2, 3, 4], "role": ["consolidator", "consolidator", "peripheral", "peripheral"]})
    score, _, item = _coordinators(graph, frame, {"betw": 1})[3]
    assert score == .9
    assert item["edges"] == [{"source": "1", "target": "3"}, {"source": "2", "target": "3"}]
    assert item["gids"] == ["1", "2", "3"]


def test_non_json_optional_result_does_not_poison_main(monkeypatch):
    frame = pd.DataFrame({"gid": [1], "in_kzt": [10]})
    monkeypatch.setattr("pipeline.extras.compute_extras", lambda *args: (pd.DataFrame({"gid": [1]}), {"bad": float("nan")}))
    result, extras, flags = _extras(frame, None, None, frame)
    pd.testing.assert_frame_equal(result, frame)
    assert extras == {} and flags == []
