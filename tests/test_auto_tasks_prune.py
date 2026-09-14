"""Poda de auto_task_runs (13 sep 2026) -- knowledge.db no tenía retención,
a diferencia de memoria.db. auto_task_stats guarda los contadores acumulados
aparte, así que podar el log detallado no debe perder ese historial de
decisión, solo las filas de ejecuciones viejas."""
import importlib
import sqlite3

import pytest


@pytest.fixture()
def at(temp_db_path, monkeypatch):
    monkeypatch.setenv("AUTO_TASK_RUNS_RETENTION_DAYS", "180")
    from core import auto_tasks as _at

    importlib.reload(_at)
    yield _at


def _insert_run(db_path: str, task_id: str, days_old: int) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO auto_task_runs (task_id, mode, ok, green_ok, action, detail, created_at)
        VALUES (?, 'approved', 1, 1, 'test', 'test', datetime('now', ?))
        """,
        (task_id, f"-{days_old} days"),
    )
    con.commit()
    con.close()


def test_prune_borra_filas_viejas_de_auto_task_runs(at, temp_db_path):
    _insert_run(temp_db_path, "TASK-001", days_old=200)
    _insert_run(temp_db_path, "TASK-002", days_old=5)

    result = at.TaskRunResult(
        task_id="TASK-001", ok=True, action="limpieza", green_ok=True, green_detail="ok",
    )
    at._log_run(result, "approved")

    con = sqlite3.connect(temp_db_path)
    rows = con.execute("SELECT task_id FROM auto_task_runs ORDER BY task_id").fetchall()
    con.close()

    ids = [r[0] for r in rows]
    assert "TASK-002" in ids, "la fila reciente (5 días) no debería podarse"
    assert ids.count("TASK-001") == 1, (
        "debería quedar solo la fila recién insertada por _log_run; "
        "la de 200 días tenía que podarse"
    )


def test_prune_no_toca_auto_task_stats(at, temp_db_path):
    """Los contadores acumulados (runs_total, etc.) no dependen de las filas
    crudas de auto_task_runs -- podar el log no debe perder esa cuenta."""
    result = at.TaskRunResult(
        task_id="TASK-002", ok=True, action="restart", green_ok=True, green_detail="ok",
    )
    at._log_run(result, "approved")
    at._log_run(result, "approved")

    con = sqlite3.connect(temp_db_path)
    con.execute(
        "UPDATE auto_task_runs SET created_at = datetime('now', '-300 days') WHERE task_id='TASK-002'"
    )
    con.commit()
    con.close()

    at._log_run(result, "approved")

    stats = at.get_task_stats("TASK-002")
    assert stats["runs_total"] == 3

    con = sqlite3.connect(temp_db_path)
    n = con.execute(
        "SELECT COUNT(*) FROM auto_task_runs WHERE task_id='TASK-002'"
    ).fetchone()[0]
    con.close()
    assert n == 1, "las filas viejas se podaron, pero el contador acumulado sigue en 3"
