"""Координаты для интерфейса: каждый кластер раскладывается отдельно, кластеры стоят спиралью от центра.

Крупные кластеры — в центре, мелкие фрагменты — по краям. Так структура видна сразу,
без «комка» из 2 248 узлов (браузер не раскладывает граф сам — layout "preset").
"""

import math

import networkx as nx

from pipeline import config as C
from pipeline.clusters import undirected_projection


def compute_layout(G: nx.DiGraph, cluster_of: dict | None = None, unit: float = 22.0) -> dict:
    """cluster_of: {gid: cluster_id}. Без него — один общий spring layout."""
    UG = undirected_projection(G)
    if cluster_of is None:
        groups = [set(G.nodes)]
    else:
        by = {}
        for g, c in cluster_of.items():
            by.setdefault(c, set()).add(g)
        groups = list(by.values())
    groups = sorted(groups, key=lambda s: (-len(s), min(s)))

    pos, placed = {}, []  # placed: (cx, cy, radius)
    for k, members in enumerate(groups):
        radius = unit * math.sqrt(len(members)) * 1.6 + unit
        sub = UG.subgraph(members)
        local = (nx.spring_layout(sub, seed=C.RANDOM_SEED, iterations=60, scale=radius, weight=None)
                 if len(members) > 1 else {next(iter(members)): (0.0, 0.0)})
        cx, cy = _place(placed, radius)
        placed.append((cx, cy, radius))
        for n, (x, y) in local.items():
            pos[n] = (round(cx + float(x), 1), round(cy + float(y), 1))
    return pos


def _place(placed: list, radius: float) -> tuple[float, float]:
    """Ставим круг кластера на спираль, пока он не перестанет пересекаться с уже поставленными."""
    if not placed:
        return 0.0, 0.0
    step = 0.0
    while True:
        step += 0.35
        r = 40.0 * step
        x, y = r * math.cos(step), r * math.sin(step)
        if all(math.hypot(x - px, y - py) >= radius + pr + 30 for px, py, pr in placed):
            return x, y
