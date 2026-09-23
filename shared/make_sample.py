#!/usr/bin/env python3
"""Генерирует shared/sample_graph.json — синтетический мок в схеме graph.json (CONTRACTS.md §2).

Прогоняет синтетические данные через тот же пайплайн, поэтому схема мока совпадает с настоящей.
Запуск: python shared/make_sample.py
"""

import random
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.clusters import assign_clusters  # noqa: E402
from pipeline.export import build_graph_json, write_graph_json  # noqa: E402
from pipeline.layout import compute_layout  # noqa: E402
from pipeline.metrics import build_graph, node_metrics  # noqa: E402
from pipeline.priority import assign_priority  # noqa: E402
from pipeline.roles import assign_roles  # noqa: E402

rng = random.Random(7)
edges, depth = [], {}
gid = iter(range(900001, 999999))


def add(src, dst, depth_):
    edges.append((src, dst, rng.randint(50, 900) * 1000.0, rng.randint(1, 4), depth_))
    depth.setdefault(dst, depth_)


for group in range(3):
    seeds = [next(gid) for _ in range(4)]
    feeders = [next(gid) for _ in range(5)]
    for s in seeds + feeders:
        depth[s] = 0
    cons = next(gid)                        # consolidator: собирает от многих
    for s in seeds + feeders:
        add(s, cons, 1)
    trans = next(gid)                       # transit: пропускает дальше
    edges.append((cons, trans, 2_000_000.0, 2, 2)); depth[trans] = 2
    dist = next(gid)                        # distributor: веер
    edges.append((trans, dist, 1_950_000.0, 2, 3)); depth[dist] = 3
    for _ in range(21):
        add(dist, next(gid), 4)             # хвост 4-го колена (truncated_by_depth)
    add(cons, next(gid), 2)                 # terminal: пришло и осталось

nodes = pd.DataFrame({"gid": list(depth), "depth": list(depth.values())})
nodes["is_seed"] = nodes.gid.isin([g for g, d in depth.items() if d == 0][::2])
edges_df = pd.DataFrame(edges, columns=["src", "dst", "sum_kzt", "n_tx", "depth"])
edges_df = edges_df.groupby(["src", "dst"], as_index=False).agg(
    sum_kzt=("sum_kzt", "sum"), n_tx=("n_tx", "sum"), depth=("depth", "min"))

G = build_graph(edges_df, nodes)
df = assign_roles(node_metrics(G, nodes))
# в моке один консолидатор помечен coordinator, чтобы в интерфейсе были видны все 6 ролей
first_cons = df.index[df.role == "consolidator"][0]
df.loc[first_cons, ["role", "evidence"]] = ["coordinator", "МОК: координирующий узел, связывает цепочки"]
df, clusters = assign_clusters(G, df)
df = assign_priority(df)
graph = build_graph_json(df, edges_df, clusters, compute_layout(G, scale=600),
                         {"resilience": [{"removed_top_n": 3, "largest_component_share": 0.4, "n_components": 9}],
                          "cycles": []})
graph["meta"]["mock"] = True
write_graph_json(graph, ROOT / "shared" / "sample_graph.json")
print(f"sample_graph.json: {len(graph['nodes'])} узлов, {len(graph['edges'])} рёбер, "
      f"роли {df.role.value_counts().to_dict()}")
