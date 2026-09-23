"""Выгрузки: 3 CSV в схеме ТЗ + graph.json для интерфейса и ассистента (docs/CONTRACTS.md)."""

import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

from pipeline import config as C

METRIC_COLS = ["in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx", "pagerank", "pass_through"]
NODES_ROLES_COLS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if hasattr(v, "item"):
        return _clean(v.item())
    return v


def write_csvs(df: pd.DataFrame, clusters: pd.DataFrame, top: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    extra = [c for c in METRIC_COLS + ["depth", "is_seed", "truncated_by_depth"] if c in df]
    df[NODES_ROLES_COLS + extra].sort_values("gid").to_csv(out_dir / "nodes_roles.csv", index=False)
    cl = clusters.copy()
    cl["top_gids"] = cl.top_gids.map(lambda g: ";".join(map(str, g)))
    cl.to_csv(out_dir / "clusters.csv", index=False)
    top.to_csv(out_dir / "top_nodes.csv", index=False)


def build_graph_json(df: pd.DataFrame, edges: pd.DataFrame, clusters: pd.DataFrame,
                     layout: dict, extras: dict | None = None) -> dict:
    nodes = []
    for r in df.itertuples(index=False):
        x, y = layout.get(r.gid, (0.0, 0.0))
        nodes.append({
            "id": str(r.gid), "depth": int(r.depth), "is_seed": bool(r.is_seed),
            "role": r.role, "role_score": float(r.role_score), "cluster_id": int(r.cluster_id),
            "priority_score": float(r.priority_score), "rank": int(r.rank), "evidence": r.evidence,
            "metrics": {c: _clean(getattr(r, c)) for c in METRIC_COLS if hasattr(r, c)},
            "flags": list(r.flags) if hasattr(r, "flags") else [],
            "x": x, "y": y,
        })
    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "n_nodes": len(df), "n_edges": len(edges), "total_kzt": _clean(float(edges.sum_kzt.sum())),
            "roles": C.ROLES, "role_colors": C.ROLE_COLORS,
        },
        "nodes": nodes,
        "edges": [{"source": str(e.src), "target": str(e.dst), "sum_kzt": _clean(float(e.sum_kzt)),
                   "n_tx": int(e.n_tx)} for e in edges.itertuples(index=False)],
        "clusters": [{k: _clean(v) if k != "top_gids" else [str(g) for g in v] for k, v in row.items()}
                     for row in clusters.to_dict("records")],
        "extras": extras or {},
    }


def write_graph_json(graph: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")


def validate(out_dir: Path, n_nodes: int) -> None:
    nr = pd.read_csv(out_dir / "nodes_roles.csv")
    top = pd.read_csv(out_dir / "top_nodes.csv")
    cl = pd.read_csv(out_dir / "clusters.csv")
    problems = []
    if len(nr) != n_nodes:
        problems.append(f"nodes_roles.csv: {len(nr)} строк вместо {n_nodes}")
    if nr[NODES_ROLES_COLS].isna().any().any() or (nr.evidence.str.len() == 0).any():
        problems.append("nodes_roles.csv: есть пустые обязательные поля")
    if not nr.role.isin(C.ROLES).all():
        problems.append("nodes_roles.csv: роль вне словаря")
    if (nr.evidence.str.len() > C.EVIDENCE_MAX_LEN).any():
        problems.append("nodes_roles.csv: evidence длиннее 200 символов")
    if len(top) < 20:
        problems.append(f"top_nodes.csv: {len(top)} строк (< 20)")
    if not set(nr.cluster_id) <= set(cl.cluster_id):
        problems.append("cluster_id из nodes_roles.csv отсутствуют в clusters.csv")
    if problems:
        raise ValueError("Проверка выгрузок не пройдена:\n  " + "\n  ".join(problems))
    print(f"  проверка выгрузок: OK ({len(nr)} узлов, {len(cl)} кластеров, топ {len(top)})")
