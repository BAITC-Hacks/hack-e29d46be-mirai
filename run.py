#!/usr/bin/env python3
"""Одна команда для жюри: считает пайплайн и запускает интерфейс.

    python run.py                  # пайплайн + сервер на http://localhost:8000
    python run.py --no-serve       # только пайплайн (3 CSV + graph.json в outputs/)
    python run.py --skip-pipeline  # только сервер на уже посчитанных outputs/
"""

import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description="Граф денег: пайплайн + интерфейс")
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs")
    ap.add_argument("--no-serve", action="store_true", help="не запускать интерфейс")
    ap.add_argument("--skip-pipeline", action="store_true", help="не пересчитывать выгрузки")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()

    if not a.skip_pipeline:
        from pipeline.main import run
        run(a.data, a.out)

    if a.no_serve:
        return
    if importlib.util.find_spec("app") is None or importlib.util.find_spec("app.server") is None:
        print("Интерфейс (app/server.py) ещё не готов — выгрузки лежат в", a.out)
        return
    import uvicorn
    print(f"Интерфейс: http://localhost:{a.port}")
    uvicorn.run("app.server:app", host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
