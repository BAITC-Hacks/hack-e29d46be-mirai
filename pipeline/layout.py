"""Координаты раскладки для интерфейса (браузер не раскладывает 2 248 узлов сам)."""

import networkx as nx

from pipeline import config as C


def compute_layout(G: nx.DiGraph, scale: float = 2000.0) -> dict:
    pos = nx.spring_layout(G.to_undirected(), seed=C.RANDOM_SEED, scale=scale, iterations=50)
    return {n: (round(float(x), 1), round(float(y), 1)) for n, (x, y) in pos.items()}
