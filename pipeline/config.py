"""Все пороги и константы пайплайна — в одном месте, чтобы их можно было объяснить жюри.

Пороги по степеням задаются как max(абсолютный минимум, перцентиль распределения): на этих данных
99% узлов имеют ≤ 6 плательщиков, поэтому «много» — это хвост распределения, а не число «с потолка».
"""

ROLES = ["consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"]

ROLE_COLORS = {
    "consolidator": "#e4572e",
    "transit": "#f3a712",
    "distributor": "#2a9d8f",
    "terminal": "#457b9d",
    "coordinator": "#9d4edd",
    "peripheral": "#b0b0b0",
}

# --- consolidator: fan-in, собирает от многих ---
CONSOLIDATOR_IN_DEG_MIN = 5          # не меньше 5 разных плательщиков…
CONSOLIDATOR_IN_DEG_Q = 0.98         # …и в верхних 2% по числу плательщиков

# --- distributor: fan-out, веер на многих ---
DISTRIBUTOR_OUT_DEG_MIN = 10         # не меньше 10 разных получателей…
DISTRIBUTOR_OUT_DEG_Q = 0.97         # …и в верхних 3% по числу получателей
FAN_DOMINANCE = 2.0                  # если есть и сбор, и раздача — роль по той стороне, что больше в 2 раза

# --- transit: пропускает дальше, не удерживая ---
TRANSIT_PASS_RANGE = (0.7, 1.3)      # отдаёт дальше 70–130% полученного
FAST_FORWARD_DAYS = 2                # «сквозной» = ушло не позже 2 дней после поступления
TRANSIT_FAST_SHARE = 0.6             # ≥ 60% исходящей суммы ушло сквозным транзитом

# --- terminal: деньги пришли и остались ---
TERMINAL_MIN_IN_DEG = 2              # ≥ 2 плательщиков, или
TERMINAL_MIN_IN_KZT_Q = 0.75         # сумма входящих в верхней четверти
TRUNCATED_TERMINAL_MIN_IN_DEG = 3    # узел 4-го колена считаем стоком только при ≥ 3 плательщиках

# --- coordinator: второй уровень консолидации / связка сбор→раздача ---
COORDINATOR_MIN_UP_COLLECTORS = 2    # получает от ≥ 2 сборщиков (consolidator/transit с fan-in)
COORDINATOR_BETWEENNESS_Q = 0.99     # или: верхний 1% по посредничеству и связывает сбор с раздачей

# --- priority_score: взвешенная сумма перцентилей (сумма весов = 1) ---
PRIORITY_WEIGHTS = {
    "seed_exposure": 0.30,   # насколько узел «заражён» потоками от seed (personalized PageRank)
    "role": 0.25,            # сила роли: вес роли × role_score
    "volume": 0.20,          # объём денег через узел
    "betweenness": 0.15,     # структурная важность: через него идут пути
    "behavior": 0.10,        # поведенческие признаки: сквозной транзит, флаги extras
}
ROLE_WEIGHT = {"coordinator": 1.0, "consolidator": 0.9, "distributor": 0.8,
               "transit": 0.6, "terminal": 0.4, "peripheral": 0.1}

# признаки из pipeline/extras.py, которые показываются как флаги узла
EXTRA_FLAGS = {"fast_transit", "in_cycle", "sync_inflow"}

# русские подписи для интерфейса и ассистента (graph.json → meta)
METRIC_LABELS = {
    "in_deg": "Плательщиков", "out_deg": "Получателей",
    "in_kzt": "Входящие, ₸", "out_kzt": "Исходящие, ₸",
    "in_tx": "Входящих переводов", "out_tx": "Исходящих переводов",
    "pagerank": "Влияние (PageRank)", "pass_through": "Отдал дальше, доля от полученного",
    "seed_exposure": "Близость к seed по потоку", "n_seed_up2": "Seed в пределах 2 переводов",
    "betweenness": "Посредничество", "fast_forward_share": "Ушло дальше за ≤ 2 дня, доля",
}
FLAG_LABELS = {
    "fast_transit": "Сквозной транзит (≤ 2 дней)",
    "gather_scatter": "Сбор и раздача одновременно",
    "truncated_by_depth": "4-е колено: обход остановился",
    "isolated_seed": "Seed без переводов",
    "in_cycle": "Участвует в цикле (деньги возвращаются)",
    "sync_inflow": "Синхронные поступления (≥ 3 плательщика в день)",
}

EVIDENCE_MAX_LEN = 200
TOP_N = 50
RANDOM_SEED = 42
