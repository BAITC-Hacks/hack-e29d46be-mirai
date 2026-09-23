"""Regression checks for real exports and optional-stage failures."""
import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline.export import validate, write_graph_json
from pipeline.load import load, sanity_check
from pipeline.main import _extras, run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("pipeline")
    return out, run(ROOT / "data", out)


def test_real_exports_preserve_roles_and_identifiers(result):
    out, graph = result
    nr = pd.read_csv(out / "nodes_roles.csv")
    assert nr.role.value_counts().to_dict() == {
        "peripheral": 1619, "terminal": 281, "transit": 248,
        "distributor": 48, "consolidator": 36, "coordinator": 16,
    }
    assert {str(gid) for gid in nr.gid} == {n["id"] for n in graph["nodes"]}
    assert all(isinstance(n["id"], str) for n in graph["nodes"])
    for n in graph["nodes"]:
        assert len(n["flags"]) == len(set(n["flags"]))
        assert "fast_transit_share" in n["metrics"]
        assert "sync_in_days" in n["metrics"]
        if "fast_transit" in n["flags"]:
            assert n["metrics"]["fast_transit_share"] >= .8
            assert not n["is_seed"]
        if n["depth"] == 4 and n["metrics"]["out_deg"] == 0:
            assert "terminal_unknown" in n["flags"]
    json.dumps(graph, allow_nan=False)


def test_resilience_removes_final_priority_nodes(result):
    out, graph = result
    ranked = pd.read_csv(out / "top_nodes.csv").gid.astype(str).tolist()
    for scenario in graph["extras"]["resilience"]:
        assert scenario["ranking_metric"] == "priority_score"
        assert scenario["removed_gids"] == ranked[:scenario["removed_top_n"]]


@pytest.mark.parametrize("mode", ["empty", "duplicate", "missing", "exception"])
def test_optional_failure_keeps_mandatory_metrics(monkeypatch, mode):
    df = pd.DataFrame({"gid": [100000000000000001, 100000000000000002], "in_kzt": [1., 2.]})
    original = df.copy(deep=True)
    def broken(nodes, edges, tx):
        nodes.loc[0, "in_kzt"] = 999
        if mode == "exception":
            raise RuntimeError("optional stage failed")
        rows = {"empty": [], "duplicate": [df.gid[0], df.gid[0]], "missing": [df.gid[0]]}[mode]
        return pd.DataFrame({"gid": rows, "fast_transit": [True] * len(rows)}), {}
    monkeypatch.setattr("pipeline.extras.compute_extras", broken)
    actual, extras, flags = _extras(df, pd.DataFrame(), pd.DataFrame(), df)
    pd.testing.assert_frame_equal(actual, original)
    assert extras == {} and flags == []


def test_failed_serialization_preserves_previous_graph(tmp_path):
    path = tmp_path / "graph.json"
    write_graph_json({"ok": True}, path)
    with pytest.raises(ValueError):
        write_graph_json({"bad": float("nan")}, path)
    assert json.loads(path.read_text()) == {"ok": True}


@pytest.mark.parametrize("column", ["sum_kzt", "n_tx"])
def test_input_aggregate_mismatch_rejected(column):
    edges, nodes, tx = load(ROOT / "data")
    edges.loc[0, column] += 100
    with pytest.raises(ValueError, match="суммам или числу"):
        sanity_check(edges, nodes, tx)


@pytest.mark.parametrize("fault", ["duplicate", "score", "rank"])
def test_invalid_exports_rejected(result, tmp_path, fault):
    out, _ = result
    for name in ("nodes_roles.csv", "clusters.csv", "top_nodes.csv"):
        (tmp_path / name).write_bytes((out / name).read_bytes())
    path = tmp_path / "top_nodes.csv"
    top = pd.read_csv(path)
    if fault == "duplicate":
        top.loc[1, "gid"] = top.loc[0, "gid"]
    elif fault == "score":
        top.loc[0, "priority_score"] = 1.1
    else:
        top.loc[0, "rank"] = 2
    top.to_csv(path, index=False)
    with pytest.raises(ValueError, match="top_nodes.csv"):
        validate(tmp_path, 2248)
