"""Граф и метрики узлов. Базовые метрики — как в starter/starter.py, имена совпадают."""

from collections import defaultdict

import networkx as nx
import numpy as np
import pandas as pd

from pipeline import config as C


def build_graph(edges: pd.DataFrame, nodes: pd.DataFrame) -> nx.DiGraph:
    """Направленный граф; узлы без рёбер (19 seed) тоже добавлены."""
    G = nx.DiGraph()
    G.add_nodes_from(nodes.gid.tolist())
    for r in edges.itertuples(index=False):
        G.add_edge(r.src, r.dst, sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx), depth=int(r.depth))
    return G


def _seeds_within(G: nx.DiGraph, seeds: list, hops: int) -> dict:
    """Сколько разных seed достают до узла по исходящим переводам не более чем за `hops` шагов."""
    cnt = defaultdict(int)
    for s in seeds:
        for v in nx.single_source_shortest_path_length(G, s, cutoff=hops):
            if v != s:
                cnt[v] += 1
    return cnt


def _fast_forward_share(tx: pd.DataFrame, window_days: int) -> dict:
    """Доля исходящей суммы узла, ушедшая не позже `window_days` дней после какого-либо входящего перевода.

    Сквозной транзит: деньги пришли и почти сразу ушли дальше, не задерживаясь на счёте.
    """
    incoming = tx.groupby("dst").date.apply(lambda s: np.sort(s.values.astype("datetime64[D]")))
    window = np.timedelta64(window_days, "D")
    fast, total = defaultdict(float), defaultdict(float)
    for r in tx.itertuples(index=False):
        total[r.src] += r.sum_kzt
        ins = incoming.get(r.src)
        if ins is None:
            continue
        d = np.datetime64(r.date, "D")
        i = np.searchsorted(ins, d, side="right") - 1      # последний входящий не позже исходящего
        if i >= 0 and d - ins[i] <= window:
            fast[r.src] += r.sum_kzt
    return {g: fast[g] / total[g] for g in total if total[g] > 0}


def node_metrics(G: nx.DiGraph, nodes: pd.DataFrame, tx: pd.DataFrame | None = None) -> pd.DataFrame:
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

    seeds = df.loc[df.is_seed, "gid"].tolist()
    # близость к seed по потоку денег: PageRank с телепортацией только в seed (taint-анализ)
    ppr = nx.pagerank(G, weight="sum_kzt", personalization={s: 1.0 for s in seeds})
    df["seed_exposure"] = df.gid.map(ppr).fillna(0.0)
    df["n_seed_up2"] = df.gid.map(_seeds_within(G, seeds, 2)).fillna(0).astype(int)
    df["betweenness"] = df.gid.map(nx.betweenness_centrality(G)).fillna(0.0)
    if tx is not None:
        df["fast_forward_share"] = df.gid.map(_fast_forward_share(tx, C.FAST_FORWARD_DAYS))
    return df
