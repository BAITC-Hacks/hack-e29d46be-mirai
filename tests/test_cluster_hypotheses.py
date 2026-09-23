"""Explanations must not infer directed flows or isolation from membership alone."""

from types import SimpleNamespace

import networkx as nx
import pandas as pd
import pytest

from pipeline.clusters import assign_clusters
from pipeline.roles import _first_pass


def test_shared_community_does_not_claim_seed_transfers_without_a_directed_path():
    graph = nx.DiGraph()
    # Complete undirected projection; seed 1 is only a recipient.
    graph.add_weighted_edges_from(
        [(2, 1, 100), (3, 1, 100), (4, 1, 100),
         (2, 3, 100), (2, 4, 100), (3, 4, 100)], weight="sum_kzt")
    frame = pd.DataFrame({"gid": [1, 2, 3, 4],
                          "role": ["peripheral", "peripheral", "consolidator", "peripheral"],
                          "is_seed": [True, False, False, False], "priority_score": .1})
    _, clusters = assign_clusters(graph, frame)

    assert len(clusters) == 1
    assert not nx.has_path(graph, 1, 3)
    hypothesis = clusters.iloc[0].hypothesis
    assert "1 seed" in hypothesis and "узлов с признаками консолидации: 1" in hypothesis
    assert "сбор средств от" not in hypothesis


def test_small_communities_with_external_edges_are_not_called_isolated():
    graph = nx.DiGraph()
    graph.add_weighted_edges_from(
        [(1, 2, 100), (2, 3, 100), (3, 1, 100),
         (4, 5, 100), (5, 6, 100), (6, 4, 100), (3, 4, 1)], weight="sum_kzt")
    frame = pd.DataFrame({"gid": list(range(1, 7)), "role": "peripheral",
                          "is_seed": False, "priority_score": .1})
    assigned, clusters = assign_clusters(graph, frame)

    assert len(clusters) == 2
    for cluster in clusters.itertuples(index=False):
        members = set(assigned.loc[assigned.cluster_id == cluster.cluster_id, "gid"])
        assert cluster.n_nodes == 3
        assert any((source in members) != (target in members) for source, target in graph.edges)
        assert "изолирован" not in cluster.hypothesis.lower()
        assert "Небольшое сообщество" in cluster.hypothesis


@pytest.mark.parametrize("n_payers, expected_score", [(1, .6), (2, .7), (3, .8)])
def test_seed_terminal_evidence_keeps_missing_incoming_caveat(n_payers, expected_score):
    row = SimpleNamespace(is_seed=True, in_deg=n_payers, out_deg=0,
                          in_kzt=700_000., out_kzt=0., pass_through=0.,
                          truncated_by_depth=False, depth=0)
    role, score, evidence, _ = _first_pass(
        row, {"cons_in": 5, "dist_out": 10, "term_in_kzt": 167_000.})

    assert role == "terminal"
    assert score == pytest.approx(expected_score)
    assert "seed: входящие занижены выгрузкой" in evidence
    assert str(n_payers) in evidence
    assert len(evidence) <= 200
