"""Reject lossy identifiers before graph construction; accept exact integer IDs."""

from pathlib import Path

import pandas as pd
import pytest

from pipeline.load import load, sanity_check

ID_COLUMNS = (("nodes", "gid"), ("edges", "src"), ("edges", "dst"),
              ("transactions", "src"), ("transactions", "dst"))


def _inputs(dtype="int64", gids=(100000000343175100, 100000000343175300)):
    source, target = gids
    frames = {
        "nodes": pd.DataFrame({"gid": gids, "depth": [0, 1], "is_seed": [True, False]}),
        "edges": pd.DataFrame({"src": [source], "dst": [target],
                               "sum_kzt": [10000.], "n_tx": [2], "depth": [1]}),
        "transactions": pd.DataFrame({"src": [source, source], "dst": [target, target],
                                      "sum_kzt": [5000., 5000.],
                                      "date": pd.to_datetime(["2026-07-01", "2026-07-02"])}),
    }
    for name, column in ID_COLUMNS:
        frames[name][column] = frames[name][column].astype(dtype)
    return frames


def _check(frames):
    sanity_check(frames["edges"], frames["nodes"], frames["transactions"])


@pytest.mark.parametrize("name,column", ID_COLUMNS)
def test_float_ids_are_rejected_at_every_input_endpoint(name, column):
    frames = _inputs()
    exact = int(frames[name][column].iloc[0])
    frames[name][column] = frames[name][column].astype("float64")
    assert int(frames[name][column].iloc[0]) != exact  # Actual 18-digit loss.
    with pytest.raises(ValueError, match=rf"{name}\.{column}:.*целочисленный"):
        _check(frames)


@pytest.mark.parametrize("dtype", ["bool", "boolean", "string", "object"])
def test_non_integer_representations_are_not_silently_coerced(dtype):
    frames = _inputs()
    for name, column in ID_COLUMNS:
        values = frames[name][column]
        if dtype in ("bool", "boolean"):
            values = values.astype(bool)
        frames[name][column] = values.astype(dtype)
    with pytest.raises(ValueError, match="целочисленный тип"):
        _check(frames)


@pytest.mark.parametrize("dtype", ["int64", "Int64", "uint64", "UInt64"])
def test_exact_integer_ids_are_accepted_without_mutation(dtype):
    frames = _inputs(dtype)
    before = {name: frame.copy(deep=True) for name, frame in frames.items()}
    _check(frames)
    for name in frames:
        pd.testing.assert_frame_equal(frames[name], before[name])


@pytest.mark.parametrize("dtype", ["uint64", "UInt64"])
def test_unsigned_values_outside_signed_int64_contract_are_rejected(dtype):
    frames = _inputs(dtype, (2**63, 2**63 + 1))
    with pytest.raises(ValueError, match="диапазон int64"):
        _check(frames)


def test_signed_int64_boundaries_do_not_overflow_during_validation():
    _check(_inputs("Int64", (-2**63, 2**63 - 1)))


def test_official_parquet_identifiers_remain_valid():
    edges, nodes, transactions = load(Path(__file__).resolve().parents[1] / "data")
    sanity_check(edges, nodes, transactions)
