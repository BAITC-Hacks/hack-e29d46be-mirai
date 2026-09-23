"""Загрузка parquet и проверка консистентности (на основе starter/starter.py)."""

from pathlib import Path

import pandas as pd
import numpy as np


def load(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    edges = pd.read_parquet(data_dir / "edges.parquet")
    nodes = pd.read_parquet(data_dir / "nodes.parquet")
    tx = pd.read_parquet(data_dir / "transactions.parquet")
    tx["date"] = pd.to_datetime(tx["date"])
    return edges, nodes, tx


def sanity_check(edges: pd.DataFrame, nodes: pd.DataFrame, tx: pd.DataFrame) -> None:
    for frame, columns in ((nodes, ["gid", "depth", "is_seed"]),
                           (edges, ["src", "dst", "sum_kzt", "n_tx", "depth"]),
                           (tx, ["src", "dst", "sum_kzt", "date"])):
        if not set(columns) <= set(frame) or frame[columns].isna().any().any():
            raise ValueError("Во входных данных отсутствуют обязательные поля или значения")
    if nodes.gid.duplicated().any() or edges.duplicated(["src", "dst"]).any():
        raise ValueError("Повторяющиеся gid или агрегированные рёбра")
    for frame in (edges, tx):
        if not np.isfinite(frame.sum_kzt).all() or (frame.sum_kzt <= 0).any():
            raise ValueError("Суммы переводов должны быть конечными и положительными")
    agg = tx.groupby(["src", "dst"]).agg(c=("sum_kzt", "size"), s=("sum_kzt", "sum")).reset_index()
    merged = edges.merge(agg, on=["src", "dst"], how="outer", indicator=True)
    if not (merged["_merge"] == "both").all():
        raise ValueError("edges и transactions не сходятся по парам")
    if not (merged.n_tx == merged.c).all() or not np.allclose(merged.sum_kzt, merged.s, rtol=1e-9, atol=0.01):
        raise ValueError("edges и transactions не сходятся по суммам или числу переводов")

    unknown = (set(edges.src) | set(edges.dst)) - set(nodes.gid)
    if unknown:
        raise ValueError(f"{len(unknown)} gid из рёбер отсутствуют в nodes.parquet")

    print(f"  данные: {len(nodes)} узлов, {len(edges)} рёбер, {len(tx)} транзакций, "
          f"{int(nodes.is_seed.sum())} seed, {tx.date.min().date()} — {tx.date.max().date()}")
