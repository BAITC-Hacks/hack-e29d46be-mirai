"""Роли узлов по прозрачным правилам. v0 — будет уточнено в #2."""

import pandas as pd

from pipeline import config as C


def _fmt_kzt(x: float) -> str:
    return f"{x / 1e6:.1f} млн ₸" if x >= 1e6 else f"{x / 1e3:.0f} тыс ₸"


def _assign(r) -> tuple[str, float, str]:
    lo, hi = C.TRANSIT_PASS_RANGE
    if r.in_deg >= C.CONSOLIDATOR_MIN_IN_DEG:
        share = 0 if pd.isna(r.pass_through) else r.pass_through
        return ("consolidator", min(1.0, r.in_deg / (2 * C.CONSOLIDATOR_MIN_IN_DEG)),
                f"Получает от {r.in_deg} разных плательщиков ({_fmt_kzt(r.in_kzt)}), "
                f"отдаёт дальше {share:.0%} полученного")
    if r.out_deg >= C.DISTRIBUTOR_MIN_OUT_DEG:
        return ("distributor", min(1.0, r.out_deg / (2 * C.DISTRIBUTOR_MIN_OUT_DEG)),
                f"Рассылает {r.out_deg} разным получателям, всего {_fmt_kzt(r.out_kzt)}")
    if r.in_deg > 0 and r.out_deg > 0 and not r.is_seed and lo <= (r.pass_through or 0) <= hi:
        return ("transit", 0.6,
                f"Пропускает дальше {r.pass_through:.0%} полученного "
                f"({_fmt_kzt(r.in_kzt)} → {_fmt_kzt(r.out_kzt)})")
    if r.in_deg > 0 and r.out_deg == 0 and not r.truncated_by_depth:
        return ("terminal", 0.5,
                f"Получил {_fmt_kzt(r.in_kzt)} от {r.in_deg} плательщиков, исходящих нет (колено {r.depth})")
    if r.truncated_by_depth:
        return ("peripheral", 0.3,
                f"Колено 4 без исходящих: обход остановился здесь, получил {_fmt_kzt(r.in_kzt)} "
                f"от {r.in_deg} плательщиков")
    return ("peripheral", 0.2,
            f"Признаков роли нет: вход {r.in_deg} ({_fmt_kzt(r.in_kzt)}), выход {r.out_deg} ({_fmt_kzt(r.out_kzt)})")


def assign_roles(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    res = [_assign(r) for r in out.itertuples(index=False)]
    out["role"] = [x[0] for x in res]
    out["role_score"] = [round(float(x[1]), 3) for x in res]
    out["evidence"] = [x[2][: C.EVIDENCE_MAX_LEN] for x in res]
    out["flags"] = [["truncated_by_depth"] if t else [] for t in out.truncated_by_depth]
    return out
