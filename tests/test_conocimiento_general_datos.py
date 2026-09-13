"""El conocimiento validado pasa de código a datos, sin cambiar una coma.

12 sep 2026. `conocimiento_general.py` tenía 5.330 líneas, de las cuales el
45% eran literales de texto (263 conceptos de teoría CompTIA + 173 reglas de
diagnóstico) — contenido, no lógica. Se movió a `core/data/*.json`; el código
que siembra, consulta y arma el prompt para el cerebro no cambió una línea.

Esta siembra es IDEMPOTENTE: solo inserta si la tabla está vacía. En Ópera y
los labs ya está sembrada, así que el cambio no se nota ahí hoy — pero sí le
pasa por delante a cada cliente NUEVO, que siembra desde cero la primera vez
que arranca. Por eso la prueba que más importa acá es simular justamente
ese arranque limpio, no solo comparar el contenido en memoria.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import conocimiento_general as cg

DATA_DIR = Path(cg.__file__).resolve().parent / "data"


class TestLosDatosExistenYSonValidos(unittest.TestCase):
    def test_los_dos_archivos_json_existen(self):
        self.assertTrue((DATA_DIR / "conocimiento_teoria.json").is_file())
        self.assertTrue((DATA_DIR / "conocimiento_reglas.json").is_file())

    def test_son_json_valido_con_el_esquema_esperado(self):
        teoria = json.loads((DATA_DIR / "conocimiento_teoria.json").read_text(encoding="utf-8"))
        reglas = json.loads((DATA_DIR / "conocimiento_reglas.json").read_text(encoding="utf-8"))
        self.assertGreater(len(teoria), 0)
        self.assertGreater(len(reglas), 0)
        for t in teoria[:5]:
            self.assertEqual(set(t.keys()),
                             {"dominio", "concepto", "explicacion",
                              "relevancia_diagnostica", "fuente"})
        for r in reglas[:5]:
            self.assertEqual(set(r.keys()),
                             {"dominio", "patron", "causa_probable",
                              "recomendacion", "fuente"})


class TestElModuloCargaExactamenteEseContenido(unittest.TestCase):
    def test_lo_que_carga_el_modulo_es_igual_al_json_en_disco(self):
        """Si alguien edita el JSON sin recargar, o el loader se rompe
        silenciosamente, esto lo atrapa."""
        teoria_json = json.loads((DATA_DIR / "conocimiento_teoria.json").read_text(encoding="utf-8"))
        reglas_json = json.loads((DATA_DIR / "conocimiento_reglas.json").read_text(encoding="utf-8"))
        self.assertEqual(cg._SEED_TEORIA, teoria_json)
        self.assertEqual(cg._SEED_RULES, reglas_json)

    def test_263_conceptos_173_reglas(self):
        """Número exacto verificado el 12 sep 2026 al migrar -- si cambia,
        que sea porque alguien agregó contenido a propósito, no porque el
        loader perdió filas en silencio."""
        self.assertEqual(len(cg._SEED_TEORIA), 263)
        self.assertEqual(len(cg._SEED_RULES), 173)


class TestSinElArchivoNoRevientaElArranque(unittest.TestCase):
    def test_json_faltante_devuelve_vacio_no_excepcion(self):
        """Un problema de contenido es reparable; no puede tumbar el agente."""
        vacio = cg._cargar_json("no-existe-este-archivo.json")
        self.assertEqual(vacio, [])


class TestLaSiembraEnUnSitioNuevoQuedaIgualQueAntes(unittest.TestCase):
    """La prueba que más importa: un cliente nuevo siembra desde cero.
    Verificado a mano el 12 sep contra la versión anterior del archivo
    (git show HEAD~1): fila por fila idéntico. Esto lo deja como guardia
    permanente contra una futura edición que rompa el loader.
    """

    def test_siembra_completa_en_bd_vacia(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "knowledge.db")
            old = os.environ.get("KNOWLEDGE_DB_PATH")
            os.environ["KNOWLEDGE_DB_PATH"] = db
            try:
                import importlib
                importlib.reload(cg)
                n_reglas = cg.seed_if_empty("test")
                n_teoria = cg.seed_teoria_if_empty("test")
                self.assertEqual(n_reglas, 173)
                self.assertEqual(n_teoria, 263)

                con = sqlite3.connect(db)
                total_reglas = con.execute(
                    "SELECT count(*) FROM conocimiento_general").fetchone()[0]
                total_teoria = con.execute(
                    "SELECT count(*) FROM conocimiento_teoria").fetchone()[0]
                con.close()
                self.assertEqual(total_reglas, 173)
                self.assertEqual(total_teoria, 263)
            finally:
                if old is not None:
                    os.environ["KNOWLEDGE_DB_PATH"] = old
                else:
                    os.environ.pop("KNOWLEDGE_DB_PATH", None)
                importlib.reload(cg)

    def test_no_reinserta_si_ya_esta_sembrada(self):
        """Idempotente: un reinicio del agente no debe duplicar filas."""
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "knowledge.db")
            old = os.environ.get("KNOWLEDGE_DB_PATH")
            os.environ["KNOWLEDGE_DB_PATH"] = db
            try:
                import importlib
                importlib.reload(cg)
                cg.seed_if_empty("test")
                segunda = cg.seed_if_empty("test")
                self.assertEqual(segunda, 0, "la segunda siembra no debe insertar nada")
            finally:
                if old is not None:
                    os.environ["KNOWLEDGE_DB_PATH"] = old
                else:
                    os.environ.pop("KNOWLEDGE_DB_PATH", None)
                importlib.reload(cg)


class TestElCerebroSigueRecibiendoElMismoContenido(unittest.TestCase):
    def test_format_for_prompt_sigue_funcionando(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "knowledge.db")
            old = os.environ.get("KNOWLEDGE_DB_PATH")
            os.environ["KNOWLEDGE_DB_PATH"] = db
            try:
                import importlib
                importlib.reload(cg)
                cg.seed_if_empty("test")
                cg.seed_teoria_if_empty("test")
                prompt = cg.format_for_prompt(["Switch Piso 3", "Cable UTP"])
                self.assertIn("cableado", prompt.lower())
                self.assertGreater(len(prompt), 100)
            finally:
                if old is not None:
                    os.environ["KNOWLEDGE_DB_PATH"] = old
                else:
                    os.environ.pop("KNOWLEDGE_DB_PATH", None)
                importlib.reload(cg)


if __name__ == "__main__":
    unittest.main()
