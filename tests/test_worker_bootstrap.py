import builtins
from pathlib import Path
import symtable

from ladder_dragon.execution.worker.bootstrap import WorkerRuntimeState


BOOTSTRAP = Path("ladder_dragon/execution/worker/bootstrap.py")


def test_runtime_state_reads_live_signal_and_connection_values():
    connection_a = object()
    connection_b = object()
    namespace = {
        "RUN": True,
        "STATS_CON": connection_a,
        "_WS_TRADING_TRANSPORT": None,
    }
    state = WorkerRuntimeState(namespace)

    namespace["RUN"] = False
    namespace["STATS_CON"] = connection_b

    assert state.RUN is False
    assert state.STATS_CON is connection_b


def test_runtime_state_writes_modes_back_to_runtime_namespace():
    namespace = {
        "LIVE_MODE": False,
        "WS_TRADING_MODE": "OFF",
    }
    state = WorkerRuntimeState(namespace)

    state.LIVE_MODE = True
    state.WS_TRADING_MODE = "SHADOW"

    assert namespace == {
        "LIVE_MODE": True,
        "WS_TRADING_MODE": "SHADOW",
    }
    assert state.namespace() is namespace


def test_worker_loop_has_no_snapshot_or_double_qualified_dependencies():
    source = BOOTSTRAP.read_text(encoding="utf-8")
    table = symtable.symtable(source, str(BOOTSTRAP), "exec")
    worker = next(
        child for child in table.get_children()
        if child.get_name() == "run_worker"
    )

    def free_globals(scope):
        names = {
            symbol.get_name()
            for symbol in scope.get_symbols()
            if symbol.is_global()
        }
        for child in scope.get_children():
            names.update(free_globals(child))
        return names

    assert free_globals(worker) <= set(dir(builtins))
    assert ".state." not in source
