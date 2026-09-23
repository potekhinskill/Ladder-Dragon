import sqlite3
import ast
import inspect
from contextlib import closing

import pytest

from ladder_dragon.supervision.aggregate_trade_history import safe_aggregate_trade_error
from ladder_dragon.supervision.prediction_diagnostics import prediction_operation, prediction_failure_status


@pytest.mark.parametrize("lock", ["reader", "retention"])
def test_real_sqlite_contention_reports_stage_and_preserves_rows(tmp_path, lock):
    """Model pinned backup reads and retention's IMMEDIATE writer separately."""
    path = tmp_path / "synthetic.db"
    with closing(sqlite3.connect(path)) as setup:
        setup.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY)")
        setup.execute("INSERT INTO evidence VALUES (1)")
        setup.commit()
    with closing(sqlite3.connect(path)) as owner, closing(
        sqlite3.connect(path, timeout=0.05)
    ) as writer:
        assert owner.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        owner.execute("BEGIN" if lock == "reader" else "BEGIN IMMEDIATE")
        owner.execute("SELECT * FROM evidence").fetchall()

        def write():
            with writer:
                writer.execute("INSERT INTO evidence VALUES (2)")

        def verify_failure(*_):
            with pytest.raises(sqlite3.OperationalError) as caught:
                prediction_operation("strategy_record", write)
            suffix = ("sqlite_code=5 sqlite_name=SQLITE_BUSY"
                      if hasattr(caught.value, "sqlite_errorcode") else "sqlite_name=unknown")
            assert safe_aggregate_trade_error(caught.value) == "OperationalError stage=strategy_record " + suffix

        if lock == "reader":
            # An explicit source transaction pins the snapshot across backup.
            with closing(sqlite3.connect(tmp_path / "copy.db")) as target:
                owner.backup(target, progress=verify_failure)
                assert target.execute("SELECT * FROM evidence").fetchall() == [(1,)]
        else:
            verify_failure()
        owner.rollback()
        assert writer.execute("SELECT * FROM evidence").fetchall() == [(1,)]
        prediction_operation("strategy_record", write)
        assert writer.execute("SELECT * FROM evidence").fetchall() == [(1,), (2,)]


def test_diagnostics_preserve_exception_and_result():
    error = sqlite3.OperationalError("PRIVATE_SQL PRIVATE_PATH PRIVATE_VALUE")
    error.sqlite_errorcode = 14
    error.sqlite_errorname = "PRIVATE_PROVIDER_TEXT"

    def fail():
        raise error

    with pytest.raises(sqlite3.OperationalError) as caught:
        prediction_operation("settle", fail)
    assert caught.value is error
    summary = safe_aggregate_trade_error(error)
    assert summary == "OperationalError stage=settle sqlite_code=14 sqlite_name=SQLITE_CANTOPEN"
    assert "PRIVATE" not in summary
    assert prediction_operation("summary", lambda x: x, 7) == 7
    with pytest.raises(ValueError, match="unknown prediction"):
        prediction_operation("PRIVATE_STAGE", fail)


@pytest.mark.parametrize("code", [None, True, -1, 65536, "PRIVATE_CODE"])
def test_untrusted_sqlite_fields_are_not_echoed(code):
    error = sqlite3.OperationalError("PRIVATE_SQL")
    error.sqlite_errorcode = code
    error.prediction_stage = ["PRIVATE_STAGE"]
    assert safe_aggregate_trade_error(error) == "OperationalError stage=unknown sqlite_name=unknown"


def test_non_sqlite_failure_is_not_reclassified():
    error = ValueError("PRIVATE")
    with pytest.raises(ValueError) as caught:
        prediction_operation("summary", lambda: (_ for _ in ()).throw(error))
    assert caught.value is error
    assert not hasattr(error, "prediction_stage")


def test_actual_supervisor_handler_reports_safe_detail_without_authority():
    from ladder_dragon.supervision import runtime

    tree = ast.parse(inspect.getsource(runtime.run_for_symbol))
    block = next(node for node in ast.walk(tree) if isinstance(node, ast.Try)
                 and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                         and call.func.id == "_record_prediction_shadow"
                         for statement in node.body for call in ast.walk(statement)))
    error = sqlite3.OperationalError("PRIVATE_SQL PRIVATE_PATH")
    error.sqlite_errorcode = 5
    error.prediction_stage = "settle"
    block.body = [ast.Raise(exc=ast.Name(id="failure", ctx=ast.Load()), cause=None)]
    logs, published = [], []
    scope = {"failure": error, "symbol": "SYNTHETIC", "log": logs.append,
             "SUPERVISOR_OPERATION_ERRORS": (sqlite3.Error,),
             "safe_aggregate_trade_error": safe_aggregate_trade_error,
             "prediction_failure_status": prediction_failure_status,
             "_AI_RUNTIME_STATUS": {},
             "_publish_ai_runtime_status": lambda: published.append(True)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[block], type_ignores=[])),
                 "<actual-supervisor-handler>", "exec"), scope)
    status = scope["_AI_RUNTIME_STATUS"]["prediction"]
    assert status["last_error"] == "OperationalError"
    assert "stage=settle sqlite_code=5 sqlite_name=SQLITE_BUSY" in status["last_error_detail"]
    assert status["mode"] == "SHADOW" and status["can_change_orders"] is False
    assert published == [True]
    assert "PRIVATE" not in repr(status) + repr(logs)
