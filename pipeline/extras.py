"""Optional, explainable signals for the observed graph (not client balances).

All thresholds and limitations are documented in docs/methodology/.
The public entry point fails closed: malformed inputs return empty results.
"""

from collections import deque
import logging
from time import monotonic

import networkx as nx
import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
TRANSIT_WINDOW_DAYS = 2
FAST_TRANSIT_THRESHOLD = 0.8
SYNC_MIN_PAYERS = 3
MAX_OBSERVED_DEPTH = 4
MAX_CYCLE_LENGTH = 5
MAX_CYCLES = 1000
MAX_CYCLE_STEPS = 200_000
MAX_CYCLE_SECONDS = 5.0
MAX_ROUTE_CANDIDATES = 50_000
MAX_ROUTES = 1000
MAX_ROUTE_SECONDS = 5.0
BETWEENNESS_SAMPLES = 128
PER_NODE_DTYPES = {
    "gid": "int64", "fast_transit_share": "float64", "fast_transit": "bool",
    "same_day_transit_share_upper_bound": "float64", "sync_in_days": "int64",
    "sync_max_payers": "int64", "in_cycle": "bool", "likely_true_terminal": "bool",
    "terminal_unknown": "bool", "truncated_by_depth": "bool",
    "transit_observation_complete_share": "float64", "transit_seed_caveat": "bool",
    "repeated_route_count": "int64",
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


def _bounded_cycles(graph):
    """Enumerate directed simple cycles with budgets checked on each DFS edge.

    Unlike a timeout checked only between simple_cycles yields, this also
    bounds unsuccessful path searches. The smallest gid is the canonical start.
    """
    start_time = monotonic()
    cycles, steps = [], 0
    components = sorted((sorted(c) for c in nx.strongly_connected_components(graph)),
                        key=lambda c: c[0])
    for component in components:
        if len(component) == 1 and not graph.has_edge(component[0], component[0]):
            continue
        members = set(component)
        adjacency = {v: sorted(w for w in graph[v] if w in members) for v in component}
        for start in component:
            path, used = [start], {start}
            stack = [iter(adjacency[start])]
            while stack:
                if steps >= MAX_CYCLE_STEPS or monotonic() - start_time >= MAX_CYCLE_SECONDS:
                    return cycles, False, steps
                target = next(stack[-1], None)
                if target is None:
                    stack.pop()
                    used.remove(path.pop())
                    continue
                steps += 1
                if target == start:
                    cycles.append(path + [start])
                    if len(cycles) >= MAX_CYCLES:
                        return cycles, False, steps
                elif target > start and target not in used and len(path) < MAX_CYCLE_LENGTH:
                    path.append(target)
                    used.add(target)
                    stack.append(iter(adjacency[target]))
    return cycles, True, steps


def _route_occurrences(first, second):
    """Match transactions one-to-one on dates, not on value, within one route."""
    cursor, count = 0, 0
    for date in second:
        while cursor < len(first) and (date - first[cursor]).days > TRANSIT_WINDOW_DAYS:
            cursor += 1
        if cursor < len(first) and 1 <= (date - first[cursor]).days <= TRANSIT_WINDOW_DAYS:
            count += 1
            cursor += 1
    return count


def _repeated_routes(graph, tx):
    start_time = monotonic()
    dates = {tuple(map(int, pair)): sorted(group.date.tolist())
             for pair, group in tx.groupby(["src", "dst"], sort=True) if len(group) >= 2}
    routes, examined = [], 0
    for middle in sorted(graph):
        for source in sorted(graph.predecessors(middle)):
            first = dates.get((source, middle))
            if source == middle or first is None:
                continue
            for target in sorted(graph.successors(middle)):
                if examined >= MAX_ROUTE_CANDIDATES or monotonic() - start_time >= MAX_ROUTE_SECONDS:
                    return routes, False, examined
                examined += 1
                if target in (source, middle):
                    continue
                second = dates.get((middle, target))
                if second is None:
                    continue
                occurrences = _route_occurrences(first, second)
                if occurrences >= 2:
                    routes.append({"gids": [str(source), str(middle), str(target)],
                                   "occurrences": occurrences, "window_days": TRANSIT_WINDOW_DAYS})
                    if len(routes) >= MAX_ROUTES:
                        return routes, False, examined
    return routes, True, examined


def _resilience(graph, nodes):
    score = None
    ranking = "betweenness_sampled"
    for column in ("priority_score", "betweenness"):
        if column not in nodes:
            continue
        values = pd.to_numeric(nodes[column], errors="coerce")
        if np.isfinite(values).all():
            score = {int(gid): float(value) for gid, value in zip(nodes.gid, values)}
            ranking = column
            break
    if score is None:
        k = min(BETWEENNESS_SAMPLES, len(graph))
        score = (nx.betweenness_centrality(graph, k=k, weight=None, seed=42)
                 if k else {})
        if len(graph) <= BETWEENNESS_SAMPLES:
            ranking = "betweenness_exact"
    order = sorted(graph, key=lambda gid: (-score[gid], gid))
    total_value = sum(data["sum_kzt"] for _, _, data in graph.edges(data=True))
    results = []
    for requested in (0, 5, 10, 20):
        removed = order[:requested]
        remaining = graph.copy()
        remaining.remove_nodes_from(removed)
        components = list(nx.weakly_connected_components(remaining))
        largest = max(map(len, components), default=0)
        retained_value = sum(data["sum_kzt"] for _, _, data in remaining.edges(data=True))
        results.append({
            "removed_top_n": requested, "actual_removed_n": len(removed),
            "removed_gids": [str(gid) for gid in removed], "ranking_metric": ranking,
            "remaining_nodes": len(remaining), "largest_component_nodes": largest,
            "largest_component_share": largest / len(remaining) if remaining else 0.0,
            "largest_component_original_share": largest / len(graph) if graph else 0.0,
            "n_components": len(components),
            "observed_flow_removed_share": max(0.0, min(1.0, 1 - retained_value / total_value))
            if total_value else 0.0,
        })
    return results


def _build_graph(nodes, edges):
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(map(int, nodes.gid)))
    for row in edges.sort_values(["src", "dst"]).itertuples(index=False):
        graph.add_edge(int(row.src), int(row.dst), sum_kzt=float(row.sum_kzt), n_tx=int(row.n_tx))
    return graph


def compute_resilience(nodes: pd.DataFrame, edges: pd.DataFrame) -> list[dict]:
    """Refresh only removal scenarios after the core computes priority_score."""
    try:
        return _resilience(_build_graph(nodes, edges), nodes)
    except Exception as exc:
        LOGGER.warning("Optional resilience unavailable: %s", exc)
        return []


def _network_features(nodes, edges, tx, per_node):
    graph = _build_graph(nodes, edges)
    cycles, cycles_complete, cycle_steps = _bounded_cycles(graph)
    cycle_members = {gid for cycle in cycles for gid in cycle}
    per_node["in_cycle"] = per_node.gid.isin(cycle_members)
    routes, routes_complete, candidates = _repeated_routes(graph, tx)
    route_counts = {}
    for route in routes:
        for gid in route["gids"]:
            route_counts[int(gid)] = route_counts.get(int(gid), 0) + 1
    per_node["repeated_route_count"] = per_node.gid.map(route_counts).fillna(0).astype("int64")
    if not cycles_complete or not routes_complete:
        LOGGER.warning("Optional extras search capped: cycles_complete=%s routes_complete=%s",
                       cycles_complete, routes_complete)
    return {
        "cycles": [[str(gid) for gid in cycle] for cycle in cycles],
        "cycles_complete": cycles_complete, "cycle_search_steps": cycle_steps,
        "cycle_max_length": MAX_CYCLE_LENGTH,
        "repeated_routes": routes, "repeated_routes_complete": routes_complete,
        "route_candidates_examined": candidates,
        "resilience": _resilience(graph, nodes),
    }


def compute_extras(nodes: pd.DataFrame, edges: pd.DataFrame,
                   tx: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return per-node optional signals and JSON-safe global graph observations.

    No input is modified. Errors log a warning and return a typed empty frame
    and an empty dict, allowing the mandatory pipeline to continue.
    """
    try:
        dated = _validate(nodes, edges, tx)
        per_node = _temporal_features(nodes, edges, dated)
        global_ = _network_features(nodes, edges, dated, per_node)
        return per_node, global_
    except Exception as exc:
        LOGGER.warning("Optional extras unavailable: %s", exc)
        return _empty_result()
