"""16 sep 2026: el chat libre no tenía ninguna forma de ver los hallazgos
del cerebro -- solo el comando /cerebro podía llamar a brain.list_recent().
Si alguien preguntaba en texto libre "por qué se cayeron varios equipos
juntos", el modelo no tenía tool para consultar lo que el cerebro ya
correlacionó (causa común entre Guardian+Infra+Hunter+Protector), y tenía
que reinventar el análisis desde cero con herramientas más limitadas.
"""
import importlib
import sqlite3

import pytest

from core import tools


@pytest.fixture()
def con_hallazgos(temp_db_path):
    from core import brain

    importlib.reload(brain)
    con = sqlite3.connect(temp_db_path)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS brain_conclusions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now')),
            entities TEXT NOT NULL, sources TEXT NOT NULL,
            root_cause TEXT NOT NULL, recommendation TEXT NOT NULL,
            urgency TEXT NOT NULL, evidence_count INTEGER DEFAULT 0,
            sent_telegram INTEGER DEFAULT 0
        )
        """
    )
    con.execute(
        "INSERT INTO brain_conclusions (entities, sources, root_cause, recommendation, "
        "urgency, sent_telegram) VALUES (?,?,?,?,?,?)",
        ("Terminal .136, Terminal .143", "infra", "Switch troncal compartido",
         "Revisar el switch troncal", "media", 1),
    )
    con.commit()
    con.close()


def test_get_cerebro_findings_trae_hallazgos_reales(con_hallazgos):
    r = tools.execute("get_cerebro_findings", {"limit": 5})
    assert r["total"] == 1
    h = r["hallazgos"][0]
    assert "Switch troncal" in h["causa_probable"]
    assert h["se_avisó_por_telegram"] is True


def test_sin_hallazgos_da_mensaje_honesto_no_error(temp_db_path):
    """Base vacía (recién creada) -- 0 hallazgos es un estado real, no un
    fallo. brain_conclusions ya se crea por el propio módulo al importarlo."""
    from core import brain

    importlib.reload(brain)
    r = tools.execute("get_cerebro_findings", {})
    assert r["total"] == 0
    assert "mensaje" in r
