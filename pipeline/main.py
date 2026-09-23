"""Оркестратор пайплайна: data/*.parquet → outputs/ (3 CSV + graph.json)."""

import time
from pathlib import Path

from pipeline import config as C
from pipeline.clusters import assign_clusters
from pipeline.export import build_graph_json, validate, write_csvs, write_graph_json
from pipeline.layout import compute_layout
from pipeline.load import load, sanity_check
from pipeline.metrics import build_graph, node_metrics
from pipeline.priority import assign_priority, top_nodes
from pipeline.roles import assign_roles


def _extras(nodes, edges, tx, df):
    """Доп. признаки Даниала (pipeline/extras.py). Если модуля нет или он упал — работаем без них."""
    try:
        from pipeline.extras import compute_extras
    except ImportError:
        return df, {}, []
    try:
        per_node, global_ = compute_extras(nodes, edges, tx)
        per_node = per_node.drop(columns=[c for c in per_node if c != "gid" and c in df])
        bool_cols = [c for c in per_node if c != "gid" and per_node[c].dtype == bool]
        return df.merge(per_node, on="gid", how="left"), global_, bool_cols
    except Exception as e:  # extras не должны ломать обязательную часть
        print(f"  ! extras пропущены: {e}")
        return df, {}, []


def _add_extra_flags(df, bool_cols):
    """Булевы признаки из extras (например in_cycle, sync_inflow) → в список flags узла."""
    if not bool_cols:
        return df
    df = df.copy()
    df["flags"] = [f + [c for c in bool_cols if row.get(c) is True]
                   for f, row in zip(df["flags"], df[bool_cols].to_dict("records"))]
    return df


def run(data_dir: Path, out_dir: Path) -> dict:
    t0 = time.time()
    print("Пайплайн «Граф денег»")
    edges, nodes, tx = load(data_dir)
    sanity_check(edges, nodes, tx)

    G = build_graph(edges, nodes)
    df = node_metrics(G, nodes, tx)
    df, extras, extra_flags = _extras(nodes, edges, tx, df)
    df = _add_extra_flags(assign_roles(df, G), extra_flags)
    df = assign_priority(df)
    df, clusters = assign_clusters(G, df)
    top = top_nodes(df, C.TOP_N)

    write_csvs(df, clusters, top, out_dir)
    graph = build_graph_json(df, edges, clusters, compute_layout(G, dict(zip(df.gid, df.cluster_id))), extras)
    write_graph_json(graph, out_dir / "graph.json")
    validate(out_dir, len(nodes))
    print(f"  роли: {df.role.value_counts().to_dict()}")
    print(f"  готово за {time.time() - t0:.1f} с → {out_dir}/")
    return graph
