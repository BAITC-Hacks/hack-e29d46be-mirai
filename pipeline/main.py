"""Оркестратор пайплайна: data/*.parquet → outputs/ (3 CSV + graph.json)."""

import time
import logging
import hashlib
import json

import pandas as pd
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
        per_node, global_ = compute_extras(df.copy(deep=True), edges, tx)
        if per_node.empty:
            return df, {}, []
        if ("gid" not in per_node or per_node.gid.duplicated().any()
                or set(per_node.gid) != set(df.gid) or not isinstance(global_, dict)):
            raise ValueError("extras must return exactly one row per input gid and a dict")
        json.dumps(global_, allow_nan=False)  # malformed optional data must not break export
        per_node = per_node.drop(columns=[c for c in per_node if c != "gid" and c in df])
        bool_cols = [c for c in per_node if c != "gid" and per_node[c].dtype == bool]
        return df.merge(per_node, on="gid", how="left", validate="one_to_one"), global_, bool_cols
    except Exception as e:  # extras не должны ломать обязательную часть
        print(f"  ! extras пропущены: {e}")
        return df, {}, []


def _add_extra_flags(df, bool_cols):
    """Значимые признаки из extras → в список flags узла (без дублей).

    Во флаги попадают только признаки из config.EXTRA_FLAGS: массовые пометки вроде
    «не seed и без исходящих» на тысяче узлов только зашумили бы карточки.
    """
    df = df.copy()
    extra = {c: df[c].fillna(False).astype(bool) for c in bool_cols if c in C.EXTRA_FLAGS}
    if "sync_in_days" in df:
        extra["sync_inflow"] = df["sync_in_days"].fillna(0) > 0
    if not extra:
        return df
    extra_df = pd.DataFrame(extra, index=df.index)
    df["flags"] = [list(dict.fromkeys(f + [c for c in extra_df.columns if row[c]]))
                   for f, (_, row) in zip(df["flags"], extra_df.iterrows())]
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
    # Resilience removes the nodes shown in the final priority list.
    if "resilience" in extras:
        try:
            from pipeline.extras import compute_resilience
            resilience = compute_resilience(df, edges)
            if resilience:
                extras["resilience"] = resilience
        except Exception as exc:
            logging.getLogger(__name__).warning("Priority resilience unavailable: %s", exc)
    df, clusters = assign_clusters(G, df)
    top = top_nodes(df, C.TOP_N)

    write_csvs(df, clusters, top, out_dir)
    graph = build_graph_json(df, edges, clusters, compute_layout(G, dict(zip(df.gid, df.cluster_id))), extras)
    digest = hashlib.sha256()
    for filename in ("nodes.parquet", "edges.parquet", "transactions.parquet"):
        digest.update(filename.encode())
        digest.update((data_dir / filename).read_bytes())
    graph["meta"].update(dataset_version="sha256:" + digest.hexdigest(),
                         period_start=tx.date.min().date().isoformat(),
                         period_end=tx.date.max().date().isoformat(),
                         data_source="Организатор: nodes.parquet, edges.parquet, transactions.parquet")
    write_graph_json(graph, out_dir / "graph.json")
    validate(out_dir, len(nodes))
    print(f"  роли: {df.role.value_counts().to_dict()}")
    print(f"  готово за {time.time() - t0:.1f} с → {out_dir}/")
    return graph
