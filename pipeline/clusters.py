"""Кластеры: Louvain на неориентированной проекции (направление для сообществ не учитываем — оговорено в README)."""

import networkx as nx
import pandas as pd

from pipeline import config as C


def assign_clusters(G: nx.DiGraph, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    UG = G.to_undirected()
    comms = nx.community.louvain_communities(UG, weight="sum_kzt", seed=C.RANDOM_SEED)
    comms = sorted(comms, key=len, reverse=True)
    cid = {gid: i for i, c in enumerate(comms) for gid in c}

    out = df.copy()
    out["cluster_id"] = out.gid.map(cid).astype(int)

    rows = []
    for i, members in enumerate(comms):
        sub = out[out.cluster_id == i]
        internal = sum(d["sum_kzt"] for u, v, d in G.subgraph(members).edges(data=True))
        top = sub.sort_values("pagerank", ascending=False).gid.head(5).tolist()
        n_seed = int(sub.is_seed.sum())
        roles = sub.role.value_counts()
        hyp = (f"{len(sub)} узлов, {n_seed} seed; "
               f"консолидаторов {roles.get('consolidator', 0)}, "
               f"распределителей {roles.get('distributor', 0)}, транзитных {roles.get('transit', 0)}")
        rows.append({"cluster_id": i, "n_nodes": len(sub), "n_seed": n_seed,
                     "sum_kzt_internal": round(internal, 2), "top_gids": top, "hypothesis": hyp})
    return out, pd.DataFrame(rows)
