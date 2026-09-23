"""The launcher must never serve a different graph from the one it calculated."""
import os
import sys
import types
from pathlib import Path

import pytest

import run as launcher


@pytest.fixture
def launch(monkeypatch, tmp_path):
    calls = {"pipeline": [], "server": [], "discovery": []}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher, "ROOT", tmp_path / "project root")
    # Register the environment mutation with monkeypatch before main changes it.
    monkeypatch.setenv("MIRAI_OUTPUT_DIR", "")

    def pipeline(data, out):
        calls["pipeline"].append((data, out, os.environ.get("MIRAI_OUTPUT_DIR")))

    def discover(name):
        calls["discovery"].append((name, os.environ.get("MIRAI_OUTPUT_DIR")))
        return object()

    def server(target, **kwargs):
        # Uvicorn imports app.server from this target; the setting must already
        # exist before either discovery or server startup.
        calls["server"].append((target, kwargs, os.environ.get("MIRAI_OUTPUT_DIR")))

    monkeypatch.setitem(sys.modules, "pipeline.main", types.SimpleNamespace(run=pipeline))
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=server))
    monkeypatch.setattr(launcher.importlib.util, "find_spec", discover)

    def invoke(args=(), env=""):
        monkeypatch.setenv("MIRAI_OUTPUT_DIR", env)
        monkeypatch.setattr(sys, "argv", ["run.py", *args])
        launcher.main()
        return calls

    return invoke


@pytest.mark.parametrize("source", ["explicit", "environment", "default"])
@pytest.mark.parametrize("mode", ["both", "pipeline_only", "server_only"])
def test_output_precedence_and_mode_consistency(launch, tmp_path, source, mode):
    args = []
    env = ""
    if source == "explicit":
        args += ["--out", "chosen output with spaces"]
        env = str(tmp_path / "different environment output")
        expected = tmp_path / "chosen output with spaces"
    elif source == "environment":
        env = "environment output with spaces"
        expected = tmp_path / env
    else:
        expected = tmp_path / "project root" / "outputs"
    if mode == "pipeline_only":
        args += ["--no-serve"]
    elif mode == "server_only":
        args += ["--skip-pipeline"]

    calls = launch(args, env=env)
    expected = expected.resolve()
    assert Path(os.environ["MIRAI_OUTPUT_DIR"]) == expected
    if mode != "server_only":
        assert calls["pipeline"] == [(launcher.ROOT / "data", expected, str(expected))]
    else:
        assert calls["pipeline"] == []
    if mode != "pipeline_only":
        assert calls["discovery"] == [("app", str(expected)), ("app.server", str(expected))]
        assert calls["server"] == [("app.server:app", {"host": "127.0.0.1", "port": 8000}, str(expected))]
    else:
        assert calls["discovery"] == []
        assert calls["server"] == []


def test_output_expands_home_without_affecting_data_and_port(launch, tmp_path):
    data = tmp_path / "different data"
    calls = launch(["--out", "~/chosen output", "--data", str(data), "--port", "8123"])
    expected = (Path.home() / "chosen output").resolve()
    assert calls["pipeline"] == [(data, expected, str(expected))]
    assert calls["server"][0][1]["port"] == 8123
