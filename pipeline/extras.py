"""Optional, explainable signals for the observed graph (not client balances).

All thresholds and limitations are documented in docs/methodology/.
The public entry point fails closed: malformed inputs return empty results.
"""

from collections import deque
import logging

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
TRANSIT_WINDOW_DAYS = 2
FAST_TRANSIT_THRESHOLD = 0.8
SYNC_MIN_PAYERS = 3
MAX_OBSERVED_DEPTH = 4
PER_NODE_DTYPES = {
    "gid": "int64", "fast_transit_share": "float64", "fast_transit": "bool",
    "same_day_transit_share_upper_bound": "float64", "sync_in_days": "int64",
    "sync_max_payers": "int64", "in_cycle": "bool", "likely_true_terminal": "bool",
    "terminal_unknown": "bool", "truncated_by_depth": "bool",
    "transit_observation_complete_share": "float64", "transit_seed_caveat": "bool",
}


def _empty_result():
    return pd.DataFrame({name: pd.Series(dtype=dtype)
                         for name, dtype in PER_NODE_DTYPES.items()}), {}


def _validate(nodes, edges, tx):
    for frame, columns in (
        (nodes, {"gid", "depth", "is_seed"}),
        (edges, {"src", "dst", "sum_kzt", "n_tx"}),
        (tx, {"src", "dst", "date", "sum_kzt"}),
    ):
        if not isinstance(frame, pd.DataFrame) or not columns <= set(frame.columns):
            raise ValueError("Missing required extras input columns")
        if frame[list(columns)].isna().any().any():
            raise ValueError("Null values in required extras input columns")
    for frame, columns in ((nodes, ["gid", "depth"]),
                           (edges, ["src", "dst", "n_tx"]), (tx, ["src", "dst"])):
        for name in columns:
            values = frame[name]
            if len(values) and (not pd.api.types.is_numeric_dtype(values)
                               or not np.isfinite(values).all()
                               or (values != np.floor(values)).any()):
                raise ValueError("Identifiers, depths and counts must be finite integers")
    if nodes.gid.duplicated().any() or edges.duplicated(["src", "dst"]).any():
        raise ValueError("Duplicate node IDs or aggregated edges")
    if not nodes.is_seed.isin([True, False]).all() or not nodes.depth.between(0, 4).all():
        raise ValueError("Invalid seed or depth values")
    gids = set(nodes.gid)
    for frame in (edges, tx):
        if not set(frame.src).union(frame.dst) <= gids:
            raise ValueError("Edge or transaction references an unknown node")
        if len(frame) and (not pd.api.types.is_numeric_dtype(frame.sum_kzt)
                           or not np.isfinite(frame.sum_kzt).all()
                           or (frame.sum_kzt <= 0).any()):
            raise ValueError("Transfer amounts must be finite and positive")
    if (edges.n_tx < 1).any():
        raise ValueError("Edge transaction counts must be positive")
    dated = tx.copy(deep=True)
    dated["date"] = pd.to_datetime(dated["date"], errors="raise").dt.normalize()
    if dated.date.isna().any():
        raise ValueError("Missing transaction dates")
    return dated


def _matched_value(incoming, outgoing, min_days):
    """FIFO capacity matching: each observed KZT is used at most once per node."""
    pending = deque()
    cursor = 0
    matched = 0.0
    for out_date, out_value in outgoing:
        latest = out_date - pd.Timedelta(days=min_days)
        earliest = out_date - pd.Timedelta(days=TRANSIT_WINDOW_DAYS)
        while cursor < len(incoming) and incoming[cursor][0] <= latest:
            date, value = incoming[cursor]
            pending.append([date, float(value)])
            cursor += 1
        while pending and pending[0][0] < earliest:
            pending.popleft()
        remaining = float(out_value)
        while pending and remaining > 0:
            amount = min(pending[0][1], remaining)
            matched += amount
            remaining -= amount
            pending[0][1] -= amount
            if pending[0][1] <= 0:
                pending.popleft()
    return matched


def _daily_flows(tx, endpoint):
    daily = tx.groupby([endpoint, "date"], sort=True).sum_kzt.sum().reset_index()
    return {int(gid): list(zip(group.date, group.sum_kzt))
            for gid, group in daily.groupby(endpoint, sort=False)}


def _temporal_features(nodes, edges, tx):
    result = nodes[["gid"]].copy().reset_index(drop=True)
    for name, dtype in PER_NODE_DTYPES.items():
        if name != "gid":
            result[name] = False if dtype == "bool" else 0
    incoming_value = edges.groupby("dst").sum_kzt.sum()
    has_outgoing = set(edges.src)
    seeds = nodes.is_seed.astype(bool).to_numpy()
    terminal = (nodes.gid.map(incoming_value).fillna(0).to_numpy() > 0)
    terminal &= ~nodes.gid.isin(has_outgoing).to_numpy()
    truncated = ((nodes.depth >= MAX_OBSERVED_DEPTH)
                 & ~nodes.gid.isin(has_outgoing)).to_numpy()
    result["truncated_by_depth"] = truncated
    result["likely_true_terminal"] = terminal & ~truncated & ~seeds
    result["terminal_unknown"] = terminal & (truncated | seeds)
    result["transit_seed_caveat"] = seeds

    # Self-transfers neither supply nor forward new value.
    flows = tx[tx.src != tx.dst]
    incoming = _daily_flows(flows, "dst")
    outgoing = _daily_flows(flows, "src")
    last_date = tx.date.max()
    shares, upper_bounds, observed = [], [], []
    for gid in result.gid:
        ins, outs = incoming.get(gid, []), outgoing.get(gid, [])
        total = sum(value for _, value in ins)
        shares.append(min(1.0, _matched_value(ins, outs, 1) / total) if total else 0.0)
        upper_bounds.append(min(1.0, _matched_value(ins, outs, 0) / total) if total else 0.0)
        complete = sum(value for date, value in ins
                       if date <= last_date - pd.Timedelta(days=TRANSIT_WINDOW_DAYS))
        observed.append(complete / total if total else 0.0)
    result["fast_transit_share"] = shares
    result["same_day_transit_share_upper_bound"] = upper_bounds
    result["transit_observation_complete_share"] = observed
    result["fast_transit"] = (result.fast_transit_share >= FAST_TRANSIT_THRESHOLD) & ~seeds
    counts = flows.groupby(["dst", "date"]).src.nunique()
    sync_days = counts[counts >= SYNC_MIN_PAYERS].groupby(level=0).size()
    max_payers = counts.groupby(level=0).max()
    result["sync_in_days"] = result.gid.map(sync_days).fillna(0)
    result["sync_max_payers"] = result.gid.map(max_payers).fillna(0)
    return result.astype(PER_NODE_DTYPES)


def compute_extras(nodes: pd.DataFrame, edges: pd.DataFrame,
                   tx: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return per-node optional signals and JSON-safe global graph observations.

    No input is modified. Errors log a warning and return a typed empty frame
    and an empty dict, allowing the mandatory pipeline to continue.
    """
    try:
        dated = _validate(nodes, edges, tx)
        per_node = _temporal_features(nodes, edges, dated)
        return per_node, {"resilience": [], "cycles": []}
    except Exception as exc:
        LOGGER.warning("Optional extras unavailable: %s", exc)
        return _empty_result()
