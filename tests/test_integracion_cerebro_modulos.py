"""El cerebro debe ver a todos los módulos de Shomer, no solo a algunos.

Auditoría de integración (9 sep 2026): el cerebro se apoya en `memoria_incidentes`
como bitácora unificada, pero solo se sincronizaban Guardian, Inframonitor,
Hunter y auto_task. **Protector quedaba fuera**, así que veía 3 de los 5 módulos.

Importa porque los equipos se solapan: en Ópera el 192.168.0.5 es "SRV Zeus PMS"
en Protector y "SRVZEUS" en Inframonitor — el servidor del PMS del hotel. Si la
copia falla la misma madrugada en que Infra vio caer ese equipo, la causa es una
sola, pero el técnico recibía dos avisos sueltos sin relación entre sí.
"""
import sqlite3
import unittest

from core import brain, memoria_central as mc


class TestProtectorLlegaAlCerebro(unittest.TestCase):
    def test_el_sync_esta_en_el_ciclo(self):
        import inspect

        src = inspect.getsource(mc.run_sync_once)
        self.assertIn("_sync_protector_backups", src)

    def test_prompt_describe_protector(self):
        self.assertIn("Protector=copias de seguridad", brain._SYSTEM_PROMPT)

    def test_prompt_explica_la_correlacion(self):
        """El modelo debe saber que un backup_error sobre una IP caída es una
        sola causa, no dos problemas."""
        self.assertIn("backup_error", brain._SYSTEM_PROMPT)


class TestCorrelacionRealEntreModulos(unittest.TestCase):
    """El escenario que motivó el cambio, con datos con forma real."""

    CLUSTER = [
        {"id": 1, "ts": "2026-09-09 05:00:10", "source": "infra",
         "entity_ip": "192.168.0.5", "entity_name": "SRVZEUS",
         "device_type": "server", "event": "online→offline",
         "detail": "sin respuesta ping", "severity": "critical"},
        {"id": 2, "ts": "2026-09-09 05:01:35", "source": "protector",
         "entity_ip": "192.168.0.5", "entity_name": "SRV Zeus PMS",
         "device_type": "backup", "event": "backup_error",
         "detail": "error: SMB FALLO - Connection timed out",
         "severity": "critical"},
    ]

    def test_se_agrupan_como_un_solo_equipo(self):
        ents = brain._cluster_entities(self.CLUSTER)
        self.assertEqual(
            len(ents), 1,
            "es el mismo equipo físico visto por dos módulos: una entidad, no dos",
        )
        self.assertEqual(ents[0]["ip"], "192.168.0.5")

    def test_escala_al_modelo(self):
        ents = brain._cluster_entities(self.CLUSTER)
        self.assertTrue(brain._should_escalate_to_llm(self.CLUSTER, ents))

    def test_quedan_en_la_misma_ventana_temporal(self):
        """85 segundos de diferencia: deben caer en el mismo cluster."""
        grupos = brain._cluster_by_time(self.CLUSTER, brain.CLUSTER_WINDOW_MIN)
        self.assertEqual(len(grupos), 1, "no deben partirse en dos incidentes")


class TestSyncIdempotente(unittest.TestCase):
    def test_no_duplica_eventos(self):
        """Sin índice UNIQUE, el INSERT OR IGNORE no deduplica: la protección
        real es el checkpoint. Si se rompe, cada ciclo duplicaría el evento."""
        con = sqlite3.connect(":memory:")
        con.execute(
            "CREATE TABLE memoria_checkpoints (source TEXT PRIMARY KEY, last_id INTEGER DEFAULT 0)"
        )
        mc._set_checkpoint(con, "protector_backups", 1757400000)
        self.assertEqual(mc._get_checkpoint(con, "protector_backups"), 1757400000)
        # Un segundo guardado con el mismo valor no crea otra fila.
        mc._set_checkpoint(con, "protector_backups", 1757400000)
        n = con.execute(
            "SELECT COUNT(*) FROM memoria_checkpoints WHERE source='protector_backups'"
        ).fetchone()[0]
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
