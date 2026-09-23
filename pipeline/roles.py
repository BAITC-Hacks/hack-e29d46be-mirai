"""Роли узлов по прозрачным правилам с порогами из config.py.

Порядок проверки (первое сработавшее правило):
  1. consolidator / distributor — fan-in / fan-out в хвосте распределения
  2. transit      — пропускает 70–130% полученного или ≥ 60% уходит в течение 2 дней
  3. terminal     — исходящих нет и есть признаки стока (обрыв 4-го колена — только при сильных признаках)
  4. peripheral   — остальное
  5. coordinator  — второй проход: узел над сборщиками (получает от ≥ 2) или связка сбор → узел → раздача
"""

import networkx as nx
import numpy as np
import pandas as pd

from pipeline import config as C


def _kzt(x: float) -> str:
    if x >= 1e6:
        return f"{x / 1e6:.1f} млн ₸"
    return f"{x / 1e3:.0f} тыс ₸"


def _pct(x: float) -> str:
    return "—" if x is None or np.isnan(x) else f"{x:.0%}"


def thresholds(df: pd.DataFrame) -> dict:
    return {
        "cons_in": max(C.CONSOLIDATOR_IN_DEG_MIN, float(df.in_deg.quantile(C.CONSOLIDATOR_IN_DEG_Q))),
        "dist_out": max(C.DISTRIBUTOR_OUT_DEG_MIN, float(df.out_deg.quantile(C.DISTRIBUTOR_OUT_DEG_Q))),
        "term_in_kzt": float(df.loc[df.in_kzt > 0, "in_kzt"].quantile(C.TERMINAL_MIN_IN_KZT_Q)),
        "betw": float(df.betweenness.quantile(C.COORDINATOR_BETWEENNESS_Q)) if "betweenness" in df else np.inf,
    }


def _first_pass(r, t: dict) -> tuple[str, float, str, list]:
    flags = []
    seed_note = " (seed: входящие занижены выгрузкой)" if r.is_seed else ""
    fast = getattr(r, "fast_forward_share", np.nan)
    fan_in, fan_out = r.in_deg >= t["cons_in"], r.out_deg >= t["dist_out"]

    if fan_in and fan_out:
        flags.append("gather_scatter")
    if fan_in and not (fan_out and r.out_deg > C.FAN_DOMINANCE * r.in_deg):
        score = min(1.0, 0.5 + 0.5 * (r.in_deg - t["cons_in"]) / max(t["cons_in"], 1))
        tail = f", раздаёт {r.out_deg} получателям" if fan_out else f", отдаёт дальше {_pct(r.pass_through)}"
        return ("consolidator", score,
                f"Сбор от {r.in_deg} разных плательщиков ({_kzt(r.in_kzt)}; порог ≥{t['cons_in']:.0f}){tail}{seed_note}",
                flags)
    if fan_out:
        score = min(1.0, 0.5 + 0.5 * (r.out_deg - t["dist_out"]) / max(t["dist_out"], 1))
        return ("distributor", score,
                f"Веер на {r.out_deg} получателей ({_kzt(r.out_kzt)}; порог ≥{t['dist_out']:.0f}), "
                f"входящих от {r.in_deg}{seed_note}", flags)

    lo, hi = C.TRANSIT_PASS_RANGE
    if r.in_deg > 0 and r.out_deg > 0 and not r.is_seed:
        balanced = not np.isnan(r.pass_through) and lo <= r.pass_through <= hi
        quick = not np.isnan(fast) and fast >= C.TRANSIT_FAST_SHARE
        if balanced or quick:
            if quick:
                flags.append("fast_transit")
            score = 0.5 + 0.25 * balanced + 0.25 * quick
            parts = [f"Отдаёт дальше {_pct(r.pass_through)} полученного ({_kzt(r.in_kzt)} → {_kzt(r.out_kzt)})"]
            if quick:
                parts.append(f"{_pct(fast)} ушло в течение {C.FAST_FORWARD_DAYS} дн. после поступления")
            return ("transit", score, "; ".join(parts), flags)

    if r.out_deg == 0 and r.in_deg > 0:
        if r.truncated_by_depth:
            flags.append("truncated_by_depth")
            if r.in_deg >= C.TRUNCATED_TERMINAL_MIN_IN_DEG:
                return ("terminal", 0.4,
                        f"Получил {_kzt(r.in_kzt)} от {r.in_deg} плательщиков; исходящих в выгрузке нет, "
                        f"но это 4-е колено — сток вероятен, не доказан", flags)
            return ("peripheral", 0.3,
                    f"4-е колено: обход остановился здесь (исходящие не выгружались); "
                    f"получил {_kzt(r.in_kzt)} от {r.in_deg}", flags)
        if r.in_deg >= C.TERMINAL_MIN_IN_DEG or r.in_kzt >= t["term_in_kzt"]:
            score = min(1.0, 0.5 + 0.1 * r.in_deg)
            return ("terminal", score,
                    f"Получил {_kzt(r.in_kzt)} от {r.in_deg} плательщиков и не переводил дальше "
                    f"(колено {r.depth} — обход продолжался бы)", flags)
        return ("peripheral", 0.2, f"Разовый получатель: {_kzt(r.in_kzt)} от {r.in_deg}, дальше не переводил", flags)

    if r.is_seed and r.in_deg == 0 and r.out_deg == 0:
        return ("peripheral", 0.1, "Seed без переводов ≥ 5 000 ₸ внутри банка за июль", flags + ["isolated_seed"])
    return ("peripheral", 0.2,
            f"Признаков роли нет: вход {r.in_deg} ({_kzt(r.in_kzt)}), выход {r.out_deg} ({_kzt(r.out_kzt)})"
            f"{seed_note}", flags)


def _coordinators(G: nx.DiGraph, df: pd.DataFrame, t: dict) -> dict:
    """Второй проход: кандидаты в организаторы — над сборщиками или между сбором и раздачей."""
    role = dict(zip(df.gid, df.role))
    collectors = {g for g, r in role.items() if r == "consolidator"}
    distributors = {g for g, r in role.items() if r == "distributor"}
    betw = dict(zip(df.gid, df.betweenness)) if "betweenness" in df else {}
    out = {}
    for g in df.gid:
        if role[g] in ("terminal",):
            continue
        up_coll = [p for p in G.predecessors(g) if p in collectors]
        down_dist = [s for s in G.successors(g) if s in distributors]
        flow = f"вход {G.in_degree(g)} ({_kzt(G.in_degree(g, weight='sum_kzt'))}), выход {G.out_degree(g)}"
        if len(up_coll) >= C.COORDINATOR_MIN_UP_COLLECTORS:
            out[g] = (0.9, f"Получает от {len(up_coll)} точек сбора — второй уровень консолидации; {flow}")
        elif up_coll and down_dist:
            out[g] = (0.8, f"Связка сбор→раздача: получает от точки сбора, передаёт {len(down_dist)} "
                           f"распределителям; {flow}")
        elif (role[g] in ("consolidator", "distributor") and betw.get(g, 0) >= t["betw"]
              and (up_coll or down_dist)):
            out[g] = (0.7, f"Верхний 1% по посредничеству, связан с {len(up_coll) + len(down_dist)} "
                           f"ключевыми узлами; {flow}")
    return out


def assign_roles(df: pd.DataFrame, G: nx.DiGraph | None = None) -> pd.DataFrame:
    out = df.copy()
    t = thresholds(out)
    res = [_first_pass(r, t) for r in out.itertuples(index=False)]
    out["role"] = [x[0] for x in res]
    out["role_score"] = [round(float(x[1]), 3) for x in res]
    out["evidence"] = [x[2] for x in res]
    out["flags"] = [x[3] for x in res]

    if G is not None:
        for g, (score, ev) in _coordinators(G, out, t).items():
            i = out.index[out.gid == g][0]
            prev = out.at[i, "role"]
            out.at[i, "role"] = "coordinator"
            out.at[i, "role_score"] = score
            names = {"consolidator": "сборщик", "distributor": "распределитель", "transit": "транзит"}
            out.at[i, "evidence"] = ev + (f"; сам — {names[prev]}" if prev in names else "")

    out["evidence"] = out.evidence.str.slice(0, C.EVIDENCE_MAX_LEN)
    return out
