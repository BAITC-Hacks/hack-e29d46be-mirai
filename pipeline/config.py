"""Все пороги и константы пайплайна — в одном месте, чтобы их можно было объяснить жюри."""

ROLES = ["consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"]

ROLE_COLORS = {
    "consolidator": "#e4572e",
    "transit": "#f3a712",
    "distributor": "#2a9d8f",
    "terminal": "#457b9d",
    "coordinator": "#9d4edd",
    "peripheral": "#b0b0b0",
}

# v0-пороги (будут откалиброваны по перцентилям в #2)
CONSOLIDATOR_MIN_IN_DEG = 8        # получает от ≥ 8 разных плательщиков
DISTRIBUTOR_MIN_OUT_DEG = 20       # отправляет ≥ 20 разным получателям
TRANSIT_PASS_RANGE = (0.8, 1.2)    # отдаёт дальше 80–120% полученного

EVIDENCE_MAX_LEN = 200
TOP_N = 50
RANDOM_SEED = 42
