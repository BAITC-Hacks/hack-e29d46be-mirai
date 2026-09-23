"""priority_score: «кого смотреть первым». Взвешенная сумма перцентилей (веса — config.PRIORITY_WEIGHTS).

Компоненты нормированы в 0..1: seed/объём/посредничество — перцентили; роль и поведение — правила.
В `why` выводятся два главных вклада + роль.
"""

import numpy as np
import pandas as pd

from pipeline import config as C

LABELS = {
    "seed_exposure": "близость к seed по потоку денег",
    "role": "сила роли",
    "volume": "объём денег",
    "betweenness": "посредничество (через узел идут пути)",
    "behavior": "поведенческие признаки",
}
BEHAVIOR_FLAGS = {"gather_scatter", "in_cycle", "sync_inflow"}


def stability_scenarios():
    """One-factor ±10% relative weight changes, normalized back to sum=1."""
    base = C.PRIORITY_WEIGHTS
    scenarios = [{"name": "base", "weights": dict(base)}]
    for key in base:
        for factor in (.9, 1.1):
            weights = {k: v * (factor if k == key else 1) for k, v in base.items()}
            total = sum(weights.values())
            scenarios.append({"name": f"{key}:{factor:.1f}",
                              "weights": {k: v / total for k, v in weights.items()}})
    return scenarios


def rank_stability(df, components, top_k=20):
    """Sensitivity, not confidence or probability; components and input data stay fixed."""
    ranks = []
    gids = df.gid.to_numpy()
    for scenario in stability_scenarios():
        scores = (components * pd.Series(scenario["weights"])).sum(axis=1).round(4).to_numpy()
        order = np.lexsort((gids, -scores))
        rank = np.empty(len(df), dtype=int)
        rank[order] = np.arange(1, len(df) + 1)
        ranks.append(rank)
    matrix = np.asarray(ranks)
    return [{"top_k": top_k, "scenarios": len(ranks), "top_k_share": float((matrix[:, i] <= top_k).mean()),
             "min_rank": int(matrix[:, i].min()), "max_rank": int(matrix[:, i].max())}
            for i in range(len(df))]


def _components(df: pd.DataFrame) -> pd.DataFrame:
    comp = pd.DataFrame(index=df.index)
    comp["seed_exposure"] = df.seed_exposure.rank(pct=True) if "seed_exposure" in df else 0.0
    comp["role"] = df.role.map(C.ROLE_WEIGHT).fillna(0) * df.role_score
    comp["volume"] = np.maximum(df.in_kzt, df.out_kzt).rank(pct=True)
    comp["betweenness"] = df.betweenness.rank(pct=True) if "betweenness" in df else 0.0
    fast = df.fast_forward_share.fillna(0) if "fast_forward_share" in df else 0.0
    # Both temporal signals support one behavior family; never count it twice.
    n_flags = df["flags"].map(lambda f: len(BEHAVIOR_FLAGS & set(f))
                            + int(bool({"fast_transit", "rapid_outflow"} & set(f))))
    comp["behavior"] = np.clip(0.5 * fast + 0.25 * n_flags, 0, 1)
    return comp


def assign_priority(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    comp = _components(out)
    w = pd.Series(C.PRIORITY_WEIGHTS)
    contrib = comp[w.index] * w
    out["priority_score"] = contrib.sum(axis=1).round(4)
    out["priority_components"] = [
        [{"key": key, "label": LABELS[key], "value": float(comp.at[i, key]),
          "weight": float(w[key]), "contribution": float(contrib.at[i, key])} for key in w.index]
        for i in out.index]
    out["rank_stability"] = rank_stability(out, comp)

    top2 = contrib.apply(lambda row: row.nlargest(2).index.tolist(), axis=1)
    out["priority_why"] = [
        "; ".join(f"{LABELS[k]} — {comp.at[i, k]:.0%}" for k in ks) for i, ks in zip(out.index, top2)
    ]
    out = out.sort_values(["priority_score", "gid"], ascending=[False, True]).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out


def top_nodes(df: pd.DataFrame, n: int) -> pd.DataFrame:
    top = df.nsmallest(n, "rank")
    why = (top.role + ": " + top.evidence + " | приоритет: " + top.priority_why)
    return pd.DataFrame({"rank": top["rank"], "gid": top.gid, "role": top.role,
                         "priority_score": top.priority_score, "why": why})
