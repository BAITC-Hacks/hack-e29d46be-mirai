"""Граф и метрики узлов. Базовые метрики — как в starter/starter.py, имена совпадают."""

import networkx as nx
import numpy as np
import pandas as pd


def build_graph(edges: pd.DataFrame, nodes: pd.DataFrame) -> nx.DiGraph:
    """Направленный граф; узлы без рёбер (19 seed) тоже добавлены."""
    G = nx.DiGraph()
    G.add_nodes_from(nodes.gid.tolist())
    for r in edges.itertuples(index=False):
        G.add_edge(r.src, r.dst, sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx), depth=int(r.depth))
    return G


def node_metrics(G: nx.DiGraph, nodes: pd.DataFrame) -> pd.DataFrame:
    df = nodes[["gid", "depth", "is_seed"]].copy()
    df["in_deg"] = df.gid.map(dict(G.in_degree())).fillna(0).astype(int)
    df["out_deg"] = df.gid.map(dict(G.out_degree())).fillna(0).astype(int)
    df["in_kzt"] = df.gid.map(dict(G.in_degree(weight="sum_kzt"))).fillna(0.0)
    df["out_kzt"] = df.gid.map(dict(G.out_degree(weight="sum_kzt"))).fillna(0.0)
    df["in_tx"] = df.gid.map(dict(G.in_degree(weight="n_tx"))).fillna(0).astype(int)
    df["out_tx"] = df.gid.map(dict(G.out_degree(weight="n_tx"))).fillna(0).astype(int)
    df["pagerank"] = df.gid.map(nx.pagerank(G, weight="sum_kzt")).fillna(0.0)
    df["pass_through"] = np.where(df.in_kzt > 0, df.out_kzt / df.in_kzt.replace(0, np.nan), np.nan)
    df["truncated_by_depth"] = (df.depth == 4) & (df.out_deg == 0)
    return df
