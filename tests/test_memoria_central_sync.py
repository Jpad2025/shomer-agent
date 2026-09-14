"""core/memoria_central.py -- la bitácora unificada que alimenta directamente
a brain.py (el cerebro) y a /bitacora, /historial. Si el sync de alguna
fuente se rompe en silencio (está diseñado para no tumbar el resto si una
falla), el cerebro empieza a razonar con información vieja o incompleta y
la calidad de la recomendación baja sin que se vea ningún error en ningún
lado. Estas pruebas simulan las 3 bases fuente reales (network_monitor.db,
knowledge.db) para verificar que cada sync trae lo que debe traer, no
duplica al re-sincronizar, y que la poda no se lleva algo reciente.
"""
import importlib
import sqlite3

import pytest


def _make_network_monitor_db(path: str) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE status_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, source TEXT, name TEXT, ip TEXT, device_type TEXT,
            prev_status TEXT, status TEXT, reason TEXT, batch_id TEXT, loss_pct REAL
        );
        CREATE TABLE blocked_ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT, blocked_at TEXT, blocked_by TEXT, alert_signature TEXT,
            severity INTEGER, unblocked_at TEXT
        );
        CREATE TABLE backup_devices (
            name TEXT, ip TEXT, last_backup_at TEXT, last_status TEXT,
            last_size_mb REAL, last_files_count INTEGER
        );
        """
    )
    con.commit()
    con.close()


def _make_knowledge_db_con_auto_task_runs(path: str) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE auto_task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT, mode TEXT, ok INTEGER, green_ok INTEGER,
            action TEXT, detail TEXT, created_at TEXT
        )
        """
    )
    con.commit()
    con.close()


@pytest.fixture()
def mc(tmp_path, monkeypatch):
    nm_path = str(tmp_path / "network_monitor_test.db")
    kn_path = str(tmp_path / "knowledge_test.db")
    mem_path = str(tmp_path / "memoria_test.db")
    _make_network_monitor_db(nm_path)
    _make_knowledge_db_con_auto_task_runs(kn_path)

    monkeypatch.setenv("NETWORK_MONITOR_DB_PATH", nm_path)
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", kn_path)
    monkeypatch.setenv("MEMORIA_DB_PATH", mem_path)

    from core import memoria_central as _mc

    importlib.reload(_mc)
    yield _mc, nm_path, kn_path


def _insert_status_event(nm_path, **kw):
    defaults = dict(
        ts="2026-09-13 10:00:00", source="guardian", name="AP-1", ip="192.168.0.10",
        device_type="ap", prev_status="online", status="offline",
        reason="ping falla", batch_id="", loss_pct=None,
    )
    defaults.update(kw)
    con = sqlite3.connect(nm_path)
    con.execute(
        "INSERT INTO status_events (ts, source, name, ip, device_type, prev_status, "
        "status, reason, batch_id, loss_pct) VALUES (?,?,?,?,?,?,?,?,?,?)",
        tuple(defaults.values()),
    )
    con.commit()
    con.close()


class TestSyncStatusEvents:
    def test_trae_eventos_nuevos_a_memoria_incidentes(self, mc):
        memoria, nm_path, _ = mc
        _insert_status_event(nm_path)

        con = sqlite3.connect(memoria.MEMORIA_DB)
        n = memoria._sync_status_events(con)
        con.commit()
        con.close()

        assert n == 1
        incidents = memoria.list_incidents(hours=999999)
        assert len(incidents) == 1
        assert incidents[0]["entity_ip"] == "192.168.0.10"
        assert incidents[0]["event"] == "online→offline"

    def test_no_duplica_al_correr_dos_veces_por_el_checkpoint(self, mc):
        memoria, nm_path, _ = mc
        _insert_status_event(nm_path)

        con = sqlite3.connect(memoria.MEMORIA_DB)
        memoria._sync_status_events(con)
        segunda_pasada = memoria._sync_status_events(con)
        con.commit()
        con.close()

        assert segunda_pasada == 0
        assert len(memoria.list_incidents(hours=999999)) == 1

    def test_offline_es_warn_recuperacion_es_info(self, mc):
        memoria, nm_path, _ = mc
        _insert_status_event(nm_path, prev_status="online", status="offline")
        _insert_status_event(nm_path, prev_status="offline", status="online")

        con = sqlite3.connect(memoria.MEMORIA_DB)
        memoria._sync_status_events(con)
        con.commit()
        con.close()

        incidents = {i["event"]: i["severity"] for i in memoria.list_incidents(hours=999999)}
        assert incidents["online→offline"] == "warn"
        assert incidents["offline→online"] == "info"


class TestSyncHunterBlocks:
    def _insert_block(self, nm_path, ip="10.0.0.5", severity=3, unblocked_at=None):
        con = sqlite3.connect(nm_path)
        con.execute(
            "INSERT INTO blocked_ips (ip, blocked_at, blocked_by, alert_signature, "
            "severity, unblocked_at) VALUES (?,?,?,?,?,?)",
            (ip, "2026-09-13 08:00:00", "hunter", "port scan", severity, unblocked_at),
        )
        con.commit()
        con.close()

    def test_bloqueo_sin_desbloquear_genera_un_evento(self, mc):
        memoria, nm_path, _ = mc
        self._insert_block(nm_path)

        con = sqlite3.connect(memoria.MEMORIA_DB)
        memoria._sync_hunter_blocks(con)
        con.commit()
        con.close()

        incidents = memoria.list_incidents(hours=999999)
        assert len(incidents) == 1
        assert incidents[0]["event"] == "bloqueo"
        assert incidents[0]["severity"] == "critical"

    def test_bloqueo_ya_desbloqueado_genera_dos_eventos(self, mc):
        memoria, nm_path, _ = mc
        self._insert_block(nm_path, unblocked_at="2026-09-13 09:00:00", severity=0)

        con = sqlite3.connect(memoria.MEMORIA_DB)
        memoria._sync_hunter_blocks(con)
        con.commit()
        con.close()

        eventos = {i["event"] for i in memoria.list_incidents(hours=999999)}
        assert eventos == {"bloqueo", "desbloqueo"}


class TestSyncProtectorBackups:
    def _insert_backup(self, nm_path, status="12 archivos", ts="2026-09-13 05:00:00"):
        con = sqlite3.connect(nm_path)
        con.execute(
            "INSERT INTO backup_devices (name, ip, last_backup_at, last_status, "
            "last_size_mb, last_files_count) VALUES (?,?,?,?,?,?)",
            ("SRV Zeus PMS", "192.168.0.5", ts, status, 120.5, 12),
        )
        con.commit()
        con.close()

    def test_backup_ok_queda_como_info(self, mc):
        memoria, nm_path, _ = mc
        self._insert_backup(nm_path, status="ok")

        con = sqlite3.connect(memoria.MEMORIA_DB)
        memoria._sync_protector_backups(con)
        con.commit()
        con.close()

        incidents = memoria.list_incidents(hours=999999)
        assert incidents[0]["event"] == "backup_ok"
        assert incidents[0]["severity"] == "info"

    def test_backup_con_error_queda_como_critical(self, mc):
        memoria, nm_path, _ = mc
        self._insert_backup(nm_path, status="error: credenciales inválidas")

        con = sqlite3.connect(memoria.MEMORIA_DB)
        memoria._sync_protector_backups(con)
        con.commit()
        con.close()

        incidents = memoria.list_incidents(hours=999999)
        assert incidents[0]["event"] == "backup_error"
        assert incidents[0]["severity"] == "critical"


class TestSyncAutoTaskRuns:
    def test_trae_ejecuciones_del_catalogo(self, mc):
        memoria, _, kn_path = mc
        con_k = sqlite3.connect(kn_path)
        con_k.execute(
            "INSERT INTO auto_task_runs (task_id, mode, ok, green_ok, action, "
            "detail, created_at) VALUES (?,?,?,?,?,?,?)",
            ("TASK-001", "approved", 1, 1, "limpieza disco", "86%→74%", "2026-09-13 03:00:00"),
        )
        con_k.commit()
        con_k.close()

        con = sqlite3.connect(memoria.MEMORIA_DB)
        n = memoria._sync_auto_task_runs(con)
        con.commit()
        con.close()

        assert n == 1
        incidents = memoria.list_incidents(hours=999999, source="auto_task")
        assert incidents[0]["entity_name"] == "TASK-001"
        assert incidents[0]["event"] == "limpieza disco"


class TestRunSyncOnceEsResiliente:
    def test_no_revienta_si_network_monitor_db_no_existe(self, mc, monkeypatch, tmp_path):
        """Si el servidor está en medio de un backup o el archivo no está
        montado todavía, el sync completo no debe caerse -- debe seguir con
        las demás fuentes y devolver 0 para la que faltó."""
        memoria, _, _ = mc
        monkeypatch.setenv("NETWORK_MONITOR_DB_PATH", str(tmp_path / "no_existe.db"))
        importlib.reload(memoria)

        counts = memoria.run_sync_once()
        assert counts["status_events"] == 0
        assert counts["hunter_blocks"] == 0
        assert counts["protector_backups"] == 0


class TestPoda:
    def test_prune_borra_incidentes_viejos_mantiene_recientes(self, mc, monkeypatch):
        memoria, _, _ = mc
        monkeypatch.setenv("MEMORIA_RETENTION_DAYS", "30")
        importlib.reload(memoria)

        con = sqlite3.connect(memoria.MEMORIA_DB)
        con.execute(
            "INSERT INTO memoria_incidentes (ts, source, entity_ip, event) "
            "VALUES (datetime('now', '-200 days'), 'guardian', '1.1.1.1', 'viejo')"
        )
        con.execute(
            "INSERT INTO memoria_incidentes (ts, source, entity_ip, event) "
            "VALUES (datetime('now', '-5 days'), 'guardian', '2.2.2.2', 'reciente')"
        )
        con.commit()
        memoria._prune(con)
        con.commit()

        eventos = [r[0] for r in con.execute("SELECT event FROM memoria_incidentes")]
        con.close()
        assert eventos == ["reciente"]


class TestStats:
    def test_stats_cuenta_por_fuente(self, mc):
        memoria, nm_path, _ = mc
        _insert_status_event(nm_path, ip="1.1.1.1")
        _insert_status_event(nm_path, ip="2.2.2.2", source="infra")

        con = sqlite3.connect(memoria.MEMORIA_DB)
        memoria._sync_status_events(con)
        con.commit()
        con.close()

        s = memoria.stats(hours=999999)
        assert s["by_source"]["guardian"] == 1
        assert s["by_source"]["infra"] == 1
