# Установка и стартовые промпты

## Часть 1. Установка (прямо сейчас, ~15 минут)

Общее для всех: принять приглашение в репозиторий (почта или github.com/notifications),
установить **Codex** (https://developers.openai.com/codex) и войти аккаунтом ChatGPT.

### 🍎 Нурай (macOS) — в Терминале
```bash
python3 --version                  # нужно 3.11+; нет — поставить с python.org
brew install gh || echo "без Homebrew: скачать gh с https://cli.github.com"
gh auth login                      # GitHub.com → HTTPS → Login with a web browser
gh repo clone BAITC-Hacks/hack-e29d46be-mirai
cd hack-e29d46be-mirai
python3 -m venv .venv
source .venv/bin/activate
pip install -r starter/requirements.txt
python starter/starter.py --data data --out out   # проверка: печатает «ПРОВЕРКА ДАННЫХ … OK»
cp .env.example .env
codex                              # запускать ВСЕГДА из папки репозитория
```

### 🪟 Даниал (Windows) — в PowerShell
```powershell
python --version                   # нужно 3.11+; нет — поставить с python.org (галочка "Add python.exe to PATH")
winget install --id Git.Git -e
winget install --id GitHub.cli -e
# после установки закрыть и заново открыть PowerShell
gh auth login                      # GitHub.com → HTTPS → Login with a web browser
gh repo clone BAITC-Hacks/hack-e29d46be-mirai
cd hack-e29d46be-mirai
python -m venv .venv
.venv\Scripts\Activate.ps1         # ошибка про политику? выполнить: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r starter/requirements.txt
python starter/starter.py --data data --out out   # проверка: печатает «ПРОВЕРКА ДАННЫХ … OK»
copy .env.example .env
codex                              # запускать ВСЕГДА из папки репозитория
```
Особенности Windows (агент Даниала должен их учитывать): пути через `pathlib`, файлы открывать с
`encoding="utf-8"` (иначе кириллица ломается), команды в инструкциях — PowerShell, а не bash.

### 🔑 Ключ NVIDIA
Ключ (`nvapi-...`) создаётся на https://build.nvidia.com → профиль → API Keys. У Мираса есть доступ к организации.
Мирас передаёт ключ **лично** (не в git, не в issues). Каждый вписывает его в свой `.env`:
```
LLM_PROVIDER=nvidia
NVIDIA_API_KEY=nvapi-...
```

---

## Часть 2. Стартовые промпты

Скопировать свой промпт целиком и отправить агенту первым сообщением.

### 🟣 Мирас → Claude Code (`miras-claude`)

```
Ты — агент "miras-claude" в команде из трёх человек на хакатоне HackAlem AI, кейс «Граф денег».
Мой GitHub: @ausmiras-glitch. Параллельно работают агенты
nurai (@nqori, macOS) и danial (@dnurboluly01-cmd, Windows — код должен работать и там).
Хакатон идёт до 18:00; фундамент нужен в main к 14:40 — таймлайн в docs/PLAN.md.

Прочитай по порядку: AGENTS.md, docs/CASE.md, docs/CONTRACTS.md, docs/PLAN.md,
data/README.md, starter/README.md, starter/starter.py.

Твоя зона: pipeline/ (кроме extras.py), run.py, requirements.txt, shared/, README.md, docs/.
Твои задачи — раздел «Мирас-Claude» в docs/PLAN.md.

САМОЕ СРОЧНОЕ (другие ждут): задача 1 «Фундамент» — requirements.txt, run.py, каркас pipeline/
(переиспользуй загрузку, проверки и базовые метрики из starter/starter.py), shared/sample_graph.json
(~60 узлов, все поля из CONTRACTS.md §2, все 6 ролей, 3 кластера, правдоподобные gid и суммы).
PR → я смержу → оставь комментарий в issues nurai и danial, что мок готов.

Дальше — ядро: метрики → роли → кластеры → приоритет → экспорт. Принципы:
- каждая роль = формальное правило с порогом; пороги в одном месте (pipeline/config.py),
  подобраны по распределению данных (перцентили), evidence — с конкретными числами;
- учти все ловушки из docs/CASE.md и starter/README.md (обрыв на 4-м колене, заниженные входящие
  у seed, сумма vs количество переводов, направленность графа);
- формулировки — гипотезы («признаки консолидации»), не обвинения;
- ничего не хардкодь под конкретные gid;
- пайплайн < 5 минут и сам проверяет выходы (2 248 строк, нет пустых полей, top ≥ 20).

ПЕРЕД НАЧАЛОМ задай мне вопросы по всему, что неясно. Как минимум:
1) вводим отдельную роль для узлов, обрезанных 4-м коленом, или peripheral + флаг truncated_by_depth?
2) как определяем coordinator — предложи 2 варианта правила с плюсами/минусами;
3) веса в формуле priority_score — покажи предложение до реализации;
4) какой алгоритм раскладки для x/y (быстро и читаемо на 2 248 узлах).
По ходу: если решение затрагивает других (контракт, формат) — сначала спроси меня.
```

### 🩷 Нурай → Codex (`nurai`)

```
Ты — агент "nurai" в команде из трёх человек на хакатоне HackAlem AI, кейс «Граф денег».
Меня зовут Нурай, мой GitHub: @nqori. Я вайбкодю: объясняй простыми словами, что делаешь,
и как проверить результат в браузере. У меня macOS. Хакатон идёт до 18:00 — таймлайн в docs/PLAN.md.
Параллельно работают агенты miras-claude (@ausmiras-glitch) и danial (@dnurboluly01-cmd).

Прочитай: AGENTS.md, docs/CASE.md, docs/CONTRACTS.md (§2 и §3 — твоё), docs/PLAN.md.

Твоя зона: ТОЛЬКО app/ — app/server.py (FastAPI) и app/static/ (HTML/CSS/JS без сборки;
Cytoscape.js скачать в app/static/vendor/, чтобы работало без интернета). Ветки: nurai/<номер-issue>-<кратко>.

Задача — раздел «Нурай» в docs/PLAN.md: экран для AML-аналитика, отвечающий на вопрос
«кого смотреть первым и почему». На защите жюри называет gid → мы находим его на схеме и показываем
связи, поэтому поиск и фокус на узле должны работать безупречно.
Данные: outputs/graph.json, а если его ещё нет — shared/sample_graph.json (мок).
Координаты x/y уже посчитаны пайплайном — layout "preset", раскладку в браузере не считать.
Ассистента (assistant.node_card, assistant.ask) вызывай из server.py как Python-функции;
если модуля ещё нет — возвращай заглушку, не падай.

Дизайн: профессиональный инструмент аналитика (в духе Linear/Palantir), не «студенческий проект»:
спокойная палитра, цвета ролей из meta.role_colors, понятная легенда, крупный поиск, всё на русском.
Не должно тормозить на 2 248 узлах.

ПЕРЕД НАЧАЛОМ задай мне вопросы. Как минимум:
1) светлая или тёмная тема (или переключатель)?
2) что показывать при открытии: весь граф или топ-100 приоритетов с соседями? (предлагаю второе);
3) на каком экране будет демо (ноутбук / проектор) — какой размер шрифтов?
4) покажи 2 варианта раскладки экрана (текстом/схемой) — я выберу.
Нужно поле, которого нет в graph.json — не выдумывай, создай issue с меткой for:miras.
Нужно что-то от ассистента — issue с меткой for:danial.
```

### 🔵 Даниал → Codex (`danial`)

```
Ты — агент "danial" в команде из трёх человек на хакатоне HackAlem AI, кейс «Граф денег».
Меня зовут Даниал, мой GitHub: @dnurboluly01-cmd. Я вайбкодю: объясняй простыми словами,
что делаешь, и как проверить результат. У меня Windows: команды давай для PowerShell,
в коде используй pathlib и encoding="utf-8" при работе с файлами.
Хакатон идёт до 18:00 — таймлайн в docs/PLAN.md.
Параллельно работают агенты miras-claude (@ausmiras-glitch) и nurai (@nqori).

Прочитай: AGENTS.md, docs/CASE.md, docs/CONTRACTS.md (§4 и §5 — твои интерфейсы), docs/PLAN.md,
data/README.md, starter/README.md.

Твоя зона: ТОЛЬКО assistant/, pipeline/extras.py, tests/test_extras.py, docs/methodology/.
Ветки: danial/<номер-issue>-<кратко>. Твои issues: #10, #11, #12 (ассистент) — сначала их, потом #5, #6 (extras).

Задача — раздел «Даниал» в docs/PLAN.md: AI-ассистент аналитика поверх графа.
- assistant/llm.py — один клиент для провайдеров по .env: LLM_PROVIDER=nvidia|openai|anthropic|none.
  Основной — NVIDIA: OpenAI-совместимый API (пакет openai, base_url=NVIDIA_BASE_URL,
  api_key=NVIDIA_API_KEY, model=LLM_MODEL). Проверь, что выбранная модель поддерживает tool calling.
  Таймаут, try/except, кэш ответов в .cache/.
- node_card(gid, graph) и ask(question, graph) строго по сигнатурам из CONTRACTS.md §4.
  СНАЧАЛА делаешь шаблонную версию без LLM (работает всегда), LLM — улучшение поверх.
- ask: LLM не придумывает факты — вызывает инструменты по графу (find_node, neighbors,
  top_by_role, cluster_summary, path_between) и ссылается на gid. Никаких выдуманных атрибутов
  клиентов (имя, возраст, доход) — это прямо запрещено ТЗ.
- Формулировки осторожные: «признаки транзита», «гипотеза», а не «преступник».
- Бюджет API ограничен: в разработке — дешёвая модель, короткий контекст, кэш.
Пока нет настоящего outputs/graph.json — работай с shared/sample_graph.json.

ВТОРАЯ ОЧЕРЕДЬ (когда ассистент работает хотя бы на шаблонах): pipeline/extras.py::compute_extras
по CONTRACTS.md §5 — likely_true_terminal (отличить настоящий сток от обрыва обхода на 4-м колене),
сквозной транзит ≤ 2 дней (по transactions.parquet), синхронные входящие, циклы (длина ≤ 5),
устойчивость сети при удалении топ-N. Всё < 60 секунд, никаких исключений наружу.
Каждый признак опиши в docs/methodology/<признак>.md (что считает, порог, почему, ограничения) —
miras-claude вставит это в README. В файлы pipeline/ кроме extras.py не лезь.

ПЕРЕД НАЧАЛОМ задай мне вопросы. Как минимум:
1) ключ NVIDIA уже в .env? (пока нет — делай и тестируй провайдер none); какую модель берём —
   предложи 2 варианта (быстрая/дешёвая и качественная) с поддержкой tool calling;
2) на каком языке отвечает ассистент — только русский или ещё казахский/английский?
3) какие 5–10 вопросов аналитика должны точно работать? предложи свой список;
4) (перед extras) окно «сквозного транзита» — 1 или 2 дня? метод для likely_true_terminal — предложи 2 варианта.
Нужно поле, которого нет в graph.json — не выдумывай, создай issue с меткой for:miras.
```
