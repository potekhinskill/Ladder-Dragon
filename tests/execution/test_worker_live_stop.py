import signal

from ladder_dragon.execution.worker import runtime


def test_worker_signal_log_identifies_sigterm(monkeypatch, capsys):
    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda number, handler: handlers.setdefault(number, handler))
    runtime.RUN = True
    runtime.install_signal_handlers()

    handlers[signal.SIGTERM](signal.SIGTERM, None)

    assert runtime.RUN is False
    assert "SIGTERM requested graceful worker shutdown" in capsys.readouterr().out


def test_buy_service_reads_live_run_flag_between_candidates(monkeypatch):
    source = __import__("inspect").getsource(
        __import__("ladder_dragon.execution.worker.buy_service", fromlist=["place_buys"]).place_buys
    )
    assert "def running()" in source
    assert source.count("if not running()") >= 3
    assert "RUN = _runtime_dependency" not in source
