"""Кластеры: Louvain на неориентированной взвешенной проекции.

Направление для поиска сообществ не учитываем (Louvain работает с неориентированным графом) —
направление денег сохраняется в ролях и в гипотезе кластера.
"""

import networkx as nx
import pandas as pd

from pipeline import config as C


def _kzt(x: float) -> str:
    return f"{x / 1e6:.1f} млн ₸" if x >= 1e6 else f"{x / 1e3:.0f} тыс ₸"


def _hypothesis(sub: pd.DataFrame, internal: float) -> str:
    r = sub.role.value_counts()
    n_seed = int(sub.is_seed.sum())
    n_coord, n_cons, n_dist, n_tr = (r.get(k, 0) for k in ("coordinator", "consolidator", "distributor", "transit"))
    if len(sub) <= 3:
        return f"Изолированный фрагмент из {len(sub)} узлов, оборот {_kzt(internal)}"
    parts = []
    if n_coord:
        parts.append(f"есть {n_coord} кандидат(ов) в координаторы — возможное ядро группы")
    if n_cons and n_seed:
        parts.append(f"сбор средств от {n_seed} seed в {n_cons} точк(и) консолидации")
    elif n_cons:
        parts.append(f"{n_cons} точк(и) консолидации")
    if n_dist:
        parts.append(f"веерная раздача через {n_dist} распределител(ей)")
    if n_tr:
        parts.append(f"{n_tr} транзитных счетов")
    if not parts:
        parts.append("периферия без выраженных ролей" + (f", {n_seed} seed" if n_seed else ""))
    return f"Гипотеза: {'; '.join(parts)}. Оборот внутри {_kzt(internal)}"


def assign_clusters(G: nx.DiGraph, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    UG = G.to_undirected()
    comms = nx.community.louvain_communities(UG, weight="sum_kzt", seed=C.RANDOM_SEED)
    comms = sorted(comms, key=lambda c: (-len(c), min(c)))
    cid = {gid: i for i, c in enumerate(comms) for gid in c}

    out = df.copy()
    out["cluster_id"] = out.gid.map(cid).astype(int)

    rank_key = "priority_score" if "priority_score" in out else "pagerank"
    rows = []
    for i, members in enumerate(comms):
        sub = out[out.cluster_id == i]
        internal = sum(d["sum_kzt"] for _, _, d in G.subgraph(members).edges(data=True))
        rows.append({
            "cluster_id": i, "n_nodes": len(sub), "n_seed": int(sub.is_seed.sum()),
            "sum_kzt_internal": round(internal, 2),
            "top_gids": sub.sort_values(rank_key, ascending=False).gid.head(5).tolist(),
            "hypothesis": _hypothesis(sub, internal),
        })
    return out, pd.DataFrame(rows)
