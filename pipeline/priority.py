"""priority_score: «кого смотреть первым». Взвешенная сумма перцентилей (веса — config.PRIORITY_WEIGHTS).

Каждая компонента — перцентиль 0..1, поэтому вклад понятен: «в верхних 3% по близости к seed».
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
