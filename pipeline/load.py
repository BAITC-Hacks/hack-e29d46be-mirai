"""Загрузка parquet и проверка консистентности (на основе starter/starter.py)."""

from pathlib import Path

import pandas as pd


def load(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    edges = pd.read_parquet(data_dir / "edges.parquet")
    nodes = pd.read_parquet(data_dir / "nodes.parquet")
    tx = pd.read_parquet(data_dir / "transactions.parquet")
    tx["date"] = pd.to_datetime(tx["date"])
    return edges, nodes, tx


def sanity_check(edges: pd.DataFrame, nodes: pd.DataFrame, tx: pd.DataFrame) -> None:
    agg = tx.groupby(["src", "dst"]).size().reset_index(name="c")
    merged = edges.merge(agg, on=["src", "dst"], how="outer", indicator=True)
    if not (merged["_merge"] == "both").all():
        raise ValueError("edges и transactions не сходятся по парам")

    unknown = (set(edges.src) | set(edges.dst)) - set(nodes.gid)
    if unknown:
        raise ValueError(f"{len(unknown)} gid из рёбер отсутствуют в nodes.parquet")

    print(f"  данные: {len(nodes)} узлов, {len(edges)} рёбер, {len(tx)} транзакций, "
          f"{int(nodes.is_seed.sum())} seed, {tx.date.min().date()} — {tx.date.max().date()}")
