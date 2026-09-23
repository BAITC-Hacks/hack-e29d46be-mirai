"""Приоритет для аналитика. v0: перцентиль PageRank; формула с весами — в #3."""

import pandas as pd

ROLE_BONUS = {"coordinator": 0.3, "consolidator": 0.25, "distributor": 0.2,
              "transit": 0.1, "terminal": 0.05, "peripheral": 0.0}


def assign_priority(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    pr_pct = out.pagerank.rank(pct=True)
    raw = 0.7 * pr_pct + out.role.map(ROLE_BONUS).fillna(0)
    out["priority_score"] = (raw / raw.max()).round(4)
    out = out.sort_values(["priority_score", "gid"], ascending=[False, True]).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out


def top_nodes(df: pd.DataFrame, n: int) -> pd.DataFrame:
    top = df.nsmallest(n, "rank")
    return pd.DataFrame({"rank": top["rank"], "gid": top.gid, "role": top.role,
                         "priority_score": top.priority_score, "why": top.evidence})
