# Purpose: load runtime modules under isolated names for monkeypatch-heavy tests.

"""Isolated module loaders used by component tests."""

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]


def load_runtime(relative: str, module_name: str) -> ModuleType:
    """Execute one runtime module under an isolated test-only module name."""
    path = (ROOT / relative).resolve()
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test runtime: {relative}")
    spec.loader.exec_module(module)
    return module


def load_worker(module_name: str = "isolated_ladder_worker") -> ModuleType:
    """Load the execution worker without invoking its CLI."""
    return load_runtime(
        "ladder_dragon/execution/worker/runtime.py",
        module_name,
    )


def load_dashboard(
    monkeypatch,
    module_name: str = "isolated_dashboard",
    *,
    auth_token: str | None = "test-secret-token",
) -> ModuleType:
    """Load the dashboard with production control paths explicitly disabled."""
    if auth_token is not None:
        monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", auth_token)
    monkeypatch.setenv("DASHBOARD_ENABLE_LOGS", "0")
    monkeypatch.setenv(
        "BOT_MAINTENANCE_FILE",
        "/nonexistent/ladder-dragon-test-maintenance.json",
    )
    return load_runtime("ladder_dragon/dashboard/runtime.py", module_name)
