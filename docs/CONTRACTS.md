# Контракты между частями системы

**Это главный файл для параллельной работы.** Каждый строит свою часть против этих схем, а не против
чужого кода. Пока настоящих данных нет — работай с `shared/sample_graph.json` (мок в той же схеме;
его генерирует Мирас-Claude первым делом).

Изменить контракт = отдельный PR с меткой `contract` + 👍 всех троих (см. AGENTS.md).

## Архитектура

```
data/*.parquet
   │
   ▼
pipeline/  (Мирас: Claude + GPT)          python run.py  ─┐
   ├─ metrics.py   — метрики узлов                         │ 1. считает пайплайн (< 5 мин)
   ├─ roles.py     — правила ролей + evidence              │ 2. запускает сервер
   ├─ clusters.py  — Louvain + гипотезы                    │
   ├─ priority.py  — priority_score, top_nodes             │
   ├─ extras.py    — временные паттерны, циклы, устойчивость (Мирас-GPT)
   └─ export.py    — 3 CSV + outputs/graph.json            │
   │                                                       │
   ▼                                                       │
outputs/nodes_roles.csv, clusters.csv, top_nodes.csv, graph.json
   │                                                       │
   ├──────────────► app/  (Нурай)  FastAPI + static/ (HTML/JS + Cytoscape.js) ◄─┘
   │                   ├─ GET /api/graph, /api/node/{gid}, /api/search ...
   │                   └─ вызывает assistant/ как Python-функции
   └──────────────► assistant/  (Даниал)  LLM: карточки узлов, вопросы на естественном языке
```

Запуск для жюри: `pip install -r requirements.txt && python run.py` → открыть http://localhost:8000

## 1. Выходные CSV (схема из ТЗ, менять нельзя)

`outputs/nodes_roles.csv` — ровно 2 248 строк
| колонка | тип | пример |
|---|---|---|
| gid | int64 | 100245 |
| role | str | consolidator |
| role_score | float 0–1 | 0.87 |
| cluster_id | int | 3 |
| priority_score | float 0–1 | 0.91 |
| evidence | str ≤200 | «Получает от 14 разных плательщиков, отдаёт дальше 4% полученного» |

Имена метрик берём из `starter/starter.py` (`in_deg, out_deg, in_kzt, out_kzt, in_tx, out_tx, pagerank,
pass_through, truncated_by_depth`), чтобы не плодить синонимы. Лишние колонки в CSV добавлять можно
(так делает и starter), обязательные удалять нельзя.

`outputs/clusters.csv`: `cluster_id, n_nodes, n_seed, sum_kzt_internal, top_gids (через ;), hypothesis`

`outputs/top_nodes.csv` (≥ 20): `rank, gid, role, priority_score, why`

Роли: `consolidator, transit, distributor, terminal, coordinator, peripheral`.
Своя роль (например `truncated` для обрыва на 4-м колене) — только через PR `contract` и с описанием в README.

## 2. `outputs/graph.json` — для интерфейса и ассистента

```json
{
  "meta": {
    "generated_at": "2026-07-31T12:00:00",
    "n_nodes": 2248, "n_edges": 3119, "total_kzt": 365890012,
    "roles": ["consolidator","transit","distributor","terminal","coordinator","peripheral"],
    "role_colors": {"consolidator":"#e4572e","transit":"#f3a712","distributor":"#2a9d8f",
                    "terminal":"#457b9d","coordinator":"#9d4edd","peripheral":"#b0b0b0"}
  },
  "nodes": [
    {
      "id": 100245,
      "depth": 2, "is_seed": false,
      "role": "consolidator", "role_score": 0.87,
      "cluster_id": 3, "priority_score": 0.91, "rank": 1,
      "evidence": "Получает от 14 разных плательщиков, отдаёт дальше 4% полученного",
      "metrics": {
        "in_deg": 14, "out_deg": 2, "in_kzt": 12500000, "out_kzt": 500000,
        "in_tx": 31, "out_tx": 2, "pagerank": 0.004,
        "pass_through": 0.04, "n_seed_upstream": 9, "betweenness": 0.012
      },
      "flags": ["fast_transit", "in_cycle", "truncated_by_depth"],
      "x": 123.4, "y": -56.7
    }
  ],
  "edges": [
    {"source": 100245, "target": 100777, "sum_kzt": 500000, "n_tx": 3}
  ],
  "clusters": [
    {"cluster_id": 3, "n_nodes": 120, "n_seed": 7, "sum_kzt_internal": 45000000,
     "top_gids": [100245, 100777], "hypothesis": "Сбор средств от 7 seed в 2 точки консолидации"}
  ],
  "extras": {
    "resilience": [{"removed_top_n": 5, "largest_component_share": 0.61, "n_components": 34}],
    "cycles": [[100245, 100777, 100900, 100245]]
  }
}
```

Правила:
- `x`, `y` — координаты раскладки, **посчитанные в пайплайне** (браузер не раскладывает 2 248 узлов сам — тормозит).
- Любое поле в `metrics`, `flags`, `extras` опционально: интерфейс и ассистент **не падают**, если его нет.
- Добавлять новые поля можно без PR `contract` (обратно совместимо). Удалять/переименовывать — только через `contract`.

## 3. HTTP API (владелец — Нурай, `app/`)

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/` | index.html |
| GET | `/api/graph` | весь graph.json |
| GET | `/api/node/{gid}` | узел + входящие/исходящие рёбра + соседи |
| GET | `/api/search?q=1002` | до 20 узлов, чей gid содержит строку |
| GET | `/api/top?n=20` | top_nodes |
| GET | `/api/node/{gid}/card` | `{"text": "...", "source": "llm" \| "template"}` — вызывает `assistant.node_card` |
| POST | `/api/ask` `{"question": "..."}` | `{"answer": "...", "cited_gids": [..], "source": "llm" \| "fallback"}` — вызывает `assistant.ask` |

## 4. Python-интерфейс ассистента (владелец — Даниал, `assistant/`)

```python
# assistant/__init__.py
from assistant.core import node_card, ask

def node_card(gid: int, graph: dict) -> dict:
    """{'text': str, 'source': 'llm' | 'template'} — всегда отвечает, даже без API-ключа."""

def ask(question: str, graph: dict) -> dict:
    """{'answer': str, 'cited_gids': list[int], 'source': 'llm' | 'fallback'}"""
```
- `graph` — распарсенный `outputs/graph.json`.
- Нет ключа / ошибка API → шаблонный ответ из метрик, **никаких исключений наружу**.
- Провайдер через `.env`: `LLM_PROVIDER=nvidia|openai|anthropic|none`.

## 5. Интерфейс extras (внутри зоны Мираса)

```python
# pipeline/extras.py  (Мирас-GPT)
def compute_extras(nodes: pd.DataFrame, edges: pd.DataFrame, tx: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    per_node: DataFrame[gid, fast_transit_share, sync_in_days, in_cycle, likely_true_terminal, ...]
    global_:  {"resilience": [...], "cycles": [...]}
    """
```
Ядро вызывает его в try/except: если extras упал — пайплайн всё равно отрабатывает.

## 6. Общие файлы
`requirements.txt` (один на всех), `run.py`, `.env.example`, `docs/CONTRACTS.md`, `shared/` — через PR `contract`.
Нужна библиотека → issue `for:miras` или маленький PR `contract` только с requirements.txt.
